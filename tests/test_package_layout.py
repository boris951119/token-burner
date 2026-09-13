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
    _mk_pkg(tmp_path, "auth", {"auth.py": "x = 1\n"})
    _mk_pkg(tmp_path, "web_ui", {
        "web_ui.py": "import auth\nfrom auth import register\n",
    })
    assert _package_layout_section(tmp_path) == ""


def test_third_party_imports_ignored(tmp_path):
    _mk_pkg(tmp_path, "web_ui", {
        "web_ui.py": "import flask\nimport os\nfrom sqlite3 import connect\n",
    })
    assert _package_layout_section(tmp_path) == ""
