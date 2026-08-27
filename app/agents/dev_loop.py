"""模块化开发循环（规格文档 3.5 节、3.7 节、8.4 节、11.4 节、12.4 节）。

逐模块「开发 → 测试 → 执行 → 修复」循环：
- Dev Agent（开发副 LLM）生成模块代码与修复补丁；
- Test Agent（测试副 LLM）生成可独立运行的测试文件（3.7）；
- Executor 执行（安全模式 SKIPPED 时等待用户反馈，等价判定，8.4）；
- 修复上限（11.4）：单模块默认 3 次修复尝试，达上限仍失败 →
  冻结该模块（保留代码与失败记录），不阻塞其他模块；
- fix_history 落盘（12.4）：changelog/<module>/fix_history.md。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

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

# 判定「执行失败」的状态集合（8.4：进入修复循环）
_RETRYABLE = {ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT}


class ModuleStatus(Enum):
    SUCCESS = "SUCCESS"
    FROZEN = "FROZEN"   # 11.4：修复上限耗尽


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
    ):
        self.llm = llm
        self.dev_model = dev_model
        self.test_model = test_model
        self.executor = executor
        self.settings = settings
        self.file_manager = file_manager

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
        code = self._write_code(module, responsibility)
        tests = self._write_tests(module, code)
        fix_attempts = 0
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
                # 前置门禁：接口契约三类差异校验
                iface_issues = check_implementation(module, code, contract)
                if iface_issues:
                    failure_report = "接口门禁失败：" + "; ".join(
                        f"[{i.kind}] {i.detail}" for i in iface_issues
                    )
                    gate_passed = False
                else:
                    gate_passed = True

            if gate_passed:
                result = self.executor.run(
                    code=code,
                    tests=tests,
                    timeout=self.settings.sandbox_timeout_seconds,
                )
                # 8.4：安全模式 SKIPPED → 用户反馈判定（成功词 → SUCCESS，否则失败）
                if result.status is ExecutionStatus.SKIPPED:
                    if _feedback_success(user_feedback):
                        return self._finish(
                            module, project_id, ModuleStatus.SUCCESS, fix_attempts,
                            "用户反馈运行成功", code, tests, gate_passed,
                        )
                    failure_report = f"用户手动运行反馈: {user_feedback}"
                elif result.status is ExecutionStatus.SUCCESS:
                    return self._finish(
                        module, project_id, ModuleStatus.SUCCESS, fix_attempts,
                        "", code, tests, gate_passed,
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
                    f"修复达上限（{fix_attempts} 次）仍失败，模块冻结。"
                    f"最后失败报告: {failure_report}",
                    code, tests, gate_passed,
                )

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
                {"role": "user", "content": WRITE_CODE_USER.format(
                    module=module, responsibility=responsibility or module
                )},
            ],
        )
        return response.content

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
        return response.content

    def _fix_code(self, module: str, code: str, tests: str, failure: str) -> str:
        response = self.llm.chat(
            self.dev_model,
            [
                {"role": "system", "content": FIX_CODE_SYSTEM},
                {"role": "user", "content": FIX_CODE_USER.format(
                    module=module, code=code, tests=tests, failure=failure
                )},
            ],
        )
        return response.content

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
