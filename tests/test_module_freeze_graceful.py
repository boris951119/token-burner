# -*- coding: utf-8 -*-
"""模块级容错（generation-2 取证：单模块 LLM 全灭崩穿管线，143 需求
2 小时归零）——单模块开发异常必须冻结该模块、继续其余模块。"""

from __future__ import annotations

import pytest

from tests.test_feedback_loop import (
    ScriptedFeedback,
    _RUN_KWARGS,
    _SIMPLE_FIX,
    _team_pipeline,
    fm,
)
from tests.test_pipeline import team_scripts


class TestModuleFreezeGraceful:
    def test_module_exception_freezes_and_continues(self, fm, monkeypatch):
        """第一个模块开发抛异常 → 冻结该模块，其余模块照常完成，
        管线正常交付（部分交付 > 崩穿归零）。"""
        from app.agents.dev_loop import DevLoopEngine

        scripts = team_scripts()
        pipeline = _team_pipeline(fm, scripts + [_SIMPLE_FIX, _SIMPLE_FIX],
                                  ["SKIPPED"] * 3)
        original = DevLoopEngine.run_module
        calls = {"n": 0}

        def flaky_run_module(self, module, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                from app.agents.dev_loop import ModelChainExhausted
                raise ModelChainExhausted(
                    "模型级全链失败（openai/minimax-m3 → "
                    "openai/deepseek-v4-pro → openai/glm-5.3）")
            return original(self, module, **kwargs)

        monkeypatch.setattr(DevLoopEngine, "run_module", flaky_run_module)
        feedback = ScriptedFeedback(["运行成功，输出符合预期"])
        result = pipeline.run(feedback_fn=feedback, **_RUN_KWARGS)
        assert result.kind == "team_flow"
        assert calls["n"] >= 2, "异常后必须继续其余模块"

    def test_all_modules_failing_still_clean_result(self, fm, monkeypatch):
        """全部模块异常 → 干净的失败终态（不是异常崩穿）。"""
        from app.agents.dev_loop import DevLoopEngine

        pipeline = _team_pipeline(fm, team_scripts(), ["SKIPPED"] * 3)

        def always_fail(self, module, **kwargs):
            from app.agents.dev_loop import ModelChainExhausted
            raise ModelChainExhausted("模型级全链失败")

        monkeypatch.setattr(DevLoopEngine, "run_module", always_fail)
        feedback = ScriptedFeedback(["运行成功，输出符合预期"])
        result = pipeline.run(feedback_fn=feedback, **_RUN_KWARGS)
        assert result.kind in ("team_flow", "budget_exceeded"), (
            "必须返回结构化终态而非异常抛出")
