# -*- coding: utf-8 -*-
"""包结构审计测试（r17 取证：组装模块 import auth，实际包 f1_auth，
空壳包 auth/ 只有 __init__.py——ModuleNotFoundError 的真凶是命名漂移）。"""

from __future__ import annotations

from pathlib import Path

from app.arcbench_smoke import _package_layout_section


def _mk_pkg(root: Path, name: str, files: dict[str, str]) -> None:
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for rel, text in files.items():
        p = pkg / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def test_r17_case_import_drift_and_empty_shell(tmp_path):
    """组装模块 import auth/search/booking，实际包是 f1_* 前缀。"""
    _mk_pkg(tmp_path, "f1_auth", {"f1_auth.py": "def register(): ...\n"})
    _mk_pkg(tmp_path, "f2_search", {"f2_search.py": "def search(): ...\n"})
    _mk_pkg(tmp_path, "web_ui", {
        "web_ui.py": "import auth\nimport search\nimport booking\n",
    })
    # 空壳包
    _mk_pkg(tmp_path, "auth", {})
    _mk_pkg(tmp_path, "search", {})

    section = _package_layout_section(tmp_path)
    assert section, "漂移场景必须产出诊断"
    assert "f1_auth" in section and "实际包名" in section
    assert "空壳包" in section


def test_clean_layout_no_findings(tmp_path):
    _mk_pkg(tmp_path, "auth", {"auth.py": "def register():\n    return 1\n"})
    _mk_pkg(tmp_path, "web_ui", {
        "web_ui.py": "import auth\nfrom auth import register\n",
    })
    assert _package_layout_section(tmp_path) == ""


def test_third_party_imports_ignored(tmp_path):
    _mk_pkg(tmp_path, "web_ui", {
        "web_ui.py": "import flask\nimport os\nfrom sqlite3 import connect\n",
    })
    assert _package_layout_section(tmp_path) == ""


class TestMemSentinel:
    """内存哨兵（官方 2GB 内存取证）：峰值超限判 FAIL。"""

    def test_parse_mem_peak(self):
        from app.arcbench_smoke import _parse_mem_peak

        assert _parse_mem_peak("SMOKE_OK\n@@MEM@@86.3") == 86.3
        assert _parse_mem_peak("no marker") == -1.0

    def test_run_smoke_reports_mem_marker(self, tmp_path):
        """真实冒烟：模板必须产出 @@MEM@@ 行（无阈值误伤时放行）。"""
        pkg = tmp_path / "app_main"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "from app_main.app_main import *  # noqa\n", encoding="utf-8")
        (pkg / "app_main.py").write_text(
            "from flask import Flask\n"
            "def create_app():\n"
            "    app = Flask(__name__)\n"
            "    @app.route('/api/health')\n"
            "    def h(): return {'ok': True}\n"
            "    @app.route('/')\n"
            "    def idx(): return '<a href=\"/x\">x</a>'\n"
            "    return app\n",
            encoding="utf-8")
        from app.arcbench_smoke import run_smoke

        ok, report = run_smoke(tmp_path)
        assert ok, report
        assert "@@MEM@@" in report


class TestSymbolImportAudit:
    """keep3 终局取证：from auth import auth_bp 而 auth 导出 bp——
    符号级导入漂移必须被确定性发现。"""

    def _layout(self, tmp_path):
        auth = tmp_path / "auth"
        auth.mkdir(parents=True)
        (auth / "__init__.py").write_text(
            "from auth.auth import *  # noqa\n", encoding="utf-8")
        (auth / "auth.py").write_text(
            'from flask import Blueprint\n'
            'bp = Blueprint("auth", __name__)\n', encoding="utf-8")
        web = tmp_path / "web_ui"
        web.mkdir(parents=True)
        (web / "__init__.py").write_text("", encoding="utf-8")
        (web / "web_ui.py").write_text(
            "from auth import auth_bp\n", encoding="utf-8")

    def test_symbol_drift_detected(self, tmp_path):
        self._layout(tmp_path)
        section = _package_layout_section(tmp_path)
        assert "auth_bp" in section and "未定义" in section, section

    def test_correct_symbol_no_finding(self, tmp_path):
        self._layout(tmp_path)
        (tmp_path / "web_ui" / "web_ui.py").write_text(
            "from auth import bp\n", encoding="utf-8")
        section = _package_layout_section(tmp_path)
        assert "未定义" not in section, section


class TestAutoShim:
    """机械垫片（gen-3 取证：命名漂移家族第四次杀伤，LLM 修复不可靠）——
    缺失导入名 + 唯一近名真实包 → 自动生成 re-export 垫片。"""

    def _layout_with_drift(self, tmp_path):
        # 真实包 note_home（实现 home 的功能）
        pkg = tmp_path / "note_home"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "note_home.py").write_text(
            "def home_page():\n    return 'HOME'\n"
            "HOME_KEY = 'home'\n", encoding="utf-8")
        # 组装模块 import home（不存在）
        web = tmp_path / "web_frontend"
        web.mkdir(parents=True)
        (web / "__init__.py").write_text("", encoding="utf-8")
        (web / "web_frontend.py").write_text(
            "import home\n"
            "def build():\n    return home.home_page()\n", encoding="utf-8")

    def test_shim_generated_and_importable(self, tmp_path):
        from app.arcbench_smoke import auto_shim_imports

        self._layout_with_drift(tmp_path)
        shims = auto_shim_imports(tmp_path)
        assert shims == ["home"], shims
        # 垫片可导入且 re-export 真实符号
        import importlib, sys

        sys.path.insert(0, str(tmp_path))
        try:
            mod = importlib.import_module("home")
            assert mod.home_page() == "HOME"
            assert mod.HOME_KEY == "home"
        finally:
            sys.path.remove(str(tmp_path))

    def test_existing_module_not_shimmed(self, tmp_path):
        from app.arcbench_smoke import auto_shim_imports

        self._layout_with_drift(tmp_path)
        (tmp_path / "home.py").write_text(
            "def home_page():\n    return 'REAL'\n", encoding="utf-8")
        assert auto_shim_imports(tmp_path) == []

    def test_no_near_name_no_shim(self, tmp_path):
        from app.arcbench_smoke import auto_shim_imports

        pkg = tmp_path / "note_home"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        web = tmp_path / "web_frontend"
        web.mkdir(parents=True)
        (web / "__init__.py").write_text("", encoding="utf-8")
        (web / "web_frontend.py").write_text(
            "import totally_unrelated\n", encoding="utf-8")
        assert auto_shim_imports(tmp_path) == []


class TestAutoBindSubmodules:
    """keep4 终局取证：from seed_data import seed_data（同名子模块）
    ——包 __init__ 未绑定子模块属性时 ImportError。"""

    def test_submodule_auto_bound(self, tmp_path):
        from app.arcbench_smoke import auto_bind_submodules

        pkg = tmp_path / "seed_data"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "seed_data.py").write_text(
            "SEED = 'G101'\n", encoding="utf-8")
        web = tmp_path / "web_ui"
        web.mkdir(parents=True)
        (web / "__init__.py").write_text("", encoding="utf-8")
        (web / "web_ui.py").write_text(
            "from seed_data import seed_data\n", encoding="utf-8")

        fixed = auto_bind_submodules(tmp_path)
        assert fixed == ["seed_data"]
        init_src = (pkg / "__init__.py").read_text(encoding="utf-8")
        assert "from . import seed_data" in init_src

    def test_already_bound_no_change(self, tmp_path):
        from app.arcbench_smoke import auto_bind_submodules

        pkg = tmp_path / "seed_data"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text(
            "from . import seed_data  # noqa\n", encoding="utf-8")
        (pkg / "seed_data.py").write_text("S = 1\n", encoding="utf-8")
        web = tmp_path / "web_ui"
        web.mkdir(parents=True)
        (web / "__init__.py").write_text("", encoding="utf-8")
        (web / "web_ui.py").write_text(
            "from seed_data import seed_data\n", encoding="utf-8")
        assert auto_bind_submodules(tmp_path) == []


class TestAnchorCoverageSection:
    """gen-6 取证家族通用化：需求锚点（机械提取）在页面响应中的
    覆盖探针——Quick Guide 类内容缺陷的确定性检测。"""

    def _app(self, tmp_path, home_body):
        pkg = tmp_path / "web_frontend"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text(
            "from web_frontend.web_frontend import *  # noqa\n",
            encoding="utf-8")
        (pkg / "web_frontend.py").write_text(
            "from flask import Flask\n"
            "def create_app():\n"
            "    app = Flask(__name__)\n"
            "    @app.route('/api/health')\n"
            "    def h(): return {'ok': True}\n"
            f"    @app.route('/')\n    def i(): return {home_body!r}\n"
            "    return app\n", encoding="utf-8")

    def test_missing_anchor_reported(self, tmp_path):
        self._app(tmp_path, "Home without guide")
        from app.arcbench_smoke import _anchor_coverage_section

        section = _anchor_coverage_section(tmp_path, '需求含 "Quick Guide" 导航')
        assert "Quick Guide" in section and "未出现" in section, section

    def test_covered_anchor_no_finding(self, tmp_path):
        self._app(tmp_path, "Home with Quick Guide link")
        from app.arcbench_smoke import _anchor_coverage_section

        section = _anchor_coverage_section(tmp_path, '需求含 "Quick Guide" 导航')
        assert section == "" or "Quick Guide" not in section.split("已出现")[-1], section
