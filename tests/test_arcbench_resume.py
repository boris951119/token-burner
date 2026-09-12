"""--resume 恢复查找测试（factory26 r4：硬杀进程场景）。

取证：interruption.md 只在协作式 Ctrl+C 落盘，平台 runner 超时硬杀
时不存在——旧判据（快照 + 中断标记双要件）在平台场景恒为空。
新判据：快照存在且无 completed.json；协作式中断优先。
"""

from __future__ import annotations

from pathlib import Path

from app.tools.file_manager import FileManager
from main import _find_resumable_project


def _mk_project(root: Path, name: str, *, state: bool, interrupted: bool, completed: bool) -> Path:
    sessions = root / name / "sessions"
    sessions.mkdir(parents=True)
    if state:
        (sessions / "pipeline_state.json").write_text("{}", encoding="utf-8")
    if interrupted:
        (sessions / "interruption.md").write_text("interrupted", encoding="utf-8")
    if completed:
        (sessions / "completed.json").write_text("{}", encoding="utf-8")
    return root / name


def test_hard_killed_project_is_resumable(tmp_path):
    """硬杀现场：只有快照、无任何标记 → 可恢复（旧判据找不到）。"""
    fm = FileManager(projects_root=tmp_path)
    _mk_project(tmp_path, "proj_a", state=True, interrupted=False, completed=False)
    assert _find_resumable_project(fm) == "proj_a"


def test_completed_project_not_resumable(tmp_path):
    fm = FileManager(projects_root=tmp_path)
    _mk_project(tmp_path, "done", state=True, interrupted=False, completed=True)
    assert _find_resumable_project(fm) is None


def test_interrupted_preferred_over_newer_hard_kill(tmp_path):
    """协作式中断与硬杀并存：优先协作式中断（标记可信）。"""
    import os

    fm = FileManager(projects_root=tmp_path)
    cooperative = _mk_project(
        tmp_path, "coop", state=True, interrupted=True, completed=False
    )
    hard_killed = _mk_project(
        tmp_path, "hard", state=True, interrupted=False, completed=False
    )
    # 把硬杀的 mtime 调新——若按纯 mtime 排序会选错
    st = hard_killed.stat()
    os.utime(hard_killed, (st.st_atime + 10, st.st_mtime + 10))
    assert _find_resumable_project(fm) == cooperative.name


def test_newest_snapshot_wins_among_hard_kills(tmp_path):
    import os

    fm = FileManager(projects_root=tmp_path)
    _mk_project(tmp_path, "old", state=True, interrupted=False, completed=False)
    newest = _mk_project(
        tmp_path, "new", state=True, interrupted=False, completed=False
    )
    st = newest.stat()
    os.utime(newest, (st.st_atime + 10, st.st_mtime + 10))
    assert _find_resumable_project(fm) == "new"
