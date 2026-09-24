# -*- coding: utf-8 -*-
"""首页路由的修复优先级（run 088dd22be41b 实证）：官方那一跑产物起服、
`/api/health` 绿，但 `GET /` 一路 404 到结束——评测从首页进入走旅程，首页
断＝全部页面类用例一起判红。首页失败必须排在修复队列第一位，而不是混在
报告尾部等模型自己看见。"""
from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import app.arcbench_smoke as sm
import app.agents.repo_fixer as rf
from app.config import Settings


class TestHomeRoutePriorityNote:
    def test_silent_when_home_is_not_the_failure(self):
        assert sm._home_route_priority_note("") == ""
        assert sm._home_route_priority_note(
            "/api/health -> 500\nimport boom") == "", \
            "没有首页失败却塞优先指令＝给修复环加噪声"

    def test_names_home_and_forbids_placeholder(self):
        note = sm._home_route_priority_note(
            "GET / -> 404（入口路由缺失？）")
        assert note.strip()
        assert "GET /" in note
        assert "首页" in note
        assert "占位" in note, "必须同时关住「用占位页糊弄首页」这条退路"
        assert note.endswith("\n\n"), "要拼在修复指令最前，得自带分隔"


class TestPriorityNoteReachesFixer:
    """门闸把首页失败报出来了，还得确认它真被灌进修复指令的第一段。"""

    def _run(self, tmp_path, monkeypatch, smoke_report):
        captured = {}

        class _FakeFixer:
            def __init__(self, llm, project_dir, **kw):
                captured["kw"] = kw

            def fix(self, issue):
                captured["issue"] = issue
                return SimpleNamespace(ok=True, rounds=1, diff="", error="")

        monkeypatch.setattr(rf, "RepoFixer", _FakeFixer)
        monkeypatch.setattr(sm, "run_smoke",
                            lambda code_dir: (False, smoke_report))
        (tmp_path / "code").mkdir(parents=True, exist_ok=True)
        sm.auto_repair(tmp_path, Settings(),
                       priority_note=sm._home_route_priority_note(smoke_report))
        return captured

    def test_home_failure_puts_the_note_at_the_front(self, tmp_path, monkeypatch):
        got = self._run(tmp_path, monkeypatch,
                        "entry <- app\nGET / -> 404（入口路由缺失？）")
        issue = got["issue"]
        assert issue.startswith("【本轮唯一优先目标】"), issue[:80]
        assert issue.index("【本轮唯一优先目标】") < issue.index("集成冒烟失败"), \
            "优先目标必须排在冒烟报告之前，否则被尾部截断吃掉"

    def test_other_failures_issue_is_unchanged(self, tmp_path, monkeypatch):
        got = self._run(tmp_path, monkeypatch,
                        "/api/health -> 500\nKeyError: 'SECRET_KEY'")
        assert not got["issue"].startswith("【")
        assert "【本轮唯一优先目标】" not in got["issue"]
