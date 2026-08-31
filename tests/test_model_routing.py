"""智能模型路由测试（M3-1 三档分层 / M3-2 评估后动态选模）。

验收锚点（v0.4.md M3）：
- 路由规则：难度 1-3 全轻量、4-6 主力+轻量混合（主 LLM 主力档、
  副评审轻量档）、7-10 全旗舰；
- 档位为空 / 候选占用时向上回退，三模型始终互异且均在预设列表；
- 用户显式选择 > 智能路由 > v0.3.1 缺省（model_routing_enabled
  关闭时行为与 v0.3.1 完全一致）。
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.orchestrator import route_models
from app.pipeline import Pipeline


def _no_dup(models: tuple[str, str, str]) -> bool:
    return len(set(models)) == 3


class TestRouteModels:
    def test_all_models_valid_and_distinct(self):
        settings = Settings(model_routing_enabled=True)
        for score in range(0, 11):
            models = route_models(score, settings)
            assert _no_dup(models), f"难度 {score} 三模型不互异: {models}"
            for m in models:
                assert m in settings.models

    def test_default_presets_high_difficulty_prefers_flagship(self):
        settings = Settings(model_routing_enabled=True)
        # 默认预设：旗舰=[gpt-4o, gemini-1.5-pro] 主力=[claude-3-5-sonnet, deepseek-chat]
        models = route_models(9, settings)
        assert models[0] in ("gpt-4o", "gemini-1.5-pro")  # 主 LLM 旗舰档
        assert set(models) <= set(settings.models)  # 旗舰不足回退，不出预设
        assert _no_dup(models)

    def test_default_presets_mid_difficulty_uses_main_tier_lead(self):
        settings = Settings(model_routing_enabled=True)
        models = route_models(5, settings)
        assert models[0] in ("claude-3-5-sonnet", "deepseek-chat")  # 主 LLM 主力档

    def test_light_tier_used_for_mid_difficulty_reviews(self):
        settings = Settings(
            model_routing_enabled=True,
            models=["gpt-4o", "claude-3-5-sonnet", "deepseek-chat", "deepseek-lite"],
            model_tier_flagship=["gpt-4o"],
            model_tier_main=["claude-3-5-sonnet", "deepseek-chat"],
            model_tier_light=["deepseek-lite"],
        )
        models = route_models(5, settings)
        # 主力+轻量混合：主 LLM 主力档、副 LLM 轻量档优先
        assert models[0] in ("claude-3-5-sonnet", "deepseek-chat")
        assert "deepseek-lite" in models
        assert _no_dup(models)

    def test_light_tier_for_low_difficulty(self):
        settings = Settings(
            model_routing_enabled=True,
            models=["gpt-4o", "deepseek-lite", "claude-3-5-sonnet"],
            model_tier_flagship=["gpt-4o"],
            model_tier_main=["claude-3-5-sonnet"],
            model_tier_light=["deepseek-lite"],
        )
        assert route_models(2, settings) == ("deepseek-lite", "claude-3-5-sonnet", "gpt-4o")

    def test_single_tier_fallback_keeps_distinct(self):
        # 三档只配一个模型 → 逐角色回退到不同档位，保持互异
        settings = Settings(
            model_routing_enabled=True,
            models=["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
            model_tier_flagship=["gpt-4o"],
            model_tier_main=["deepseek-chat"],
            model_tier_light=["claude-3-5-sonnet"],
        )
        for score in (1, 5, 9):
            models = route_models(score, settings)
            assert _no_dup(models)
        assert route_models(9, settings)[0] == "gpt-4o"  # 高难度主 LLM 旗舰

    def test_tier_models_not_in_presets_filtered_out(self):
        # 运行时过滤兜底：构造后档位漂移（如用户改了 models 列表）不致崩溃。
        # 构造期校验由 TestConfigValidation 覆盖。
        settings = Settings(
            model_routing_enabled=True,
            models=["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
            model_tier_flagship=["gpt-4o"],
            model_tier_main=["claude-3-5-sonnet", "deepseek-chat"],
        )
        settings.model_tier_light = ["ghost-model"]  # 模拟漂移
        models = route_models(5, settings)
        assert _no_dup(models)
        assert "ghost-model" not in models


class TestConfigValidation:
    def test_routing_enabled_unknown_tier_model_rejected(self):
        with pytest.raises(ValueError, match="未登记模型"):
            Settings(
                model_routing_enabled=True,
                model_tier_light=["nonexistent-model"],
            )

    def test_routing_disabled_tolerates_stale_tiers(self):
        # 路由关闭：档位即使指向未登记模型也不阻断启动（行为与旧版一致）
        Settings(model_tier_light=["nonexistent-model"])


class TestPipelineResolveModels:
    def _pipeline(self, settings: Settings) -> Pipeline:
        return Pipeline(
            llm=object(), executor=None, settings=settings,
            file_manager=None,
        )

    def _route(self, score: int):
        from app.orchestrator import Route, RoutingResult

        return RoutingResult(
            route=Route.TEAM_FLOW, task_type="编程",
            difficulty_score=score, difficulty_level="中等", reason="r",
        )

    def test_explicit_models_win_over_routing(self):
        settings = Settings(model_routing_enabled=True)
        p = self._pipeline(settings)
        assert p._resolve_models(self._route(9), ("a", "b", "c")) == ("a", "b", "c")

    def test_routing_disabled_default_triple(self):
        p = self._pipeline(Settings())
        assert p._resolve_models(self._route(9), None) == \
            ("gpt-4o", "deepseek-chat", "claude-3-5-sonnet")

    def test_routing_enabled_selects_by_difficulty(self):
        settings = Settings(
            model_routing_enabled=True,
            models=["gpt-4o", "claude-3-5-sonnet", "deepseek-chat", "deepseek-lite"],
            model_tier_flagship=["gpt-4o"],
            model_tier_main=["claude-3-5-sonnet", "deepseek-chat"],
            model_tier_light=["deepseek-lite"],
        )
        p = self._pipeline(settings)
        models = p._resolve_models(self._route(5), None)
        assert models[0] in ("claude-3-5-sonnet", "deepseek-chat")
        assert "deepseek-lite" in models
