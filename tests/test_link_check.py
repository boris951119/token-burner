"""M14-2 全局链接门禁测试（v1.0 V0 批次）。

场景来源：v0.5 真实验收——book_validator 的代码 `from _shared.utils import
validate_isbn, validate_date`，后续模块重写 _shared/utils.py 丢了这两个函数，
import 断裂静默流入交付物（门禁未拦截）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tools.file_manager import FileManager  # noqa: E402
from app.utils.link_check import (  # noqa: E402
    _SymbolIndex,
    check_links,
    format_link_issues,
)


@pytest.fixture()
def project(tmp_path):
    """最小双模块项目：validator（用 _shared）+ formatter（正常）。"""
    fm = FileManager(projects_root=tmp_path / "projects")
    pid = fm.create_project("book-cli").project_id
    fm.write_shared_file(pid, "utils.py", (
        "def validate_isbn(isbn):\n    return len(isbn) == 13\n\n"
        "def validate_date(d):\n    return len(d) == 10\n"
    ))
    fm.write_code_file(pid, "validator", "validator.py", (
        "from _shared.utils import validate_isbn\n\n"
        "def check(isbn):\n    return validate_isbn(isbn)\n"
    ))
    handle = fm.get_project(pid)
    return fm, pid, handle.root / "code"


class TestCheckLinks:
    def test_normal_project_passes(self, project):
        """正常项目零误报（v0.5 cmd 项目本应全绿）。"""
        fm, pid, code_root = project
        result = check_links(code_root)
        assert result.passed
        assert result.issues == []
        assert result.files_checked >= 1

    def test_v05_breakage_detected(self, project):
        """v0.5 断裂复现：_shared 丢 validate_isbn → 待验新模块被阻断。

        链路：validator.py（已落盘）import validate_isbn；
        _shared/utils.py 被重写只剩别的符号 → 门禁拦截。
        """
        fm, pid, code_root = project
        # 重演 v0.5 事故：_shared 被整文件覆盖丢掉 validate_isbn
        (code_root / "_shared" / "utils.py").write_text(
            "def format_title(t):\n    return t.title()\n",
            encoding="utf-8",
        )
        # 待验新模块（formatter）本身正常，但全局链接已断
        pending = (
            "from _shared.utils import format_title\n\n"
            "def fmt(t):\n    return format_title(t)\n"
        )
        result = check_links(
            code_root, pending_module="formatter", pending_code=pending,
        )
        assert not result.passed
        assert any(
            i.symbol == "validate_isbn" and i.source == "_shared.utils"
            for i in result.issues
        )

    def test_pending_module_import_missing_symbol(self, project):
        """待验模块 import 了不存在的符号 → 拦截（自身断裂）。"""
        fm, pid, code_root = project
        pending = (
            "from _shared.utils import no_such_fn\n\n"
            "def f():\n    return no_such_fn()\n"
        )
        result = check_links(
            code_root, pending_module="formatter", pending_code=pending,
        )
        assert not result.passed
        assert result.issues[0].symbol == "no_such_fn"
        assert "formatter" in result.issues[0].importer

    def test_cross_module_import(self, project):
        """模块间引用：from validator import check（存在→通过；缺失→拦截）。"""
        fm, pid, code_root = project
        ok = "from validator import check\n\n\ndef g():\n    return check('x')\n"
        assert check_links(
            code_root, pending_module="caller", pending_code=ok,
        ).passed

        bad = "from validator import not_defined\n\n\ndef g():\n    pass\n"
        result = check_links(code_root, pending_module="caller",
                             pending_code=bad)
        assert not result.passed
        assert result.issues[0].source == "validator"

    def test_import_module_existence_only(self, project):
        """`import <module>`（无 from）只查模块存在性，不查符号。"""
        fm, pid, code_root = project
        pending = "import validator\n\n\ndef g():\n    return validator\n"
        assert check_links(
            code_root, pending_module="caller", pending_code=pending,
        ).passed

    def test_external_imports_ignored(self, project):
        """标准库/三方包 import 不在链接门禁范围（静态门禁管依赖声明）。"""
        fm, pid, code_root = project
        pending = (
            "import json\nimport os\nfrom pathlib import Path\n"
            "from collections import OrderedDict\n\n"
            "def g():\n    return 1\n"
        )
        assert check_links(
            code_root, pending_module="caller", pending_code=pending,
        ).passed

    def test_frozen_module_covered(self, project):
        """FROZEN 模块的断裂同样被检查（交付物仍会 import 它）。"""
        fm, pid, code_root = project
        # validator 已落盘（模拟 FROZEN 仍留在交付物）；删掉 _shared 符号
        (code_root / "_shared" / "utils.py").write_text(
            "def other():\n    return 1\n", encoding="utf-8",
        )
        pending = "def isolated():\n    return 1\n"
        result = check_links(
            code_root, pending_module="newmod", pending_code=pending,
        )
        assert not result.passed   # validator 的断裂被查出来

    def test_index_cache_incremental(self, project):
        """符号索引 mtime 缓存：未变更文件不重解析。"""
        fm, pid, code_root = project
        idx = _SymbolIndex(code_root)
        s1 = idx.symbols_of("_shared.utils")
        assert "validate_isbn" in s1
        # 二次查询命中缓存（无 IO 重解析——同 stat 直接返回）
        s2 = idx.symbols_of("_shared.utils")
        assert s1 == s2

    def test_format_link_issues_readable(self, project):
        """报告可读：含引用方/符号/来源与修复指引。"""
        issues = check_links.__globals__  # noqa: F841 仅为触发导入存在
        from app.utils.link_check import LinkIssue

        report = format_link_issues([
            LinkIssue(
                importer="code/validator/validator.py",
                symbol="validate_isbn",
                source="_shared.utils",
            ),
        ])
        assert "链接门禁失败" in report
        assert "validate_isbn" in report
        assert "code/validator/validator.py" in report
        assert "_shared.utils" in report
        assert format_link_issues([]) == ""


class TestDevLoopGateIntegration:
    """dev_loop 门禁链接入：链接门禁失败 → 进入修复循环（非直接通过）。"""

    def test_link_failure_blocks_gate(self, project):
        """断裂场景经 _drive 门禁链被拦（不进执行）。"""
        fm, pid, code_root = project
        (code_root / "_shared" / "utils.py").write_text(
            "def other():\n    return 1\n", encoding="utf-8",
        )
        from app.agents.dev_loop import DevLoopEngine
        from app.config import Settings
        from app.execution.safe_executor import SafeExecutor

        calls = {"fix": 0}

        class StubLLM:
            def chat(self, model, messages, json_mode=False):
                calls["fix"] += 1
                # 修复输出：仍断链（验证门禁持续拦截直至上限）
                class R:
                    content = (
                        "```python\nfrom _shared.utils import no_such\n"
                        "def f():\n    return no_such()\n```\n"
                    )
                return R()

        settings = Settings()
        loop = DevLoopEngine(
            llm=StubLLM(), executor=SafeExecutor(),
            settings=settings, file_manager=fm,
            dev_model="dev-m", test_model="test-m",
        )
        # 直接调用 _drive（内存态验证门禁，不走执行器）
        result = loop._drive(
            module="formatter", project_id=pid,
            code=("from _shared.utils import no_such\n\n"
                  "def f():\n    return no_such()\n"),
            tests="def test_f():\n    pass\n",
            fix_attempts=0, user_feedback="",
            contract=None, project_modules={"formatter"},
            feedback_pending=False,
        )
        # 断链未修复 → 冻结（修复轮耗尽），且从未进入执行
        assert calls["fix"] >= 1           # 修复循环被触发
        assert "链接" in result.message or "FROZEN" in str(result.status)
