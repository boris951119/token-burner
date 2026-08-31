"""模块化开发循环（规格文档 3.5 节、3.7 节、3.8 节、8.4 节、11.4 节、12.4 节）。

逐模块「开发 → 测试 → 执行 → 反馈 → 修复」循环：
- Dev Agent（开发副 LLM）生成模块代码与修复补丁；
- Test Agent（测试副 LLM）生成可独立运行的测试文件（3.7）；
- Executor 执行（安全模式 SKIPPED → AWAITING_FEEDBACK，等待用户
  手动运行反馈，3.8 闭环由 resume_with_feedback 驱动）；
- 修复上限（11.4）：单模块默认 5 次修复尝试，达上限仍失败 →
  冻结该模块并输出「已知问题与降级方案」（保留代码与失败记录）；
- fix_history 落盘（12.4）：changelog/<module>/fix_history.md。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.config import Settings
from app.execution.executor import ExecutionResult, ExecutionStatus, Executor
from app.tools.file_manager import FileManager
from app.tools.prompt_templates import (
    FIX_CODE_SYSTEM,
    FIX_CODE_USER,
    WRITE_CODE_SYSTEM,
    WRITE_CODE_USER,
    WRITE_TESTS_SYSTEM,
    WRITE_TESTS_USER,
)
from app.utils.interface_check import check_implementation
from app.utils.static_check import run_static_check
from app.utils.untrusted import sanitize_untrusted

# 判定「执行失败」的状态集合（8.4：进入修复循环）
_RETRYABLE = {ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT}

# 12.7 模块文档同步章节（文档即代码）
_MD_FIX_HEADING = "## 修复记录"
_MD_STATUS_HEADING = "## 当前状态"
_MD_DIGEST_LIMIT = 120  # 修复记录失败摘要截断长度（单行可读）

# 12.7/14.4：LLM 输出中的公共层代码标记块（解析后落盘 code/_shared/）
_SHARED_BLOCK = re.compile(
    r"# ==== shared: (\S+?) ====\n(.*?)# ==== end shared ====", re.DOTALL
)

# 真实运行回归：LLM 无视「仅输出代码」时常用 markdown 围栏包裹代码，
# ast.parse 在第 1 行（```python）即报语法错误 → 门禁死循环至冻结
_FENCED_CODE = re.compile(
    r"```[ \t]*[A-Za-z0-9_+-]*[ \t]*\n(.*?)```", re.DOTALL
)


def _extract_code(content: str) -> str:
    """从 LLM 输出提取代码（确定性，零 LLM）。

    - 含围栏：取最长围栏块（多块时说明性片段被丢弃）；
    - 只有开启围栏（输出截断）：剥围栏行及此前说明，取其余全部；
    - 无围栏：原样返回（提示词已约束仅输出代码）。
    """
    blocks = _FENCED_CODE.findall(content)
    if blocks:
        return max(blocks, key=len)
    open_fence = re.search(r"```[ \t]*[A-Za-z0-9_+-]*[ \t]*\n", content)
    if open_fence:
        return content[open_fence.end():]
    return content


def _extract_shared_blocks(content: str) -> tuple[dict[str, str], str]:
    """解析 LLM 输出中的 _shared 标记块。

    Returns:
        (文件名 → 公共层代码, 剥离标记块后的模块自身代码)。
    """
    shared: dict[str, str] = {}

    def _strip(match: re.Match) -> str:
        shared[match.group(1)] = match.group(2)
        return ""

    rest = _SHARED_BLOCK.sub(_strip, content)
    return shared, rest


class ModuleStatus(Enum):
    SUCCESS = "SUCCESS"
    FROZEN = "FROZEN"   # 11.4：修复上限耗尽
    # 3.8：安全模式 SKIPPED → 等待用户手动运行反馈（保留现场，不空耗修复轮）
    AWAITING_FEEDBACK = "AWAITING_FEEDBACK"


@dataclass
class ModuleResult:
    """单模块开发结果（8.4 结构映射）。"""

    module: str
    status: ModuleStatus
    fix_attempts: int
    message: str
    code: str = ""
    tests: str = ""


class DevLoopEngine:
    """逐模块开发循环编排（3.5 节）。"""

    def __init__(
        self,
        llm,
        dev_model: str,
        test_model: str,
        executor: Executor,
        settings: Settings,
        file_manager: FileManager,
        budget_guard=None,
    ):
        self.llm = llm
        self.dev_model = dev_model
        self.test_model = test_model
        self.executor = executor
        self.settings = settings
        self.file_manager = file_manager
        self.budget_guard = budget_guard  # 11.0 总闸（超预算立即中止上抛）
        # 12.7/14.4：当前任务项目（shared 块落盘归属）
        self._active_project_id: str | None = None
        # M4-3：_shared 上下文缓存（同任务跨模块复用，不重复读盘；
        # None = 未缓存。_split_shared 写入新公共块时失效）
        self._shared_ctx_cache: str | None = None

    # ------------------------------------------------------------------

    def _shared_context(self) -> str:
        """M4-3：code/_shared/ 公共层上下文（同任务缓存，跨模块零重读）。

        空目录缓存空串（避免每模块都探测一次盘）；_shared 变更时由
        _split_shared 精确失效。文件名做确定性白名单展示（无执行语义）。
        """
        if self._shared_ctx_cache is not None:
            return self._shared_ctx_cache
        parts: list[str] = []
        pid = self._active_project_id
        if pid:
            for rel in self.file_manager.list_files(pid, "code/_shared"):
                content = self.file_manager.read_file(pid, rel) or ""
                parts.append(f"### {rel}\n```python\n{content.rstrip()}\n```")
        self._shared_ctx_cache = "\n\n".join(parts)
        return self._shared_ctx_cache

    def _prompt_with_shared(self, base: str) -> str:
        """M4-3：提示词追加公共层上下文段（模板文件保持不变）。"""
        shared = self._shared_context()
        if not shared:
            return base
        return (
            base
            + "\n\n## 已有公共层代码（code/_shared/，直接 import 使用，"
            "不要重复实现；若需修改请用 _shared 标记块给出完整新版本）\n"
            + shared
        )

    # ------------------------------------------------------------------

    def run_module(
        self,
        module: str,
        project_id: str | None = None,
        responsibility: str = "",
        user_feedback: str = "",
        contract: dict | None = None,
        project_modules: set[str] | None = None,
    ) -> ModuleResult:
        """执行单模块完整循环：开发 → 测试 → 门禁 → 执行（→ 反馈）→ 修复。

        门禁（12.2 / 17 章第三阶段）：静态验证 + 接口契约校验，
        均在执行器之前运行——门禁失败不消耗执行预算，直接进修复循环。
        """
        self._active_project_id = project_id
        code = self._write_code(module, responsibility)
        tests = self._write_tests(module, code)
        return self._drive(
            module, project_id, code, tests, fix_attempts=0,
            user_feedback=user_feedback, contract=contract,
            project_modules=project_modules, feedback_pending=True,
        )

    def resume_with_feedback(
        self,
        module: str,
        prev: ModuleResult,
        feedback: str,
        project_id: str | None = None,
        contract: dict | None = None,
        project_modules: set[str] | None = None,
    ) -> ModuleResult:
        """3.8 反馈闭环入口：用户手动运行反馈驱动下一轮。

        - 反馈含成功词 → 模块确认完成（不消耗修复轮）；
        - 反馈为报错 → 修复一轮后重新等待新反馈（不重复消费旧反馈）；
        - 已达修复上限 → 冻结并输出「已知问题与降级方案」交用户决定。
        """
        self._active_project_id = project_id
        if _feedback_success(feedback):
            return self._finish(
                module, project_id, ModuleStatus.SUCCESS, prev.fix_attempts,
                "用户反馈运行成功", prev.code, prev.tests, True,
            )
        if prev.fix_attempts >= self.settings.max_fix_rounds:
            return self._finish(
                module, project_id, ModuleStatus.FROZEN, prev.fix_attempts,
                _frozen_message(prev.fix_attempts, f"用户手动运行反馈: {feedback}"),
                prev.code, prev.tests, True,
            )
        return self._drive(
            module, project_id, prev.code, prev.tests,
            fix_attempts=prev.fix_attempts, user_feedback=feedback,
            contract=contract, project_modules=project_modules,
            feedback_pending=True,
        )

    def regress_module(
        self,
        module: str,
        prev: ModuleResult,
        project_id: str | None = None,
        contract: dict | None = None,
        project_modules: set[str] | None = None,
    ) -> ModuleResult:
        """14.4/12.7：_shared 变更触发的依赖模块整包回归。

        以既有代码与测试重走「门禁 → 执行」：通过则维持 SUCCESS
        （fix_attempts 不变）；失败则进入修复循环（计入 11.4 上限）；
        安全模式 SKIPPED → AWAITING_FEEDBACK（回归不强制执行）。
        """
        self._active_project_id = project_id
        return self._drive(
            module, project_id, prev.code, prev.tests,
            fix_attempts=prev.fix_attempts, user_feedback="",
            contract=contract, project_modules=project_modules,
            feedback_pending=False,
        )

    def _drive(
        self,
        module: str,
        project_id: str | None,
        code: str,
        tests: str,
        fix_attempts: int,
        user_feedback: str,
        contract: dict | None,
        project_modules: set[str] | None,
        feedback_pending: bool,
    ) -> ModuleResult:
        """统一推进循环：门禁 → 执行 →（反馈判定）→ 修复，直至终态。

        SKIPPED（安全模式）语义（3.8 / 8.4）：
        - 反馈未消费且含成功词 → SUCCESS；
        - 反馈未消费且为报错 → 消费该反馈修复一轮；
        - 无反馈 / 反馈已消费 → AWAITING_FEEDBACK（等待新一轮用户
          反馈，不重复消费旧反馈空耗修复轮）。
        """
        failure_report = ""
        gate_passed = False

        while True:
            # 前置门禁：静态验证（语法 / import 核验）
            static = run_static_check(
                code, project_modules=project_modules or set(),
                declared_deps=set(contract.get("dependencies", [])) if contract else None,
            )
            if not static.passed:
                failure_report = "静态门禁失败：" + "; ".join(static.issues)
                gate_passed = False
            else:
                # 前置门禁：接口契约差异校验（14.2 严重度表：
                # missing/extra 阻断；signature_mismatch 仅警告）
                iface_issues = check_implementation(module, code, contract)
                blockers = [i for i in iface_issues if i.severity == "blocking"]
                warnings = [i for i in iface_issues if i.severity == "warning"]
                warning_note = (
                    "接口警告（14.2，不阻断）: "
                    + "; ".join(f"[{i.kind}] {i.detail}" for i in warnings)
                    if warnings else ""
                )
                if blockers:
                    failure_report = "接口门禁失败：" + "; ".join(
                        f"[{i.kind}] {i.detail}" for i in blockers
                    )
                    gate_passed = False
                else:
                    gate_passed = True

            if gate_passed:
                result = self.executor.run(
                    code=code,
                    tests=tests,
                    timeout=self.settings.sandbox_timeout_seconds,
                    module=module,
                )
                # 8.4：安全模式 SKIPPED → 用户反馈判定
                if result.status is ExecutionStatus.SKIPPED:
                    if feedback_pending and _feedback_success(user_feedback):
                        return self._finish(
                            module, project_id, ModuleStatus.SUCCESS, fix_attempts,
                            "用户反馈运行成功", code, tests, gate_passed,
                        )
                    if feedback_pending and user_feedback:
                        # 报错反馈 → 消费该反馈进入修复
                        failure_report = f"用户手动运行反馈: {user_feedback}"
                        feedback_pending = False
                    else:
                        # 3.8：等待用户手动运行后反馈（保留现场）
                        return self._finish(
                            module, project_id, ModuleStatus.AWAITING_FEEDBACK,
                            fix_attempts,
                            result.message or "安全模式：请手动运行并反馈结果",
                            code, tests, gate_passed,
                        )
                elif result.status is ExecutionStatus.SUCCESS:
                    return self._finish(
                        module, project_id, ModuleStatus.SUCCESS, fix_attempts,
                        warning_note, code, tests, gate_passed,
                    )
                elif result.status is ExecutionStatus.BLOCKED:
                    # 3.6.3：高危操作被拦截 → 直接冻结（不做修复循环）
                    return self._finish(
                        module, project_id, ModuleStatus.FROZEN, fix_attempts,
                        f"高危操作被安全拦截: {result.message}", code, tests, gate_passed,
                    )
                else:  # FAILED / TIMEOUT
                    failure_report = (
                        f"exit_code={result.exit_code} stderr={result.stderr} "
                        f"stdout={result.stdout} timeout={self.settings.sandbox_timeout_seconds}s"
                    )

            # 11.4：修复上限
            if fix_attempts >= self.settings.max_fix_rounds:
                return self._finish(
                    module, project_id, ModuleStatus.FROZEN, fix_attempts,
                    _frozen_message(fix_attempts, failure_report),
                    code, tests, gate_passed,
                )

            # 11.0：超预算 → 立即中止该任务（异常上抛，由 Pipeline 落盘）
            if self.budget_guard is not None:
                self.budget_guard.ensure_allowed()

            fix_attempts += 1
            code = self._fix_code(module, code, tests, failure_report)
            self._persist_fix(project_id, module, fix_attempts, failure_report)

    def run_batch(
        self, modules: list[str], project_id: str | None = None
    ) -> dict[str, ModuleResult]:
        """按顺序逐模块执行（3.5：依赖顺序由调用方传入）。"""
        results: dict[str, ModuleResult] = {}
        for module in modules:
            results[module] = self.run_module(module, project_id=project_id)
        return results

    # ------------------------------------------------------------------

    def _write_code(self, module: str, responsibility: str) -> str:
        response = self.llm.chat(
            self.dev_model,
            [
                {"role": "system", "content": WRITE_CODE_SYSTEM},
                {"role": "user", "content": self._prompt_with_shared(
                    WRITE_CODE_USER.format(
                        module=module, responsibility=responsibility or module
                    )
                )},
            ],
        )
        return self._split_shared(_extract_code(response.content))

    def _write_tests(self, module: str, code: str) -> str:
        response = self.llm.chat(
            self.test_model,
            [
                {"role": "system", "content": WRITE_TESTS_SYSTEM},
                {"role": "user", "content": WRITE_TESTS_USER.format(
                    module=module, code=code
                )},
            ],
        )
        return _extract_code(response.content)

    def _fix_code(self, module: str, code: str, tests: str, failure: str) -> str:
        response = self.llm.chat(
            self.dev_model,
            [
                {"role": "system", "content": FIX_CODE_SYSTEM},
                {"role": "user", "content": self._prompt_with_shared(
                    FIX_CODE_USER.format(
                        module=module, code=code, tests=tests,
                        # 问题 8：失败报告/用户反馈为不可信输入，注入前包裹数据边界
                        failure=sanitize_untrusted(failure),
                    )
                )},
            ],
        )
        return self._split_shared(_extract_code(response.content))

    def _split_shared(self, content: str) -> str:
        """12.7/14.4：拆分公共层标记块 → 落盘 code/_shared/，返回模块代码。

        文件名归一化（真实运行教训）：LLM 常写「_shared/utils.py」等带
        路径的标记名——按意图取 basename 归一（_shared/utils.py →
        utils.py，天然剥离穿越段）；归一后为空（如「..」）的块跳过不落盘。
        变更检测由 Pipeline 以 shared_signature 基线对比完成
        （14.5：仅真实内容变更触发回归）。
        """
        shared_files, rest = _extract_shared_blocks(content)
        for filename, code in shared_files.items():
            # 先剥常见目录前缀（保留可读意图），再取 basename 兜底
            normalized = filename
            for prefix in ("_shared/", "code/", "_shared\\", "code\\"):
                if normalized.startswith(prefix):
                    normalized = normalized[len(prefix):]
            normalized = Path(normalized).name
            if not normalized or normalized in (".", ".."):
                continue  # 无有效文件名：跳过该块（门禁会兜住缺失依赖）
            if self._active_project_id:
                self.file_manager.write_shared_file(
                    self._active_project_id, normalized, code
                )
                # M4-3：公共层变更 → 上下文缓存失效（下个模块看到新版）
                self._shared_ctx_cache = None
        return rest

    # ------------------------------------------------------------------

    def _finish(
        self,
        module: str,
        project_id: str | None,
        status: ModuleStatus,
        fix_attempts: int,
        message: str,
        code: str,
        tests: str,
        gate_passed: bool = False,
    ) -> ModuleResult:
        # 12.3：代码与测试落盘（含冻结场景——保留现场供审计）
        if project_id:
            handle = self.file_manager.get_project(project_id)
            if handle is not None:
                # 12.3：模块名同名文件（非 main.py）——多模块可同进程导入互不冲突
                self.file_manager.write_code_file(project_id, module, f"{module}.py", code)
                self.file_manager.write_test_file(
                    project_id, module, f"test_{module}.py", tests
                )
                self._persist_validation_report(
                    project_id, module, status, fix_attempts, gate_passed, message
                )
                # 12.7：终态同步模块文档「当前状态」章节（幂等整节替换）
                status_note = message.split("。")[0] if message else "正常通过"
                self._sync_module_md(
                    project_id,
                    module,
                    status_entry=(
                        f"- {status.value}（{time.strftime('%Y-%m-%d %H:%M')}，"
                        f"修复 {fix_attempts} 次）\n- {status_note}"
                    ),
                )
                if status is ModuleStatus.FROZEN:
                    self._persist_fix(
                        project_id, module, fix_attempts, f"[冻结] {message}"
                    )
        return ModuleResult(
            module=module,
            status=status,
            fix_attempts=fix_attempts,
            message=message,
            code=code,
            tests=tests,
        )

    def _persist_fix(
        self, project_id: str | None, module: str, attempt: int, failure: str
    ) -> None:
        """修复历史落盘（12.4：changelog/<module>/fix_history.md）。"""
        if not project_id:
            return
        entry = f"### 第 {attempt} 次修复\n失败报告: {failure}\n时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        self.file_manager.append_fix_history(project_id, module, entry)
        # 12.7：修复时同步更新模块文档（文档即代码）
        digest = re.sub(r"\s+", " ", failure).strip()
        if len(digest) > _MD_DIGEST_LIMIT:
            digest = digest[:_MD_DIGEST_LIMIT] + "…"
        self._sync_module_md(
            project_id,
            module,
            fix_entry=f"- 第 {attempt} 次修复（{time.strftime('%Y-%m-%d %H:%M')}）: {digest}",
        )

    def _sync_module_md(
        self,
        project_id: str | None,
        module: str,
        fix_entry: str | None = None,
        status_entry: str | None = None,
    ) -> None:
        """12.7 模块文档同步：修复记录追加 + 当前状态整节替换（幂等）。

        modules/<module>.md 缺失时静默跳过（容错，不中断开发循环）。
        """
        if not project_id:
            return
        handle = self.file_manager.get_project(project_id)
        if handle is None:
            return
        path = handle.root / "modules" / f"{module}.md"
        if not path.exists():
            return
        content = path.read_text(encoding="utf-8")

        if fix_entry:
            if _MD_FIX_HEADING in content:
                content = content.rstrip() + f"\n{fix_entry}\n"
            else:
                content = content.rstrip() + f"\n\n{_MD_FIX_HEADING}\n{fix_entry}\n"

        if status_entry:
            pattern = re.compile(
                re.escape(_MD_STATUS_HEADING) + r"[^\n]*(?:\n(?!## ).*)*",
                re.MULTILINE,
            )
            if pattern.search(content):
                content = pattern.sub(
                    f"{_MD_STATUS_HEADING}\n{status_entry}", content
                )
            else:
                content = content.rstrip() + f"\n\n{_MD_STATUS_HEADING}\n{status_entry}\n"

        path.write_text(content, encoding="utf-8")

    def _persist_validation_report(
        self,
        project_id: str,
        module: str,
        status: ModuleStatus,
        fix_attempts: int,
        gate_passed: bool,
        message: str,
    ) -> None:
        """验证报告落盘（17 章第三阶段：changelog/<module>/validation.md）。"""
        handle = self.file_manager.get_project(project_id)
        if handle is None:
            return
        report = (
            f"# 模块 {module} 验证报告\n\n"
            f"- 最终状态: {status.value}\n"
            f"- 门禁（静态 + 接口）: {'通过' if gate_passed else '未通过'}\n"
            f"- 修复次数: {fix_attempts}\n"
            f"- 执行/冻结说明: {message or '正常通过'}\n"
            f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        path = handle.root / "changelog" / module / "validation.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")


def _frozen_message(fix_attempts: int, last_failure: str) -> str:
    """11.4 / 3.8：冻结时的「已知问题与降级方案」输出（交用户决定）。"""
    return (
        f"修复达上限（{fix_attempts} 次）仍失败，模块冻结。"
        f"已知问题与降级方案：失败记录见 changelog/ 修复历史，"
        f"可手动修复后重试，或调高 max_fix_rounds 后续跑。"
        f"最后失败报告: {last_failure}"
    )


def _feedback_success(feedback: str) -> bool:
    """用户手动运行反馈的确定性判定（成功词命中且无未否定失败词 → 通过）。"""
    if not feedback:
        return False
    positive = ("成功", "通过", "正确", "正常", "无报错", "输出符合")
    negative = ("失败", "报错", "错误", "异常", "超时", "不通过")
    has_p = any(w in feedback for w in positive)
    has_n = _has_real_negative(feedback, negative)
    return has_p and not has_n


def _has_real_negative(text: str, negative: tuple[str, ...]) -> bool:
    """负向词命中且未被否定前缀修饰（「无报错」「未失败」不算失败）。"""
    negations = ("无", "未", "没有", "不")
    for word in negative:
        idx = text.find(word)
        while idx != -1:
            prefix = text[max(0, idx - 2) : idx]
            if not any(prefix.endswith(n) for n in negations):
                return True
            idx = text.find(word, idx + 1)
    return False
