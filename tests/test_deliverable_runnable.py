"""交付物真实可运行性测试（产品审计问题 1 修复，TDD 先行）。

问题：多模块项目代码布局为 code/<module>/<module>.py，跨模块引用
`from <module> import <符号>`、公共层 `from _shared.<文件> import <符号>`——
按旧指引（cd code/<模块> && python <模块>.py）运行时兄弟目录不在
sys.path 上，交付物结构性跑不起来。

修复约定（程序确定性生成，非 LLM）：
- code/<module>/__init__.py：包级重导出（from <module>.<module> import *），
  使 `from <module> import <符号>` 在 code/ 为工作目录时可解析；
- code/_shared/__init__.py：包标记（空文件）；
- 项目根 conftest.py：把 code/ 插入 sys.path（pytest 可导入项目模块）。

验收标准（真实子进程，非 mock）：
- cd code && python -m <module>.<module> 直接运行（含跨模块与 _shared 引用）；
- 项目根目录 python -m pytest tests/<module>/ 通过。
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from app.tools.file_manager import FileManager


@pytest.fixture
def fm(tmp_path):
    return FileManager(projects_root=tmp_path / "projects")


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", timeout=60,
    )


def _build_two_module_project(fm):
    """双模块 + _shared 交付物：auth 跨模块引用 user，user 引用 _shared。"""
    project_id = fm.create_project("可运行交付物验证").project_id
    fm.write_code_file(project_id, "user", "user.py", (
        "from _shared.utils import helper\n"
        "\n"
        "\n"
        "def core_fn():\n"
        "    return helper() + 1\n"
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    print('user ok', core_fn())\n"
    ))
    fm.write_code_file(project_id, "auth", "auth.py", (
        "from user import core_fn\n"
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    print('auth ok', core_fn())\n"
    ))
    fm.write_shared_file(project_id, "utils.py", "def helper():\n    return 41\n")
    fm.write_test_file(
        project_id, "user", "test_user.py",
        "from user import core_fn\n\n\ndef test_core():\n    assert core_fn() == 42\n",
    )
    return fm.get_project(project_id)


# ---------------------------------------------------------------------------
# 路径基础设施生成（确定性，随文件写入自动落盘）
# ---------------------------------------------------------------------------


class TestPathInfrastructure:
    def test_project_scaffold_creates_root_conftest(self, fm):
        # 项目创建即生成根 conftest.py（pytest 导入路径引导）
        handle = fm.create_project("demo")
        conftest = handle.root / "conftest.py"
        assert conftest.is_file()
        content = conftest.read_text(encoding="utf-8")
        assert "sys.path" in content and "code" in content

    def test_module_init_reexport_created(self, fm):
        # 写入模块代码 → 同目录自动生成 __init__.py（包级重导出）
        project_id = fm.create_project("demo").project_id
        fm.write_code_file(project_id, "user", "user.py", "def core_fn():\n    return 1\n")
        init = fm.get_project(project_id).root / "code" / "user" / "__init__.py"
        assert init.is_file()
        assert "from user.user import" in init.read_text(encoding="utf-8")

    def test_module_init_idempotent(self, fm):
        # 修复轮重写代码 → __init__.py 内容稳定（不堆积、不漂移）
        project_id = fm.create_project("demo").project_id
        fm.write_code_file(project_id, "user", "user.py", "def a():\n    return 1\n")
        fm.write_code_file(project_id, "user", "user.py", "def b():\n    return 2\n")
        init = fm.get_project(project_id).root / "code" / "user" / "__init__.py"
        content = init.read_text(encoding="utf-8")
        assert content.count("from user.user import") == 1

    def test_shared_init_created(self, fm):
        # 写入公共层文件 → _shared/__init__.py 包标记
        project_id = fm.create_project("demo").project_id
        fm.write_shared_file(project_id, "utils.py", "def helper():\n    return 1\n")
        init = fm.get_project(project_id).root / "code" / "_shared" / "__init__.py"
        assert init.is_file()

    def test_non_canonical_filename_no_init(self, fm):
        # 非约定文件名（如辅助文件）不生成重导出 init（避免误包）
        project_id = fm.create_project("demo").project_id
        fm.write_code_file(project_id, "user", "helpers.py", "x = 1\n")
        init = fm.get_project(project_id).root / "code" / "user" / "__init__.py"
        assert not init.is_file()


# ---------------------------------------------------------------------------
# 真实子进程运行验收
# ---------------------------------------------------------------------------


class TestRealRunnability:
    def test_cross_module_run(self, fm):
        # auth 引用 user → cd code && python -m auth.auth 正常运行
        handle = _build_two_module_project(fm)
        result = _run(["-m", "auth.auth"], handle.root / "code")
        assert result.returncode == 0, result.stderr
        assert "auth ok 42" in result.stdout

    def test_shared_import_run(self, fm):
        # user 引用 _shared → python -m user.user 正常运行
        handle = _build_two_module_project(fm)
        result = _run(["-m", "user.user"], handle.root / "code")
        assert result.returncode == 0, result.stderr
        assert "user ok 42" in result.stdout

    def test_pytest_from_project_root(self, fm):
        # 项目根目录运行 pytest：conftest 注入 code/ 路径 → 测试导入成功
        handle = _build_two_module_project(fm)
        result = _run(["-m", "pytest", "tests/user", "-q"], handle.root)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 passed" in result.stdout

    def test_single_module_layout_runnable(self, fm):
        # 单模块路径（12.2 直出）同样以 code/<m>/<m>.py 落盘 → 同样可运行
        project_id = fm.create_project("单模块").project_id
        fm.write_code_file(project_id, "main", "main.py", (
            "def run():\n    return 7\n\n\n"
            'if __name__ == "__main__":\n    print("main ok", run())\n'
        ))
        handle = fm.get_project(project_id)
        result = _run(["-m", "main.main"], handle.root / "code")
        assert result.returncode == 0, result.stderr
        assert "main ok 7" in result.stdout


# ---------------------------------------------------------------------------
# 用户指引文案与实际结构一致
# ---------------------------------------------------------------------------


class TestInstructionsMatchLayout:
    def test_safe_executor_message_uses_module_run_command(self):
        # 指引必须与布局一致：cd code + python -m <模块名>.<模块名>
        from app.execution.safe_executor import SafeExecutor

        message = SafeExecutor().run("x=1", "", timeout=30).message
        assert "python -m" in message
        assert "code" in message
        # 旧指引（cd 进模块目录后 python <模块>.py）必须移除——该方式必挂
        assert "python <模块名>.py" not in message

    def test_safe_executor_test_command_from_project_root(self):
        # 测试指引：项目根目录运行（conftest 在根目录）
        from app.execution.safe_executor import SafeExecutor

        message = SafeExecutor().run("x=1", "def test_x(): pass", timeout=30).message
        assert "pytest" in message
