"""static_check 单元测试（TDD 先行）。

依据：规格文档 17 章第三阶段：utils/static_check.py——
ast.parse 语法门禁 + import / 引用核验（生成后静态验证，
安全模式下减少无意义修复轮数，19 章「代码质量门禁」）。
"""

from __future__ import annotations

from app.utils.static_check import StaticCheckResult, check_imports, check_syntax, run_static_check


class TestSyntaxCheck:
    def test_valid_code_passes(self):
        issues = check_syntax("x = 1\nprint(x)\n")
        assert issues == []

    def test_syntax_error_reported_with_line(self):
        issues = check_syntax("def f(:\n    pass\n")
        assert len(issues) == 1
        assert "语法" in issues[0]

    def test_empty_code_passes_syntax(self):
        assert check_syntax("") == []

    def test_incomplete_code_reported(self):
        issues = check_syntax("def f():\n    return {")
        assert len(issues) == 1


class TestImportCheck:
    def test_project_module_import_ok(self):
        code = "import user\nfrom data import store\n"
        issues = check_imports(code, project_modules={"user", "data"})
        assert issues == []

    def test_ghost_project_import_reported(self):
        # 引用核验（契约驱动）：契约声明依赖某模块但项目无此模块 → 幽灵
        code = "import ghost_module\n"
        issues = check_imports(
            code, project_modules={"user", "data"}, declared_deps={"ghost_module"}
        )
        assert len(issues) == 1
        assert "ghost_module" in issues[0]

    def test_undeclared_project_import_reported(self):
        # 代码 import 了项目模块但契约未声明 → 未声明跨模块依赖
        code = "import user\n"
        issues = check_imports(code, project_modules={"user", "data"}, declared_deps=set())
        assert len(issues) == 1
        assert "user" in issues[0]

    def test_stdlib_import_allowed(self):
        code = "import json\nfrom pathlib import Path\n"
        assert check_imports(code, project_modules=set()) == []

    def test_third_party_import_allowed_but_flagged_info(self):
        # 第三方依赖不阻断（由 requirements 管理），仅提示
        code = "import numpy\n"
        result = run_static_check(code, project_modules=set())
        assert result.passed is True  # 不算失败
        assert any("numpy" in i for i in result.warnings)

    def test_relative_import_within_module_ok(self):
        code = "from . import helper\n"
        assert check_imports(code, project_modules=set()) == []


class TestRunStaticCheck:
    def test_result_structure(self):
        result = run_static_check("x = 1\n", project_modules=set())
        assert isinstance(result, StaticCheckResult)
        assert result.passed is True
        assert result.issues == []
        assert result.warnings == []

    def test_syntax_failure_blocks(self):
        result = run_static_check("def broken(:\n", project_modules=set())
        assert result.passed is False
        assert result.issues

    def test_ghost_import_failure_blocks(self):
        # 契约声明依赖 user 而项目仅有 data → 幽灵引用（阻断）
        result = run_static_check(
            "import user\n", project_modules={"data"}, declared_deps={"user"}
        )
        assert result.passed is False
        assert "user" in result.issues[0]

    def test_combined_checks(self):
        # 语法错误优先报告（AST 无法解析时 import 核验无从谈起）
        result = run_static_check("import ghost\nbroken((\n", project_modules=set())
        assert result.passed is False
        assert any("语法" in i for i in result.issues)
