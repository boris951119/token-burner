"""LocalExecutor 自动验证模式测试（产品审计问题 2 修复，TDD 先行）。

问题：auto 模式与 safe 行为完全相同（仅 SafeExecutor，永远 SKIPPED），
却按 ×2.5 扣预算——有名无实。

修复约定（3.6.3 沙箱执行的基础版，Alpha v0.4 提前落地）：
- 危险操作预扫描（AST，执行前）：系统命令/子进程/网络/动态执行/
  危险文件操作 → BLOCKED（dev_loop 语义：直接冻结不修复）；
- 真实子进程执行：测试存在 → pytest（exit code 判定）；无测试 →
  直接运行模块（__main__）；expected_output 给定且不匹配 → FAILED；
- 超时熔断（subprocess timeout）→ TIMEOUT；
- 跨模块/_shared 依赖经项目 code/ 目录（PYTHONPATH）解析；
- 输出（stdout/stderr/test_results）进修复循环驱动自动修复。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.execution.executor import ExecutionStatus
from app.execution.local_executor import LocalExecutor, scan_dangerous


def _run_kwargs(code, tests="", timeout=30, expected_output="", module="user"):
    return dict(code=code, tests=tests, timeout=timeout,
                expected_output=expected_output, module=module)


# ---------------------------------------------------------------------------
# 危险操作预扫描（AST，确定性）
# ---------------------------------------------------------------------------


class TestDangerScan:
    @pytest.mark.parametrize("code", [
        "import os\nos.system('dir')\n",
        "import subprocess\nsubprocess.run(['ls'])\n",
        "import socket\ns = socket.socket()\n",
        "import requests\nrequests.get('http://x')\n",
        "from urllib.request import urlopen\n",
        "import ctypes\nctypes.CDLL('x')\n",
        "eval('1+1')\n",
        "exec('x = 1')\n",
        "import os\nos.execvp('ls', ['ls'])\n",
        "import shutil\nshutil.rmtree('/tmp/x')\n",
    ])
    def test_dangerous_patterns_blocked(self, code):
        issues = scan_dangerous(code)
        assert issues, f"应检出危险操作: {code!r}"

    def test_clean_code_passes(self):
        code = "def add(a, b):\n    return a + b\n\n\nprint(add(1, 2))\n"
        assert scan_dangerous(code) == []
        assert scan_dangerous(code, tests="def test_add():\n    assert True\n") == []

    def test_scan_covers_tests_too(self):
        # 测试代码同样预扫描（被测代码干净但测试里起网络请求也不行）
        issues = scan_dangerous("x = 1\n", tests="import socket\nsocket.socket()\n")
        assert issues

    def test_safe_builtins_not_flagged(self):
        # print/open 读文件/字符串操作等正常 API 不误报
        code = (
            "with open('data.txt') as f:\n"
            "    print(f.read().upper())\n"
        )
        assert scan_dangerous(code) == []


# ---------------------------------------------------------------------------
# 真实执行（子进程）
# ---------------------------------------------------------------------------


class TestRealExecution:
    def test_module_run_success(self, tmp_path):
        # 无测试：直接运行模块，exit 0 → SUCCESS，stdout 被捕获
        ex = LocalExecutor(project_code_dir=tmp_path)
        result = ex.run(**_run_kwargs(
            "def core():\n    return 3\n\n\nprint('ok', core())\n"
        ))
        assert result.status is ExecutionStatus.SUCCESS
        assert result.exit_code == 0
        assert "ok 3" in result.stdout

    def test_module_run_failure_captured(self, tmp_path):
        # 运行时报错 → FAILED，stderr 含 traceback（进修复循环）
        ex = LocalExecutor(project_code_dir=tmp_path)
        result = ex.run(**_run_kwargs("raise ValueError('boom')\n"))
        assert result.status is ExecutionStatus.FAILED
        assert result.exit_code != 0
        assert "boom" in result.stderr

    def test_timeout_kills_process(self, tmp_path):
        # 超时熔断（3.6.3）：TIMEOUT 而非挂起
        ex = LocalExecutor(project_code_dir=tmp_path)
        result = ex.run(**_run_kwargs("import time\ntime.sleep(10)\n", timeout=1))
        assert result.status is ExecutionStatus.TIMEOUT

    def test_expected_output_mismatch_fails(self, tmp_path):
        # expected_output 给定且不匹配 → FAILED（可观测信息）
        ex = LocalExecutor(project_code_dir=tmp_path)
        result = ex.run(**_run_kwargs(
            "print('hello')\n", expected_output="world"
        ))
        assert result.status is ExecutionStatus.FAILED
        assert "预期" in result.message or "world" in result.message

    def test_expected_output_match_passes(self, tmp_path):
        ex = LocalExecutor(project_code_dir=tmp_path)
        result = ex.run(**_run_kwargs(
            "print('hello world')\n", expected_output="hello"
        ))
        assert result.status is ExecutionStatus.SUCCESS


# ---------------------------------------------------------------------------
# pytest 测试执行
# ---------------------------------------------------------------------------


class TestPytestExecution:
    def test_tests_pass(self, tmp_path):
        ex = LocalExecutor(project_code_dir=tmp_path)
        result = ex.run(**_run_kwargs(
            "def core():\n    return 42\n",
            tests="from user import core\n\n\ndef test_core():\n    assert core() == 42\n",
        ))
        assert result.status is ExecutionStatus.SUCCESS
        assert result.test_results and result.test_results[0]["passed"] >= 1

    def test_tests_fail_with_details(self, tmp_path):
        # 测试失败 → FAILED，失败详情进输出（stdout/stderr）驱动修复
        ex = LocalExecutor(project_code_dir=tmp_path)
        result = ex.run(**_run_kwargs(
            "def core():\n    return 41\n",
            tests="from user import core\n\n\ndef test_core():\n    assert core() == 42\n",
        ))
        assert result.status is ExecutionStatus.FAILED
        output = result.stdout + result.stderr
        assert "failed" in output.lower()
        assert result.test_results[0]["failed"] >= 1

    def test_cross_module_import_via_project_code_dir(self, tmp_path):
        # 跨模块依赖：项目 code/ 目录已含 user.py，当前模块 auth 引用之
        (tmp_path / "user.py").write_text("def core_fn():\n    return 7\n", encoding="utf-8")
        ex = LocalExecutor(project_code_dir=tmp_path)
        result = ex.run(**_run_kwargs(
            "from user import core_fn\n\n\nprint('auth', core_fn())\n",
            module="auth",
        ))
        assert result.status is ExecutionStatus.SUCCESS
        assert "auth 7" in result.stdout

    def test_shared_import_via_project_code_dir(self, tmp_path):
        # _shared 公共层依赖同样经项目 code/ 目录解析
        shared = tmp_path / "_shared"
        shared.mkdir()
        (shared / "__init__.py").write_text("", encoding="utf-8")
        (shared / "utils.py").write_text("def helper():\n    return 5\n", encoding="utf-8")
        ex = LocalExecutor(project_code_dir=tmp_path)
        result = ex.run(**_run_kwargs(
            "from _shared.utils import helper\n\n\nprint('v', helper())\n"
        ))
        assert result.status is ExecutionStatus.SUCCESS
        assert "v 5" in result.stdout


# ---------------------------------------------------------------------------
# 危险代码被拦截（BLOCKED，不进子进程）
# ---------------------------------------------------------------------------


class TestBlocked:
    def test_dangerous_code_blocked_before_execution(self, tmp_path):
        # 预扫描命中 → BLOCKED，绝不启动子进程
        ex = LocalExecutor(project_code_dir=tmp_path)
        result = ex.run(**_run_kwargs(
            "import os\nprint(os.system('echo hi'))\n"
        ))
        assert result.status is ExecutionStatus.BLOCKED
        assert result.exit_code is None
        assert result.stdout == ""
        assert "危险" in result.message or "拦截" in result.message


# ---------------------------------------------------------------------------
# dev_loop 集成：auto 模式驱动自动修复
# ---------------------------------------------------------------------------


class TestDevLoopIntegration:
    def _engine(self, executor, llm, fm):
        from app.agents.dev_loop import DevLoopEngine
        from app.config import Settings

        return DevLoopEngine(
            llm=llm, dev_model="deepseek-chat", test_model="claude",
            executor=executor, settings=Settings(), file_manager=fm,
        )

    def test_auto_mode_failure_triggers_fix_then_success(self, tmp_path):
        # 首轮代码运行失败 → 修复循环自动触发 → 第二版成功（全程无人工反馈）
        from app.tools.file_manager import FileManager
        from tests.test_pipeline import ScriptedLLM as PipelineScriptedLLM

        fm = FileManager(projects_root=tmp_path / "projects")
        project_id = fm.create_project("auto 验证").project_id
        handle = fm.get_project(project_id)
        code_root = handle.root / "code"
        code_root.mkdir(exist_ok=True)

        llm = PipelineScriptedLLM([
            "raise RuntimeError('v1 broken')\n",                     # 首版代码（导入即炸）
            "from user import run\n\n\ndef test_run():\n    assert run() == 1\n",  # 测试
            "def run():\n    return 1\n",                             # 修复版
        ])
        engine = self._engine(LocalExecutor(project_code_dir=code_root), llm, fm)
        result = engine.run_module("user", project_id=project_id)
        assert result.status.value == "SUCCESS"
        assert result.fix_attempts == 1  # 一次真实失败 → 一次自动修复

    def test_auto_mode_dangerous_code_frozen(self, tmp_path):
        # 危险代码 → BLOCKED → 直接冻结（不消耗修复循环）
        from app.config import Settings
        from app.tools.file_manager import FileManager
        from tests.test_pipeline import ScriptedLLM

        fm = FileManager(projects_root=tmp_path / "projects")
        project_id = fm.create_project("危险冻结").project_id
        handle = fm.get_project(project_id)
        code_root = handle.root / "code"
        code_root.mkdir(exist_ok=True)

        llm = ScriptedLLM([
            "import os\nos.system('rm -rf /')\n",
            "def test_user():\n    pass\n",
        ])
        engine = self._engine(LocalExecutor(project_code_dir=code_root), llm, fm)
        result = engine.run_module("user", project_id=project_id)
        assert result.status.value == "FROZEN"
        assert "拦截" in result.message or "危险" in result.message
        assert result.fix_attempts == 0


# ---------------------------------------------------------------------------
# Executor 接口：module 参数（SafeExecutor 向后兼容）
# ---------------------------------------------------------------------------


class TestInterfaceCompat:
    def test_safe_executor_ignores_module_param(self):
        from app.execution.safe_executor import SafeExecutor

        result = SafeExecutor().run("x=1", "", timeout=30, module="user")
        assert result.status.value == "SKIPPED"

    def test_local_executor_default_module_name(self, tmp_path):
        # module 缺省也能跑（接口兼容旧调用）
        ex = LocalExecutor(project_code_dir=tmp_path)
        result = ex.run("print('anon ok')\n", "", timeout=30)
        assert result.status is ExecutionStatus.SUCCESS
