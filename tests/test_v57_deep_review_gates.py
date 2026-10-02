# -*- coding: utf-8 -*-
"""深审 1–3：probe-fast 不得跳过 schema/完整验收；账户止损进修复；
single 假升级关掉 + 早冻。"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_probe_fast_guards_include_schema_drift(tmp_path):
    from app.arcbench_smoke import probe_fast_guard_issues

    code = tmp_path / "code"
    code.mkdir()
    (code / "db.py").write_text(
        "CREATE TABLE users (id INTEGER)\n"
        'cur.execute("INSERT INTO users (id, created_at) VALUES (?, ?)")\n',
        encoding="utf-8",
    )
    issues = probe_fast_guard_issues(code, "Users sign in.")
    assert any("[schema]" in x for x in issues), issues


def test_verify_delivery_probe_green_does_not_early_return_true():
    """静态防回归：守卫全绿也不得 return True 跳过自测。"""
    src = (ROOT / "app" / "arcbench_smoke.py").read_text(encoding="utf-8")
    assert "return True, msg" not in src
    assert "入口修补后强制完整验收" in src
    assert "冷库终检/[schema]/自测不得跳过" in src


def test_main_no_force_stage3_on_probe_fast():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'print("[probe-fast] 入口修补超时，强制交' not in src
    assert "自测不跳过" in src


def test_auto_repair_llm_raises_on_account_fatal(monkeypatch, tmp_path):
    from app.utils.selftest_gate import LLMAccountError
    import app.arcbench_smoke as smoke
    import app.utils.model_client as mcmod

    code = tmp_path / "code"
    code.mkdir()
    (code / "main.py").write_text("app = None\n", encoding="utf-8")

    class _S:
        models = ["openai/glm-5.3-flash"]

    class _MC:
        def __init__(self, settings):
            pass

        def chat(self, model, messages):
            raise RuntimeError(
                "LLM 调用失败: Error code: 402 - insufficient balance")

    monkeypatch.setattr(mcmod, "ModelClient", _MC)
    monkeypatch.setattr(
        smoke, "run_smoke",
        lambda *_a, **_k: (False, "GET / -> 500"),
    )

    with pytest.raises(LLMAccountError):
        smoke.auto_repair(tmp_path, _S(), max_rounds=1)


def test_single_roster_skips_fake_upgrade(monkeypatch, capsys, tmp_path):
    from app.agents.dev_loop import DevLoopEngine
    from app.config import Settings
    from app.tools.file_manager import FileManager
    from tests.test_dev_loop import FakeExecutor, ScriptedLLM

    settings = Settings(models=["openai/glm-5.3-flash"], max_fix_rounds=5)
    settings.projects_root = tmp_path
    llm = ScriptedLLM(["x = 9\n"])
    engine = DevLoopEngine(
        llm=llm, dev_model="openai/glm-5.3-flash",
        test_model="openai/glm-5.3-flash",
        main_model="openai/glm-5.3-flash",
        executor=FakeExecutor([]),
        settings=settings,
        file_manager=FileManager(projects_root=tmp_path),
    )
    engine._last_code_model = "openai/glm-5.3-flash"
    assert engine._single_roster() is True
    assert engine._fix_cap() == 2
    engine._fix_code("m", "x = 1\n", "T", "boom", fix_attempts=3)
    out = capsys.readouterr().out
    assert "single 编队跳过修复升级" in out
    assert "修复升级 →" not in out
    assert llm.calls[0]["model"] == "openai/glm-5.3-flash"


def test_multi_exhausted_skips_fake_upgrade_to_failed(monkeypatch, capsys, tmp_path):
    """三腿全在排除集时不得再打印「修复升级 → 主帅」空转。"""
    import app.utils.model_ledger as ledger
    from app.agents.dev_loop import DevLoopEngine
    from app.config import Settings
    from app.tools.file_manager import FileManager
    from tests.test_dev_loop import FakeExecutor, ScriptedLLM

    monkeypatch.setattr(
        ledger, "recommend",
        lambda task_type, exclude=(), min_attempts=0: [])
    settings = Settings(
        models=["m_flash", "m_pro", "m_q"], max_fix_rounds=5)
    settings.projects_root = tmp_path
    llm = ScriptedLLM(["x = 9\n"])
    engine = DevLoopEngine(
        llm=llm, dev_model="m_flash", test_model="m_q",
        main_model="m_flash", executor=FakeExecutor([]),
        settings=settings,
        file_manager=FileManager(projects_root=tmp_path),
    )
    engine._last_code_model = "m_flash"
    engine._repair_failed_models = {"m_pro", "m_q"}
    engine._fix_code("m", "x = 1\n", "T", "boom", fix_attempts=3)
    out = capsys.readouterr().out
    assert "修复备胎耗尽" in out
    assert "修复升级 →" not in out
