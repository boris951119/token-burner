# -*- coding: utf-8 -*-
"""冷库终检 + schema 审计进自测判分段（96a4a9f157 尸检回归）。

死链回放：生成期 06:18 的修复补丁给 INSERT 加了 created_at、建表 DDL
没有 → 温库里早先版本的列让本地一路判绿 → 官方评测空库冷启动，
POST /api/workbooks ×95 全灭、0/100。三道回归：
① 模板内库文件起服前清除（与官方同一起跑线，温库验不出建表漂移）；
② schema 审计挂进每轮 run_selftests（修复补丁引入的漂移当轮现形，
  不再依赖早前冒烟阶段那一次）；
③ 写码/修复提示词钉住种子判空守卫（5382e37bbf07 首页 500 死因）。
"""
from __future__ import annotations

from pathlib import Path

import app.utils.selftest_gate as sg

DRIFT_MOD = '''
DDL = """
CREATE TABLE IF NOT EXISTS worksheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);
"""

def api_create_workbook(name):
    conn.execute(
        "INSERT INTO worksheets (name, created_at) "
        "VALUES (?, datetime('now'))", (name,))
'''


class _FakeProc:
    pid = 4545

    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def _stub_server(monkeypatch, extra_files: dict[str, str] | None = None):
    import app.platform_export as pe

    def fake_export(out_dir, project_dir):
        backend = out_dir / "backend"
        backend.mkdir(parents=True, exist_ok=True)
        (backend / "main.py").write_text("pass", encoding="utf-8")
        for rel, text in (extra_files or {}).items():
            p = out_dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return {"backend_files": 1, "frontend_files": 0}

    monkeypatch.setattr(pe, "export_platform_layout", fake_export)
    monkeypatch.setattr(sg, "_free_port", lambda prefer: 39995)
    monkeypatch.setattr(sg.subprocess, "Popen",
                        lambda *a, **k: _FakeProc())
    monkeypatch.setattr(sg, "_wait_health",
                        lambda url, deadline_s=60, proc=None: True)


def test_coldboot_wipes_db_files_in_template(tmp_path, monkeypatch):
    """导出模板里的库文件（含 sqlite 伴生文件）起服前清除；非库文件保留。"""
    _stub_server(monkeypatch, extra_files={
        "backend/app.db": "warm",
        "backend/app.db-journal": "warm",
        "backend/data/store.sqlite3": "warm",
        "backend/keep.txt": "stay",
    })
    passed, failed, failures, tail = sg.run_selftests(tmp_path, None)
    assert "冷库终检：清除 3 个库文件" in tail, tail
    assert not list(tmp_path.glob(".selftest_template*/**/*.db"))
    assert not list(tmp_path.glob(".selftest_template*/**/*.sqlite3"))
    kept = list(tmp_path.glob(".selftest_template*/backend/keep.txt"))
    assert kept, "非库文件不得误删"


def test_schema_drift_surfaced_in_failures(tmp_path, monkeypatch):
    """96a4 形态：DDL 无 created_at、INSERT 带——判分段必须出红且带定位。"""
    _stub_server(monkeypatch, extra_files={
        "backend/workbook_list_create_api.py": DRIFT_MOD})
    passed, failed, failures, tail = sg.run_selftests(tmp_path, None)
    assert failed >= 1, "schema 漂移不得被零信号放行"
    joined = "\n".join(failures)
    assert "[schema]" in joined and "created_at" in joined, joined
    assert "workbook_list_create_api.py" in joined, "定位到文件才能进修复指令"


def test_wipe_database_files_matches_companion_files(tmp_path):
    (tmp_path / "a.db").write_text("x", encoding="utf-8")
    (tmp_path / "b.sqlite-wal").write_text("x", encoding="utf-8")
    (tmp_path / "c.txt").write_text("x", encoding="utf-8")
    gone = sg._wipe_database_files(tmp_path)
    assert gone == ["a.db", "b.sqlite-wal"]
    assert (tmp_path / "c.txt").is_file()


def test_prompts_pin_seed_guard_and_coldboot_contract():
    root = Path(__file__).resolve().parents[1]
    write_sys = (root / "app" / "prompts" / "write_code_system.md").read_text(
        encoding="utf-8")
    fix_sys = (root / "app" / "prompts" / "fix_code_system.md").read_text(
        encoding="utf-8")
    # 5382e37bbf07 死因：种子查询 None 直接下标 → 冷启动首页 500
    assert "判空守卫" in write_sys and "自动补种" in write_sys
    assert "禁止对查询" in write_sys and "下标取值" in write_sys
    # 修复侧同契约：DDL 唯一权威 + 判空守卫
    assert "冷启动契约" in fix_sys and "seed_data" in fix_sys
