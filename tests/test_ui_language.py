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


# ---- 精度与覆盖面（9/23 交付取证）-------------------------------------
# 旧实现两处偏差：① 文档字符串算违规——导出的官方 runner 入口模板自带
# 中文 docstring，于是每个英文需求的交付都凭空多一个"违规文件"，而这条
# 审计在修复指令里标着「最高优先级」；② 只扫 .py/.html，界面文案一旦
# 只活在 home.js 的模板串里就直接放行。

def test_docstring_only_chinese_is_not_a_violation(tmp_path: Path):
    code = tmp_path / "code"
    (code / "runner").mkdir(parents=True)
    (code / "runner" / "main.py").write_text(
        '"""官方 runner 启动入口：PORT 环境变量，/api/health 就绪。"""\n'
        'PORT = 3301\n', encoding="utf-8")
    assert audit_ui_language(code, EN_REQ) == []


def test_chinese_ui_text_in_js_is_caught(tmp_path: Path):
    code = tmp_path / "code"
    (code / "static").mkdir(parents=True)
    (code / "static" / "home.js").write_text(
        "const nav = '<span>提醒事项</span>';\n", encoding="utf-8")
    findings = audit_ui_language(code, EN_REQ)
    assert findings and "static/home.js" in findings[0]
    # 违规片段直接给出，修复环才看得见是哪一处（旧版只报文件名）
    assert "提醒事项" in findings[0]


def test_js_and_html_comments_are_not_ui_text(tmp_path: Path):
    code = tmp_path / "code"
    code.mkdir(parents=True)
    (code / "app.js").write_text(
        "/* 中文块注释合法 */\n// 行注释也合法\nconst t = 'Reminders';\n",
        encoding="utf-8")
    (code / "index.html").write_text(
        "<!-- 中文注释不算界面文案 --><p>Reminders</p>", encoding="utf-8")
    assert audit_ui_language(code, EN_REQ) == []


def test_vendor_assets_are_not_scanned(tmp_path: Path):
    code = tmp_path / "code"
    (code / "node_modules" / "lib").mkdir(parents=True)
    (code / "node_modules" / "lib" / "vendor.js").write_text(
        "const x = '第三方库里的中文';\n", encoding="utf-8")
    assert audit_ui_language(code, EN_REQ) == []
