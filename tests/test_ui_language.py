# -*- coding: utf-8 -*-
"""UI 语言一致性审计（9/22 stackoverflow 中文 UI 取证回归）。"""
from pathlib import Path

from app.utils.ui_language import (
    audit_ui_language,
    requirement_language,
)

EN_REQ = ("Web-based question and answer platform for developers. " * 12)
CN_REQ = "面向开发者的问答平台，支持提问、回答、搜索与声望体系。" * 12


def test_requirement_language_detection():
    assert requirement_language(EN_REQ) == "latin"
    assert requirement_language(CN_REQ) == "cjk"
    assert requirement_language("short") == "unknown"


def test_chinese_ui_flagged_for_english_requirement(tmp_path: Path):
    code = tmp_path / "code" / "home"
    code.mkdir(parents=True)
    (tmp_path / "code" / "home" / "home.py").write_text(
        'NAV = "知识问答平台"\nLINK = "首页"\n', encoding="utf-8")
    findings = audit_ui_language(tmp_path / "code", EN_REQ)
    assert findings and "home/home.py" in findings[0]
    assert "英文" in findings[0]


def test_chinese_comments_not_flagged(tmp_path: Path):
    code = tmp_path / "code"
    code.mkdir(parents=True)
    (code / "app_mod.py").write_text(
        '# 中文注释合法（管线提示词语言所致）\n'
        'NAV = "Question List"\n',
        encoding="utf-8")
    assert audit_ui_language(code, EN_REQ) == []


def test_english_ui_silent(tmp_path: Path):
    code = tmp_path / "code"
    code.mkdir(parents=True)
    (code / "home.py").write_text('NAV = "Q&A Platform"\n', encoding="utf-8")
    assert audit_ui_language(code, EN_REQ) == []


def test_cjk_requirement_not_force_latin(tmp_path: Path):
    code = tmp_path / "code"
    code.mkdir(parents=True)
    (code / "home.py").write_text('NAV = "问答平台"\n', encoding="utf-8")
    assert audit_ui_language(code, CN_REQ) == []
