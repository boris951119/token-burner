"""本地自动验证执行器（规格 3.6.3 沙箱执行的基础版，Alpha v0.4 提前落地）。

产品审计问题 2：auto 模式此前与 safe 行为完全相同（永远 SKIPPED），
却按 ×2.5 扣预算——有名无实。本执行器让自动验证名实相符：

- 危险操作预扫描（AST，执行前确定性拦截）→ BLOCKED；
- 真实子进程执行：有测试 → pytest；无测试 → 直接运行模块；
- 超时熔断（subprocess timeout）→ TIMEOUT；
- 跨模块 / _shared 依赖经项目 code/ 目录（PYTHONPATH）解析；
- 输出（stdout/stderr/测试计数）进修复循环驱动自动修复（3.7/3.8）。

安全边界声明（第 19 章）：基础版为进程级隔离 + 危险 API 黑名单 +
超时熔断，不是完整容器沙箱；高危拦截采用「宁可误报」策略。
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.execution.executor import ExecutionResult, ExecutionStatus, Executor

# ---------------------------------------------------------------------------
# 危险操作预扫描（3.6.3：执行前确定性拦截）
# ---------------------------------------------------------------------------

# 禁止整包导入的模块（系统命令/子进程/网络/动态加载/序列化逃逸）
_FORBIDDEN_MODULES: frozenset[str] = frozenset({
    "subprocess", "socket", "ctypes", "pickle", "shelve",
    "urllib", "requests", "http", "httpx", "http.client",
    "telnetlib", "ftplib", "smtplib", "poplib", "imaplib",
    "webbrowser", "asyncio.subprocess",
})

# 禁止的 os / shutil 属性调用
_FORBIDDEN_OS_ATTRS: frozenset[str] = frozenset({
    "system", "popen", "popen2", "popen3", "popen4",
    "execv", "execve", "execvp", "execvpe", "execl", "execle",
    "execlp", "execlpe", "spawnv", "spawnve", "spawnvp", "spawnl",
    "spawnle", "spawnlp", "fork", "forkpty", "kill", "killpg",
    "remove", "unlink", "rmdir", "removedirs", "renames",
})

_FORBIDDEN_SHUTIL_ATTRS: frozenset[str] = frozenset({"rmtree", "move"})

# fs 删除族：模块代码侧维持拦截（规格安全边界），测试侧放行——
# 测试用 unlink/rmtree 清理临时产物是标准写法，执行环境为一次性 tmp
# 目录；一刀切曾致文件类功能测试全数 BLOCKED 直接冻结（bench_v1 取证）
_FS_DELETION_OS_ATTRS: frozenset[str] = frozenset({
    "remove", "unlink", "rmdir", "removedirs", "renames",
})

# 禁止的内建函数
_FORBIDDEN_BUILTINS: frozenset[str] = frozenset({
    "eval", "exec", "compile", "__import__",
})


def scan_dangerous(code: str, tests: str = "", platform: str = "any") -> list[str]:
    """AST 预扫描：返回危险操作描述列表（空列表 = 放行）。

    扫描代码与测试两段文本（被测代码干净但测试里发起网络请求同样拦截）。
    M14-4：platform 指定交付目标平台时，平台不可用模块（如 windows 上的
    fcntl）同样拦截——导入即 ImportError，宁可误报绝不放过。
    3.6.3 分级修订：硬级（不可替代高危）与软级（fs 删除族·代码侧）合并
    返回（兼容既有调用方）；分级语义用 scan_dangerous_graded。
    """
    hard, soft = scan_dangerous_graded(code, tests, platform)
    return hard + soft


def scan_dangerous_graded(
    code: str, tests: str = "", platform: str = "any",
) -> tuple[list[str], list[str]]:
    """分级危险扫描：返回 (hard, soft)。

    - hard（不可替代高危：动态执行/系统命令/网络/子进程/序列化逃逸）：
      维持 3.6.3 执行器层 BLOCKED 直接冻结；
    - soft（fs 删除族 · 模块代码侧：os.remove/unlink/rmdir/removedirs/
      renames、shutil.rmtree/move）：有正当业务语义且 auto 模式本就运行
      在沙箱内——bench_v1 round-5 取证（glm-4.7 两模块死于 os.remove
      直接冻结）后降级为「进修复循环换安全设计」，由 dev_loop 门禁层
      在执行器之前拦截处置，执行器只拦 hard。
    """
    from app.utils.platform_policy import unavailable_modules

    platform_mods = unavailable_modules(platform)
    hard: list[str] = []
    soft: list[str] = []
    for label, text in (("代码", code), ("测试", tests)):
        if not text.strip():
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            # 语法错误交给静态门禁（run_static_check）报告，此处不重复
            continue
        for node in ast.walk(tree):
            h, s = _scan_node(node, label, platform_mods)
            hard.extend(h)
            soft.extend(s)
    return hard, soft


def _scan_node(
    node: ast.AST, label: str, platform_mods: frozenset[str] = frozenset(),
) -> tuple[list[str], list[str]]:
    """单节点扫描 → (hard, soft)：import 黑名单 + 平台模块 + 危险调用。"""
    hard: list[str] = []
    soft: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in _FORBIDDEN_MODULES:
                hard.append(f"{label}禁止导入 {alias.name}（系统命令/网络/动态加载）")
            elif root in platform_mods:
                hard.append(
                    f"{label}禁止导入 {alias.name}"
                    f"（目标平台不存在该模块，导入即 ImportError）"
                )
    elif isinstance(node, ast.ImportFrom):
        root = (node.module or "").split(".")[0]
        if root in _FORBIDDEN_MODULES:
            hard.append(f"{label}禁止从 {node.module} 导入（系统命令/网络/动态加载）")
        elif root in platform_mods:
            hard.append(
                f"{label}禁止从 {node.module} 导入"
                f"（目标平台不存在该模块，导入即 ImportError）"
            )
    elif isinstance(node, ast.Call):
        func = node.func
        # os.xxx / shutil.xxx 危险属性
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id == "os" and func.attr in _FORBIDDEN_OS_ATTRS:
                if label == "测试" and func.attr in _FS_DELETION_OS_ATTRS:
                    pass  # 测试清理 tmp 产物（见 _FS_DELETION_OS_ATTRS 注）
                elif func.attr in _FS_DELETION_OS_ATTRS:
                    soft.append(f"{label}调用 os.{func.attr}()（文件删除族，请改用安全设计）")
                else:
                    hard.append(f"{label}禁止调用 os.{func.attr}()")
            elif func.value.id == "shutil" and func.attr in _FORBIDDEN_SHUTIL_ATTRS:
                if label == "测试":
                    pass  # rmtree/move 同上：测试清理 tmp 产物放行
                else:
                    soft.append(f"{label}调用 shutil.{func.attr}()（文件删除族，请改用安全设计）")
        # eval/exec/__import__ 内建
        elif isinstance(func, ast.Name) and func.id in _FORBIDDEN_BUILTINS:
            hard.append(f"{label}禁止调用 {func.id}()（动态执行）")
    return hard, soft


def danger_prompt_constraint() -> str:
    """危险操作约束提示词段（注入 write_code/fix_code，方案 A）。

    与扫描黑名单同文件同源（单一数据源，提示与拦截不漂移——对齐
    platform_policy 的设计锚点）。
    """
    return (
        "\n\n## 安全约束（违反将被安全层拦截）\n"
        "禁止使用：eval / exec / compile / __import__（动态执行）；"
        "os.system / os.popen* / os.exec* / os.spawn* / os.kill*（系统命令）；"
        "subprocess / socket / ctypes / pickle / urllib / requests 等"
        "（系统命令/网络/动态加载/序列化逃逸）模块的任何导入。\n"
        "文件删除（os.remove / os.unlink / os.rmdir / shutil.rmtree / shutil.move）"
        "不得直接调用：请改为 ① 由调用方负责清理 ② 返回待清理路径列表 "
        "③ 使用 tempfile.TemporaryDirectory 上下文（作用域结束自动清理）。"
    )


# ---------------------------------------------------------------------------
# M16-1：JS 静态危险扫描（require/import 黑名单 + eval 族 + node --check）
# ---------------------------------------------------------------------------

# 禁止整包引入的 Node 模块（子进程/网络/动态执行/集群——对齐 Python
# _FORBIDDEN_MODULES 的类别口径）
_JS_FORBIDDEN_MODULES: frozenset[str] = frozenset({
    "child_process", "cluster", "net", "dgram", "tls",
    "http", "https", "http2", "dns", "vm", "worker_threads",
})

# fs 允许引入（文件读写是合法能力），但删除/改名类方法调用拦截
#（对齐 Python os.remove/unlink/rmdir/renames 的黑名单粒度）
_JS_FORBIDDEN_FS_METHODS: frozenset[str] = frozenset({
    "rm", "rmSync", "unlink", "unlinkSync",
    "rmdir", "rmdirSync", "rename", "renameSync",
})

# require('mod') / import x from 'mod' / import 'mod' / import('mod')
# / export {x} from 'mod'（再导出同样触发模块加载）
_JS_MODULE_RE = re.compile(
    r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)
      |import\s+(?:[\w*{},\s]+?\s+from\s+)?['"]([^'"]+)['"]
      |import\s*\(\s*['"]([^'"]+)['"]\s*\)
      |export\s+[\w*{},\s]+?\s+from\s+['"]([^'"]+)['"]""",
    re.VERBOSE,
)

# eval 族（动态执行）：eval( / new Function( / 裸 Function( 构造器调用
_JS_EVAL_RE = re.compile(
    r"\beval\s*\(|\bnew\s+Function\s*\(|(?<![\w.])Function\s*\("
)

# 危险 fs 方法调用（任意接收者——宁可误报）
_JS_FS_CALL_RE = re.compile(
    r"\.\s*(" + "|".join(sorted(_JS_FORBIDDEN_FS_METHODS)) + r")\s*\("
)

# 动态 require（非字面量参数——路径拼接/变量注入的常见载体）
_JS_DYNAMIC_REQUIRE_RE = re.compile(r"\brequire\s*\(\s*(?!['\"\)])")


def _strip_js_comments(src: str) -> str:
    """剥离注释（降低注释中黑名单词的误报；引号内的 // 不受影响）。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    out: list[str] = []
    for line in src.splitlines():
        quote = None
        cut = len(line)
        i = 0
        while i < len(line):
            ch = line[i]
            if quote:
                if ch == "\\":
                    i += 2
                    continue
                if ch == quote:
                    quote = None
            elif ch in "'\"":
                quote = ch
            elif line.startswith("//", i):
                cut = i
                break
            i += 1
        out.append(line[:cut])
    return "\n".join(out)


def _node_syntax_issues(code: str, tests: str) -> list[str]:
    """node --check 语法核验（宿主无 node → 跳过，执行阶段兜底）。"""
    import shutil

    node = shutil.which("node")
    if node is None:
        return []
    issues: list[str] = []
    for label, text in (("代码", code), ("测试", tests)):
        if not text.strip():
            continue
        with tempfile.TemporaryDirectory(prefix="token_burner_jscheck_") as tmp:
            f = Path(tmp) / "check.js"
            f.write_text(text, encoding="utf-8")
            try:
                proc = subprocess.run(
                    [node, "--check", str(f)],
                    capture_output=True, text=True, timeout=10,
                    encoding="utf-8", errors="replace",
                )
            except (subprocess.TimeoutExpired, OSError):
                continue  # check 自身故障不阻塞（执行阶段非零退出兜底）
        if proc.returncode != 0:
            lines = (proc.stderr or proc.stdout or "").strip().splitlines()
            detail = lines[0][:120] if lines else "未知语法错误"
            issues.append(f"{label}JS 语法错误（node --check）: {detail}")
    return issues


def scan_dangerous_js(
    code: str, tests: str = "", node_check: bool = True
) -> list[str]:
    """M16-1：JS 静态危险预扫描（返回危险操作描述列表，空 = 放行）。

    三道防线（与 Python 版 scan_dangerous 同位互补）：
    1. require/import/export-from 黑名单（child_process/net/vm 等
       ——子进程/网络/动态执行，含 node: 前缀变体）；
    2. eval 族 + 危险 fs 方法（rm/unlink/rmdir/rename，对齐 Python
       os.* 黑名单粒度）+ 动态 require（非字面量模块名）；
    3. node --check 语法核验（仅 node_check=True 时）——供独立调用方
       （如上层静态门禁）使用；执行器接线一律 node_check=False：
       语法错误属可修复类，语义归执行 FAILED（修复循环）而非
       BLOCKED（冻结），对齐 Python 版「语法错误交给静态门禁」原则。

    无 JS 解析器依赖（宁缺毋滥），正则 + 注释剥离实现；
    姿态与 Python 版一致：宁可误报绝不放过。
    """
    issues: list[str] = []
    for label, text in (("代码", code), ("测试", tests)):
        if not text.strip():
            continue
        src = _strip_js_comments(text)
        for m in _JS_MODULE_RE.finditer(src):
            mod = next(g for g in m.groups() if g)
            root = mod.split("node:")[-1].split("/")[0]
            if root in _JS_FORBIDDEN_MODULES:
                issues.append(f"{label}禁止引入 {mod}（系统命令/网络/动态执行）")
        if _JS_EVAL_RE.search(src):
            issues.append(f"{label}禁止 eval/Function 动态执行")
        for m in _JS_FS_CALL_RE.finditer(src):
            issues.append(
                f"{label}禁止调用 fs.{m.group(1)}()（删除/改名类文件操作）")
        if _JS_DYNAMIC_REQUIRE_RE.search(src):
            issues.append(f"{label}禁止动态 require（非字面量模块名）")
    if node_check and (code.strip() or tests.strip()):
        issues.extend(_node_syntax_issues(code, tests))
    return issues


# ---------------------------------------------------------------------------
# pytest 输出解析（test_results 填充）
# ---------------------------------------------------------------------------

_FAILED_RE = re.compile(r"(\d+) failed")
_PASSED_RE = re.compile(r"(\d+) passed")


def _parse_pytest_summary(stdout: str) -> dict:
    """从 pytest -q 输出提取 passed/failed 计数（解析失败返回零计数）。"""
    failed = _FAILED_RE.search(stdout)
    passed = _PASSED_RE.search(stdout)
    return {
        "failed": int(failed.group(1)) if failed else 0,
        "passed": int(passed.group(1)) if passed else 0,
    }


# ---------------------------------------------------------------------------
# 执行器本体
# ---------------------------------------------------------------------------


class LocalExecutor(Executor):
    """自动验证模式：危险预扫描 + 本地子进程真实执行。

    M16-1：language="node" 时切换 JS 链路——scan_dangerous_js 预扫描
    + node --test / node 执行（宿主需有 node；缺失时明确 FAILED）。
    """

    def __init__(
        self,
        project_code_dir: Path | str | None = None,
        platform: str = "any",
        language: str = "python",
    ):
        self.project_code_dir = Path(project_code_dir) if project_code_dir else None
        # M14-4：交付目标平台（平台不可用模块拦截；any = 不检查）
        self.platform = platform
        if language not in ("python", "node"):
            raise ValueError(
                f"language 仅支持 python / node，当前: {language!r}"
            )
        self.language = language

    def run(
        self,
        code: str,
        tests: str,
        timeout: int,
        expected_output: str = "",
        module: str = "",
    ) -> ExecutionResult:
        # 3.6.3：执行前危险预扫描（宁可误报，绝不放过）。
        # M16-1：node 链路用 JS 黑名单；node_check=False——语法错误属
        # 可修复类，语义归执行 FAILED（修复循环）而非 BLOCKED（冻结），
        # 对齐 Python 版「语法错误交给静态门禁」原则。
        if self.language == "node":
            hard_issues = scan_dangerous_js(code, tests, node_check=False)
        else:
            # 3.6.3 分级：执行器只拦 hard（不可替代高危）；soft（fs 删除族
            # ·代码侧）由 dev_loop 门禁层在执行器之前拦截并进修复循环
            hard_issues, _soft = scan_dangerous_graded(
                code, tests, platform=self.platform,
            )
        if hard_issues:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                exit_code=None,
                message="危险操作已拦截（未执行）: " + "; ".join(hard_issues),
            )

        module_name = module or "_module_"
        ext = "js" if self.language == "node" else "py"
        started = time.time()
        with tempfile.TemporaryDirectory(prefix="token_burner_exec_") as tmp:
            tmp_dir = Path(tmp)
            (tmp_dir / f"{module_name}.{ext}").write_text(code, encoding="utf-8")

            env = dict(os.environ)
            # 依赖解析顺序：当前模块（临时目录）优先，其次项目 code/ 目录
            paths = [str(tmp_dir)]
            if self.project_code_dir and self.project_code_dir.is_dir():
                paths.append(str(self.project_code_dir))
            env["PYTHONPATH"] = os.pathsep.join(
                paths + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
            )

            if tests.strip():
                (tmp_dir / f"test_{module_name}.{ext}").write_text(
                    tests, encoding="utf-8"
                )
                # M16-1：node 链路 → node --test（内置 runner，无 npm 依赖；
                # 显式 tap reporter 保证 # pass/# fail 汇总行可解析——
                # node 缺省 spec 格式无此行，Docker 版同修）
                if self.language == "node":
                    argv = ["node", "--test", "--test-reporter=tap",
                            f"test_{module_name}.{ext}"]
                else:
                    argv = [sys.executable, "-m", "pytest",
                            f"test_{module_name}.{ext}", "-q", "--no-header"]
                try:
                    proc = subprocess.run(
                        argv,
                        cwd=tmp_dir, env=env, timeout=timeout,
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                    )
                except subprocess.TimeoutExpired:
                    return ExecutionResult(
                        status=ExecutionStatus.TIMEOUT,
                        exit_code=None,
                        duration_ms=int((time.time() - started) * 1000),
                        message=f"测试执行超时（>{timeout}s 熔断，3.6.3）",
                    )
                except FileNotFoundError:
                    return ExecutionResult(
                        status=ExecutionStatus.FAILED,
                        exit_code=None,
                        duration_ms=int((time.time() - started) * 1000),
                        message="Node.js 运行时不可用（PATH 中无 node，"
                                "无法执行 JS 代码）",
                    )
                duration = int((time.time() - started) * 1000)
                if self.language == "node":
                    from app.execution.docker_executor import _parse_node_tap

                    test_results = [_parse_node_tap(proc.stdout)]
                    ok_msg = f"node --test 通过（{test_results[0]['passed']} 项）"
                    fail_msg = "node --test 未通过"
                else:
                    test_results = [_parse_pytest_summary(proc.stdout)]
                    ok_msg = f"pytest 通过（{test_results[0]['passed']} 项）"
                    fail_msg = "pytest 未通过"
                if proc.returncode == 0:
                    return ExecutionResult(
                        status=ExecutionStatus.SUCCESS,
                        exit_code=0, stdout=proc.stdout, stderr=proc.stderr,
                        test_results=test_results, duration_ms=duration,
                        message=ok_msg,
                    )
                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
                    test_results=test_results, duration_ms=duration,
                    message=fail_msg,
                )

            # 无测试：直接运行模块（__main__ / 入口脚本）
            if self.language == "node":
                argv = ["node", f"{module_name}.{ext}"]
            else:
                argv = [sys.executable, f"{module_name}.{ext}"]
            try:
                proc = subprocess.run(
                    argv,
                    cwd=tmp_dir, env=env, timeout=timeout,
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                )
            except subprocess.TimeoutExpired:
                return ExecutionResult(
                    status=ExecutionStatus.TIMEOUT,
                    exit_code=None,
                    duration_ms=int((time.time() - started) * 1000),
                    message=f"执行超时（>{timeout}s 熔断，3.6.3）",
                )
            except FileNotFoundError:
                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    exit_code=None,
                    duration_ms=int((time.time() - started) * 1000),
                    message="Node.js 运行时不可用（PATH 中无 node，"
                            "无法执行 JS 代码）",
                )
            duration = int((time.time() - started) * 1000)
            if proc.returncode != 0:
                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
                    duration_ms=duration, message="运行失败（非零退出码）",
                )
            if expected_output and expected_output not in proc.stdout:
                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
                    duration_ms=duration,
                    message=f"预期输出不匹配：期望包含 {expected_output!r}",
                )
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                exit_code=0, stdout=proc.stdout, stderr=proc.stderr,
                duration_ms=duration, message="运行成功",
            )
