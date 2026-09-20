# -*- coding: utf-8 -*-
"""grade_repair_loop 回滚保险：修复前快照 → 改坏 → diff 存档 → 整体还原。

bookstack 取证：修复轮 git checkout 整体回滚未先 diff 丢过有益改动；
keep7 取证：修复把好状态改坏且无路可退。此二问题都由该保险兜住。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.grade_repair_loop as grl
from scripts.grade_repair_loop import _archive_diff_and_restore, _snapshot


def _mk_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / "code").mkdir(parents=True)
    (proj / "code" / "main.py").write_text("print('v1')\n", encoding="utf-8")
    (proj / "frontend").mkdir()
    (proj / "frontend" / "index.html").write_text(
        "<h1>v1</h1>", encoding="utf-8")
    (proj / "__pycache__").mkdir()
    (proj / "__pycache__" / "junk.pyc").write_text("x", encoding="utf-8")
    return proj


def test_snapshot_excludes_caches(tmp_path):
    proj = _mk_project(tmp_path)
    snap = _snapshot(proj)
    assert (snap / "code" / "main.py").read_text(
        encoding="utf-8") == "print('v1')\n"
    assert not (snap / "__pycache__").exists()


def test_rollback_restores_state_and_archives_diff(tmp_path, monkeypatch):
    # diff 落盘位置随 ROOT 隔离到 tmp，不污染仓库 logs/
    monkeypatch.setattr(grl, "ROOT", tmp_path)
    proj = _mk_project(tmp_path / "work")  # 项目与 ROOT/logs 不同层
    snap = _snapshot(proj)
    # 模拟坏修复：改坏既有文件 + 新增无关文件
    (proj / "code" / "main.py").write_text(
        "print('BROKEN')\n", encoding="utf-8")
    (proj / "code" / "extra.py").write_text("x = 1\n", encoding="utf-8")

    patch = _archive_diff_and_restore(proj, snap, "ut")

    # 状态回到快照：改坏的被还原、新增的被清掉
    assert (proj / "code" / "main.py").read_text(
        encoding="utf-8") == "print('v1')\n"
    assert not (proj / "code" / "extra.py").exists()
    assert (proj / "frontend" / "index.html").read_text(
        encoding="utf-8") == "<h1>v1</h1>"
    # diff 先于还原落盘，坏改动可追溯
    diff_text = patch.read_text(encoding="utf-8", errors="replace")
    assert "BROKEN" in diff_text
    assert "extra.py" in diff_text
    assert patch.parent == tmp_path / "logs" / "repair_rollback"


def test_rollback_brings_back_deleted_file(tmp_path, monkeypatch):
    monkeypatch.setattr(grl, "ROOT", tmp_path)
    proj = _mk_project(tmp_path / "work")
    snap = _snapshot(proj)
    (proj / "frontend" / "index.html").unlink()  # 坏修复删了好文件

    _archive_diff_and_restore(proj, snap, "ut")

    assert (proj / "frontend" / "index.html").exists()
