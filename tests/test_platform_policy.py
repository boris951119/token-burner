"""M14-3/M14-4 平台约束与平台黑名单测试（v1.0 V1 批次）。

场景来源：v0.5 真实验收——file_utils 生成代码 `import fcntl`（Unix-only），
交付物在 Windows 直接 ImportError；提示词无平台约束、扫描无平台类别。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.execution.local_executor import (  # noqa: E402
    LocalExecutor,
    scan_dangerous,
)
from app.utils.platform_policy import (  # noqa: E402
    prompt_constraint,
    unavailable_modules,
)

FCNTL_CODE = "import fcntl\n\n\ndef lock(f):\n    return fcntl.lockf(f)\n"


class TestPlatformPolicy:
    def test_windows_unavailable_contains_fcntl(self):
        """v0.5 事故模块在 windows 黑名单。"""
        assert "fcntl" in unavailable_modules("windows")
        assert "termios" in unavailable_modules("windows")

    def test_linux_unavailable_contains_msvcrt(self):
        assert "msvcrt" in unavailable_modules("linux")
        assert "fcntl" not in unavailable_modules("linux")

    def test_any_is_empty(self):
        """any → 不检查（跨平台模式，行为与 v0.5 一致）。"""
        assert unavailable_modules("any") == frozenset()

    def test_prompt_constraint_windows(self):
        """windows 提示词段含黑名单模块与替代指引。"""
        p = prompt_constraint("windows")
        assert "fcntl" in p
        assert "Windows" in p
        assert "msvcrt" in p          # 替代方案提示

    def test_prompt_constraint_any_empty(self):
        assert prompt_constraint("any") == ""


class TestSettingsPlatform:
    def test_default_windows(self):
        """缺省 windows（本机交付环境，v0.5 教训）。"""
        assert Settings().target_platform == "windows"

    def test_invalid_rejected(self):
        with pytest.raises(ValueError, match="target_platform"):
            Settings(target_platform="bad")


class TestScanDangerousPlatform:
    def test_fcntl_blocked_on_windows(self):
        """v0.5 事故场景：fcntl 在 windows 目标被扫描拦截。"""
        issues = scan_dangerous(FCNTL_CODE, platform="windows")
        assert issues and "fcntl" in issues[0]
        assert "ImportError" in issues[0]

    def test_fcntl_allowed_on_any(self):
        assert scan_dangerous(FCNTL_CODE, platform="any") == []

    def test_from_import_form_caught(self):
        issues = scan_dangerous(
            "from fcntl import lockf\n", platform="windows")
        assert issues and "fcntl" in issues[0]

    def test_msvcrt_blocked_on_linux(self):
        issues = scan_dangerous("import msvcrt\n", platform="linux")
        assert issues and "msvcrt" in issues[0]

    def test_tests_text_also_scanned(self):
        """测试代码里的平台不可用 import 同样拦截。"""
        issues = scan_dangerous("def t():\n    pass\n", FCNTL_CODE,
                                platform="windows")
        assert issues


class TestExecutorPlatformWiring:
    def test_local_executor_blocks_fcntl(self):
        """LocalExecutor(platform=windows) 执行 fcntl 代码 → BLOCKED。"""
        ex = LocalExecutor(platform="windows")
        result = ex.run(
            code=FCNTL_CODE, tests="", timeout=5, module="file_lock",
        )
        assert result.status.value == "BLOCKED"
        assert "fcntl" in result.message

    def test_local_executor_any_passes_scan(self):
        """any 平台：扫描放行（后续真实执行路径由既有测试覆盖）。"""
        ex = LocalExecutor(platform="any")
        result = ex.run(
            code="def f():\n    return 1\n",
            tests="def test_f():\n    assert f() == 1\n",
            timeout=10, module="m",
        )
        assert result.status.value != "BLOCKED"

    def test_factory_passes_platform(self):
        """工厂构造 LocalExecutor 时透传 target_platform。"""
        from app.execution.factory import build_executor

        s = Settings(docker_executor_enabled=False)
        ex = build_executor("auto", s)
        assert isinstance(ex, LocalExecutor)
        assert ex.platform == "windows"    # Settings 缺省

    def test_devloop_prompt_injected(self):
        """DevLoopEngine 按 target_platform 预生成提示词段。"""
        from app.agents.dev_loop import DevLoopEngine
        from app.execution.safe_executor import SafeExecutor

        class StubFM:
            pass

        engine = DevLoopEngine(
            llm=object(), executor=SafeExecutor(),
            settings=Settings(target_platform="windows"),
            file_manager=StubFM(), dev_model="d", test_model="t",
        )
        assert "fcntl" in engine._platform_prompt

        engine_any = DevLoopEngine(
            llm=object(), executor=SafeExecutor(),
            settings=Settings(target_platform="any"),
            file_manager=StubFM(), dev_model="d", test_model="t",
        )
        assert engine_any._platform_prompt == ""
