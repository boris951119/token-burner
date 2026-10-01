# -*- coding: utf-8 -*-
"""workflow_mode（用户功能）：auto 零变化 / single 单模型档 / multi 显式编队。"""
from __future__ import annotations

import pytest

from app.config import Settings, apply_workflow_mode


def _settings(models, mode="auto"):
    s = Settings.__new__(Settings)
    s.models = list(models)
    s.workflow_mode = mode
    s.single_model_mode = len(set(models)) < 3
    return s


def test_auto_is_zero_change():
    s = _settings(["a", "b", "c"])
    out = apply_workflow_mode(s)
    assert out.models == ["a", "b", "c"]
    assert out.single_model_mode is False


def test_single_collapses_to_first_model():
    s = _settings(["pro", "flash", "qwen"], mode="single")
    out = apply_workflow_mode(s)
    assert out.models == ["pro"]                    # 平台单模型形态（单元素）
    assert out.single_model_mode is True            # 三角色由 _model_triplet 补位


def test_single_with_platform_injected_one_model_kept():
    """平台注入 MODEL 后只有 1 模型：single 保形不报错。"""
    s = _settings(["flash"], mode="single")
    out = apply_workflow_mode(s)
    assert out.models == ["flash"]


def test_multi_requires_three_distinct():
    s = _settings(["a", "a", "b"], mode="multi")
    with pytest.raises(ValueError, match="3 个互异"):
        apply_workflow_mode(s)
    ok = apply_workflow_mode(_settings(["a", "b", "c", "d"], mode="multi"))
    assert ok.models == ["a", "b", "c"]              # 取前三


def test_invalid_mode_raises_at_startup():
    with pytest.raises(ValueError, match="非法"):
        apply_workflow_mode(_settings(["a"], mode="turbo"))


def test_single_shot_discussion_bypasses_review_rounds():
    """single 档讨论=单发 spec：0 评审轮，一次出稿直接返回。"""
    import sys
    from pathlib import Path
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "orch_test", Path("/Users/liuboyu/Developer/token-burner/app/orchestrator.py"))
    orch = importlib.util.module_from_spec(spec)
    sys.modules["orch_test"] = orch
    try:
        spec.loader.exec_module(orch)
        calls = []

        class FakeEngine(orch.DiscussionEngine):
            def __init__(self):
                pass  # 绕过基类构造（只测 run_discussion 的 single 分支）

            def _chat(self, model, messages):
                calls.append((model, messages[0]["content"]))
                return "# SPEC\n- 模块甲"

            def _record_message(self, *a, **k):
                pass

            def _persist_discussion(self, pid, outcome):
                self._saved = outcome

            def _clock(self):
                return 0.0

        eng = FakeEngine()
        eng.main_model = "m1"
        eng.settings = _settings(["m1"], mode="single")
        eng.project_id = "p1"
        out = eng.run_discussion("做个表格应用")
        assert len(calls) == 1                          # 单发：只有一次 LLM 调用
        assert out.rounds_completed == 0 and out.converged
        assert out.spec_md.startswith("# SPEC")
        assert "single" in out.discussion_summary
    finally:
        sys.modules.pop("orch_test", None)
