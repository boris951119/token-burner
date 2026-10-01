# -*- coding: utf-8 -*-
"""全局意图回流：spec_digest 确定性摘要 + 写码提示挂槽。"""
from __future__ import annotations

import sys

from app.utils.agent_tools import spec_digest


def test_short_spec_passes_through():
    assert spec_digest("# 计划\n做 A") == "# 计划\n做 A"


def test_empty_spec_returns_empty():
    assert spec_digest("") == ""
    assert spec_digest(None) == ""


def test_long_spec_head_tail_clamp_with_skeleton():
    body = ("# 总体设计\n" + "正文" * 2000 + "\n## 尾部章节\n" + "结尾" * 500)
    d = spec_digest(body, head=1800, tail=400)
    assert len(d) <= 1800 + 400 + 120          # 夹逼上限（含标注行）
    assert d.startswith("# 总体设计")           # 骨架标题先行
    assert "(正文开头)" in d and "(正文结尾)" in d
    assert d.rstrip().endswith("结尾" * 10)      # 尾部保留


def test_skeleton_covers_section_titles():
    body = ("# 总体设计\nx" * 3000 + "\n## 模块甲\ny\n## 模块乙\nz")
    d = spec_digest(body)
    assert "## 模块甲" in d and "## 模块乙" in d   # 结构标题不丢


def test_dev_loop_prompt_carries_spec_summary(tmp_path):
    """挂槽回归：spec_summary 非空时出现在写码提示。"""
    import importlib.util
    from pathlib import Path as _P
    spec = importlib.util.spec_from_file_location(
        "dl_test", _P("/Users/liuboyu/Developer/token-burner/app/agents/dev_loop.py"))
    dl = importlib.util.module_from_spec(spec)
    sys.modules["dl_test"] = dl
    try:
        spec.loader.exec_module(dl)
        eng = dl.DevLoopEngine.__new__(dl.DevLoopEngine)
        eng.peer_exports_summary = ""
        eng.schema_authority_summary = ""
        eng.skills_summary = ""
        eng.spec_summary = "全局：三层架构，统一英文 UI"
        eng.research_context = ""
        eng._shared_ctx_cache = ""
        eng._active_project_id = None
        out = eng._prompt_with_shared("写一个模块")
        assert "全局设计意图" in out and "三层架构" in out
        # 空摘要零变化
        eng.spec_summary = ""
        out2 = eng._prompt_with_shared("写一个模块")
        assert "全局设计意图" not in out2
    finally:
        sys.modules.pop("dl_test", None)
