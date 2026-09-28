# -*- coding: utf-8 -*-
"""锚点覆盖硬门禁回归（平台 v6 取证：0/32 全挂——带引号文案被翻译，
评测逐字断言落空；旧管线冒烟一过锚点信息永不出口）。"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import app.arcbench_smoke as sm
from app.config import Settings


def _write(p, s):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8", newline="\n")


_APP = '''\
from flask import Blueprint, Flask, jsonify

bp = Blueprint("app", __name__)


@bp.route("/api/health")
def health():
    return jsonify(status="ok")


@bp.route("/")
def home():
    return '<div class="create-note">Take a note</div><div>Sprint goals</div>'


def create_app():
    app = Flask(__name__)
    app.register_blueprint(bp)
    return app
'''

_REQ = '''
# REQ-1 Home
Display a "Take a note" form. Seed data: pinned note "Sprint goals".

# REQ-2 Labels
Provide "Reminders" as a default label.
'''


class TestAnchorMissing:
    def test_missing_reported_against_real_shape(self, tmp_path):
        """页面含 'Take a note'/'Sprint goals' → 不缺；'Reminders' 缺。"""
        code = tmp_path / "code"
        _write(code / "app_mod" / "__init__.py",
               "from app_mod.app_mod import *  # noqa: F401,F403\n")
        _write(code / "app_mod" / "app_mod.py", _APP)
        missing = sm._anchor_missing(code, _REQ)
        assert any("Reminders" in m for m in missing), missing
        assert not any("Take a note" in m for m in missing), missing
        assert not any("Sprint goals" in m for m in missing), missing

    def test_translated_ui_detected(self, tmp_path):
        """中文改写英文锚点 = 缺失（平台 v6 根因形态）。"""
        code = tmp_path / "code"
        translated = _APP.replace("Take a note", "记笔记")
        _write(code / "app_mod" / "__init__.py",
               "from app_mod.app_mod import *  # noqa: F401,F403\n")
        _write(code / "app_mod" / "app_mod.py", translated)
        missing = sm._anchor_missing(code, _REQ)
        assert any("Take a note" in m for m in missing), missing

    def test_probe_failure_returns_empty(self, tmp_path):
        """探针自身故障不得冤枉应用（宁漏不误）。"""
        assert sm._anchor_missing(tmp_path, "无引号需求") == []
        bad = tmp_path / "code"
        _write(bad / "x.py", "syntax error(")
        assert sm._anchor_missing(bad, _REQ) == []


class TestAnchorGateInVerify:
    def _settings(self):
        return Settings(models=["openai/glm-5.3",
                                "openai/deepseek-v4-pro",
                                "openai/minimax-m3"])

    def test_anchor_missing_triggers_repair_then_pass(self, tmp_path,
                                                      monkeypatch):
        """缺失 → auto_repair（extra_issue 主体 + 锚点门禁探针 test_cmd）
        出牌 → 复探通过 → 进旅程。"""
        (tmp_path / "code").mkdir()
        calls = {"anchor": 0}

        monkeypatch.setattr(sm, "run_smoke",
                            lambda cd: (True, "smoke ok"))
        monkeypatch.setattr(sm, "_anchor_missing",
                            lambda cd, req: (calls.setdefault("m", ["Reminders"]))
                            if calls["anchor"] == 0 and calls.update(
                                anchor=calls["anchor"] + 1) is None
                            else [])
        monkeypatch.setattr(sm, "_beat", lambda *a, **k: None)
        monkeypatch.setattr(sm, "_llm_from",
                            lambda s: (lambda sys_, usr: "ok"))
        monkeypatch.setattr(sm, "_journey_gate",
                            lambda *a, **k: (True, "journey ok"))

        def fake_repair(project_dir, settings, max_rounds=3, **kw):
            assert "Reminders" in kw.get("extra_issue", ""), \
                "锚点缺口必须以 extra_issue 主体传入修复通道"
            assert kw.get("test_cmd"), \
                "修复循环必须用锚点门禁探针做验证信号（冒烟对缺口零感知）"
            return True, "补齐文案"

        monkeypatch.setattr(sm, "auto_repair", fake_repair)

        ok, report = sm.verify_delivery(tmp_path, _REQ, self._settings())
        assert ok, report
        assert "[anchor] 缺失" in report and "[anchor] PASS" in report

    def test_anchor_unfixed_still_delivers(self, tmp_path, monkeypatch):
        """修不齐**不拦交付**（平台 Keep 实跑取证：硬闸把 6 小时生成
        整跑打成 0）——WARN 留痕，旅程照走，最终 PASS。"""
        (tmp_path / "code").mkdir()
        monkeypatch.setattr(sm, "run_smoke",
                            lambda cd: (True, "smoke ok"))
        monkeypatch.setattr(sm, "_anchor_missing",
                            lambda cd, req: ["Reminders"])
        monkeypatch.setattr(sm, "_beat", lambda *a, **k: None)
        monkeypatch.setattr(sm, "auto_repair",
                            lambda *a, **k: (False, "修不动"))
        journey_called = {"n": 0}
        monkeypatch.setattr(sm, "_journey_gate",
                            lambda *a, **k: journey_called.update(
                                n=journey_called["n"] + 1) or (True, ""))

        ok, report = sm.verify_delivery(tmp_path, _REQ, self._settings(),
                                        max_verify_rounds=2)
        assert ok, "锚点未全对齐只能 WARN，不得把交付闸死"
        assert "[anchor] WARN" in report
        assert journey_called["n"] >= 1, "放行进旅程"


class TestAutoRepairExtraIssue:
    def test_extra_issue_bypasses_smoke_early_return(self, tmp_path,
                                                      monkeypatch):
        """extra_issue 场景冒烟通过也不早退，指令即主体进 RepoFixer。"""
        (tmp_path / "code").mkdir()
        monkeypatch.setattr(sm, "run_smoke",
                            lambda cd: (True, "smoke ok"))

        captured = {}

        class _Fixer:
            def __init__(self, llm, project_dir, test_cmd=None,
                         max_rounds=3, stop_check=None,
                         baseline_test_cmd=None):
                pass

            def fix(self, issue):
                captured["issue"] = issue
                import types
                return types.SimpleNamespace(ok=True, rounds=1)

        monkeypatch.setattr("app.agents.repo_fixer.RepoFixer", _Fixer)
        monkeypatch.setattr(
            sm, "run_smoke", lambda cd: (True, "smoke ok"))

        class _MC:
            def __init__(self, settings):
                pass

            def chat(self, model, messages):
                class _R:
                    content = "补齐"
                return _R()

        monkeypatch.setattr("app.utils.model_client.ModelClient", _MC)

        ok, report = sm.auto_repair(
            tmp_path, Settings(models=["openai/glm-5.3"]), max_rounds=1,
            extra_issue="锚点缺失: 'Reminders' 需逐字补齐")
        assert ok
        assert "Reminders" in captured["issue"], \
            "extra_issue 必须成为修复指令主体"


class TestVisibleTextAntiGaming:
    """平台 v6-3 取证：LLM 把锚点串塞进 hidden textarea 骗过子串
    匹配——锚点探针必须基于渲染可见文本判定。"""

    def test_hidden_textarea_stuffing_defeated(self, tmp_path):
        code = tmp_path / "code"
        # 占位壳页：锚点串全在 hidden textarea 里，页面上没有
        _write(code / "app_mod" / "__init__.py",
               "from app_mod.app_mod import *  # noqa: F401,F403\n")
        _write(code / "app_mod" / "app_mod.py",
               'from flask import Flask, jsonify\n'
               'def create_app():\n'
               '    app = Flask(__name__)\n'
               '    @app.route("/api/health")\n'
               '    def health():\n'
               '        return jsonify(status="ok")\n'
               '    @app.route("/")\n'
               '    def home():\n'
               '        return (\'<textarea hidden>Take a note\\n'
               'Sprint goals\\nReminders</textarea>\'\n'
               '                 \'<h1>System is running.</h1>\')\n'
               '    return app\n')
        missing = sm._anchor_missing(code, _REQ)
        assert any("Take a note" in m for m in missing), \
            "隐藏 textarea 塞串必须被判为缺失"
        assert any("Sprint goals" in m for m in missing), missing

    def test_visible_copy_still_counts(self, tmp_path):
        code = tmp_path / "code"
        _write(code / "app_mod" / "__init__.py",
               "from app_mod.app_mod import *  # noqa: F401,F403\n")
        _write(code / "app_mod" / "app_mod.py",
               'from flask import Flask, jsonify\n'
               'def create_app():\n'
               '    app = Flask(__name__)\n'
               '    @app.route("/api/health")\n'
               '    def health():\n'
               '        return jsonify(status="ok")\n'
               '    @app.route("/")\n'
               '    def home():\n'
               '        return \'<input placeholder="Take a note">\' \\n'
               '               \'<div>Sprint goals</div>\'\n'
               '    return app\n')
        missing = sm._anchor_missing(code, _REQ)
        assert not any("Take a note" in m for m in missing), missing
        assert not any("Sprint goals" in m for m in missing), missing
