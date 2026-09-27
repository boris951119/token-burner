# -*- coding: utf-8 -*-
"""v52 通气：peer 注入 + schema 权威摘要。"""
from __future__ import annotations

from app.agents.dev_loop import DevLoopEngine
from app.config import Settings
from app.tools.file_manager import FileManager
from app.utils.schema_audit import format_schema_authority


class _NoLLM:
    def chat(self, *a, **k):
        raise AssertionError("no llm")


class _NoExec:
    def run(self, *a, **k):
        raise AssertionError("no exec")


def test_prompt_includes_peer_and_schema(tmp_path):
    fm = FileManager(projects_root=tmp_path / "projects")
    eng = DevLoopEngine(
        llm=_NoLLM(), dev_model="m1", test_model="m2",
        executor=_NoExec(), settings=Settings(models=["m1", "m2", "m3"]),
        file_manager=fm, main_model="m3",
    )
    eng.peer_exports_summary = "## 本项目模块清单\n- a, b"
    eng.schema_authority_summary = "- users(id, name)"
    out = eng._prompt_with_shared("BODY")
    assert "本项目模块清单" in out and "users(id, name)" in out
    assert out.index("BODY") < out.index("本项目模块清单")


def test_format_schema_authority(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "seed.py").write_text(
        '''DDL = """CREATE TABLE IF NOT EXISTS users (id INTEGER, name TEXT);"""\n''',
        encoding="utf-8",
    )
    text = format_schema_authority(code)
    assert "users" in text and "id" in text and "name" in text
