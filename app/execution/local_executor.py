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

# 禁止的内建函数
_FORBIDDEN_BUILTINS: frozenset[str] = frozenset({
    "eval", "exec", "compile", "__import__",
})


def scan_dangerous(code: str, tests: str = "", platform: str = "any") -> list[str]:
    """AST 预扫描：返回危险操作描述列表（空列表 = 放行）。

    扫描代码与测试两段文本（被测代码干净但测试里发起网络请求同样拦截）。
    M14-4：platform 指定交付目标平台时，平台不可用模块（如 windows 上的
    fcntl）同样拦截——导入即 ImportError，宁可误报绝不放过。
    """
    from app.utils.platform_policy import unavailable_modules

    platform_mods = unavailable_modules(platform)
    issues: list[str] = []
    for label, text in (("代码", code), ("测试", tests)):
        if not text.strip():
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            # 语法错误交给静态门禁（run_static_check）报告，此处不重复
            continue
        for node in ast.walk(tree):
            issues.extend(_scan_node(node, label, platform_mods))
    return issues


def _scan_node(
    node: ast.AST, label: str, platform_mods: frozenset[str] = frozenset(),
) -> list[str]:
    """单节点扫描：import 黑名单 + 平台不可用模块 + 危险属性调用 + 危险内建。"""
    issues: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in _FORBIDDEN_MODULES:
                issues.append(f"{label}禁止导入 {alias.name}（系统命令/网络/动态加载）")
            elif root in platform_mods:
                issues.append(
                    f"{label}禁止导入 {alias.name}"
                    f"（目标平台不存在该模块，导入即 ImportError）"
                )
    elif isinstance(node, ast.ImportFrom):
        root = (node.module or "").split(".")[0]
        if root in _FORBIDDEN_MODULES:
            issues.append(f"{label}禁止从 {node.module} 导入（系统命令/网络/动态加载）")
        elif root in platform_mods:
            issues.append(
                f"{label}禁止从 {node.module} 导入"
                f"（目标平台不存在该模块，导入即 ImportError）"
            )
    elif isinstance(node, ast.Call):
        func = node.func
        # os.xxx / shutil.xxx 危险属性
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id == "os" and func.attr in _FORBIDDEN_OS_ATTRS:
                issues.append(f"{label}禁止调用 os.{func.attr}()")
            elif func.value.id == "shutil" and func.attr in _FORBIDDEN_SHUTIL_ATTRS:
                issues.append(f"{label}禁止调用 shutil.{func.attr}()")
        # eval/exec/__import__ 内建
        elif isinstance(func, ast.Name) and func.id in _FORBIDDEN_BUILTINS:
            issues.append(f"{label}禁止调用 {func.id}()（动态执行）")
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
    """自动验证模式：危险预扫描 + 本地子进程真实执行。"""

    def __init__(
        self,
        project_code_dir: Path | str | None = None,
        platform: str = "any",
    ):
        self.project_code_dir = Path(project_code_dir) if project_code_dir else None
        # M14-4：交付目标平台（平台不可用模块拦截；any = 不检查）
        self.platform = platform

    def run(
        self,
        code: str,
        tests: str,
        timeout: int,
        expected_output: str = "",
        module: str = "",
    ) -> ExecutionResult:
        # 3.6.3：执行前危险预扫描（宁可误报，绝不放过）
        issues = scan_dangerous(code, tests, platform=self.platform)
        if issues:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                exit_code=None,
                message="危险操作已拦截（未执行）: " + "; ".join(issues),
            )

        module_name = module or "_module_"
        started = time.time()
        with tempfile.TemporaryDirectory(prefix="token_burner_exec_") as tmp:
            tmp_dir = Path(tmp)
            (tmp_dir / f"{module_name}.py").write_text(code, encoding="utf-8")

            env = dict(os.environ)
            # 依赖解析顺序：当前模块（临时目录）优先，其次项目 code/ 目录
            paths = [str(tmp_dir)]
            if self.project_code_dir and self.project_code_dir.is_dir():
                paths.append(str(self.project_code_dir))
            env["PYTHONPATH"] = os.pathsep.join(
                paths + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
            )

            if tests.strip():
                (tmp_dir / f"test_{module_name}.py").write_text(
                    tests, encoding="utf-8"
                )
                try:
                    proc = subprocess.run(
                        [sys.executable, "-m", "pytest", f"test_{module_name}.py", "-q", "--no-header"],
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
                duration = int((time.time() - started) * 1000)
                test_results = [_parse_pytest_summary(proc.stdout)]
                if proc.returncode == 0:
                    return ExecutionResult(
                        status=ExecutionStatus.SUCCESS,
                        exit_code=0, stdout=proc.stdout, stderr=proc.stderr,
                        test_results=test_results, duration_ms=duration,
                        message=f"pytest 通过（{test_results[0]['passed']} 项）",
                    )
                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
                    test_results=test_results, duration_ms=duration,
                    message="pytest 未通过",
                )

            # 无测试：直接运行模块（__main__）
            try:
                proc = subprocess.run(
                    [sys.executable, f"{module_name}.py"],
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
