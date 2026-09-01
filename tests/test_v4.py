"""V4 批次测试：M12-6 自定义路由策略（分档阈值进 config）。

规格（v0.5.md M12-6，原 M3-4）：各阶段模型档位与阈值可配置——
- route_models 的分档阈值 7/4 从 orchestrator 硬编码迁移到
  Settings.route_flagship_threshold / route_main_threshold；
- 默认值 7/4 保持 v0.4 行为完全不变；
- config.json 覆盖后路由按自定义规则分发（验收标准）；
- 非法阈值（旗舰阈值 ≤ 主力阈值、越界）尽早失败。
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.orchestrator import route_models

from pathlib import Path  # noqa: E402  （契约测试读取 client.html 用）


def _tier_settings(**overrides) -> Settings:
    """三档各一模型的可观测配置（路由结果与档位一一对应）。"""
    base = dict(
        models=["flag1", "main1", "light1"],
        model_tier_flagship=["flag1"],
        model_tier_main=["main1"],
        model_tier_light=["light1"],
        model_routing_enabled=True,
    )
    base.update(overrides)
    return Settings(**base)


class TestDefaultThresholdsUnchanged:
    """默认阈值 7/4：v0.4 行为不变（回归保护）。"""

    def test_score_7_full_flagship(self):
        s = _tier_settings()
        assert route_models(7, s) == ("flag1", "main1", "light1")

    def test_score_6_mixed(self):
        s = _tier_settings()
        # 主 LLM 主力档，副评审轻量档，测试副回退旗舰
        assert route_models(6, s) == ("main1", "light1", "flag1")

    def test_score_4_mixed(self):
        s = _tier_settings()
        assert route_models(4, s) == ("main1", "light1", "flag1")

    def test_score_3_all_light(self):
        s = _tier_settings()
        assert route_models(3, s) == ("light1", "main1", "flag1")


class TestCustomThresholds:
    """config 自定义阈值后路由按自定义规则分发（M12-6 验收标准）。"""

    def test_custom_thresholds_change_routing(self):
        # 旗舰阈值 7→9、主力阈值 4→2：难度 8 从全旗舰降为混合档
        s = _tier_settings(route_flagship_threshold=9, route_main_threshold=2)
        assert route_models(8, s) == ("main1", "light1", "flag1")   # 原 7 会全旗舰

    def test_custom_main_threshold_expands_light_band(self):
        # 主力阈值 4→6：难度 5 从混合档落入全轻量带？否——5 < 6 → 轻量带
        s = _tier_settings(route_flagship_threshold=9, route_main_threshold=6)
        assert route_models(5, s) == ("light1", "main1", "flag1")

    def test_boundary_scores_respect_custom_thresholds(self):
        s = _tier_settings(route_flagship_threshold=9, route_main_threshold=2)
        assert route_models(9, s) == ("flag1", "main1", "light1")   # 恰达旗舰阈值
        assert route_models(2, s) == ("main1", "light1", "flag1")   # 恰达主力阈值

    def test_config_json_override_reaches_routing(self):
        """load_settings 经 config.json 覆盖阈值后路由生效（端到端）。"""
        import json as _json
        import tempfile
        from pathlib import Path

        from app.config import load_settings

        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text(_json.dumps({
                "route_flagship_threshold": 10,
                "route_main_threshold": 1,
            }), encoding="utf-8")
            s = load_settings(config_file=cfg)
            assert s.route_flagship_threshold == 10
            assert s.route_main_threshold == 1


class TestInvalidThresholds:
    """非法阈值尽早失败（确定性校验）。"""

    def test_flagship_not_greater_than_main_rejected(self):
        with pytest.raises(ValueError, match="route_main_threshold"):
            _tier_settings(route_flagship_threshold=4, route_main_threshold=4)

    def test_negative_rejected(self):
        with pytest.raises(ValueError, match="route_main_threshold"):
            _tier_settings(route_main_threshold=-1)

    def test_flagship_above_ten_rejected(self):
        with pytest.raises(ValueError, match="route_flagship_threshold"):
            _tier_settings(route_flagship_threshold=11)


# ---------------------------------------------------------------------------
# M12-9：模型路由明细（call_log 档位标注 + 旗舰假设成本）
# ---------------------------------------------------------------------------

from app.dashboard.cost_dashboard import CostDashboard  # noqa: E402
from app.orchestrator import tier_map  # noqa: E402


def _log_entry(model: str, inp: int, out: int, hint: str = "需求评估专家") -> dict:
    return {"model": model, "system_hint": hint,
            "input_tokens": inp, "output_tokens": out}


class TestTierMap:
    def test_three_tiers_mapped(self):
        s = _tier_settings()
        assert tier_map(s) == {
            "flag1": "旗舰", "main1": "主力", "light1": "轻量",
        }

    def test_cross_tier_duplicate_flagship_wins(self):
        s = _tier_settings(model_tier_main=["main1", "flag1"])
        assert tier_map(s)["flag1"] == "旗舰"   # 旗舰先登记，setdefault 保护
        assert tier_map(s)["main1"] == "主力"

    def test_unregistered_model_absent(self):
        assert "mystery" not in tier_map(_tier_settings())


class TestDashboardTierAndCosts:
    def test_from_call_log_annotates_tier(self):
        s = _tier_settings()
        d = CostDashboard.from_call_log(
            [_log_entry("flag1", 100, 50), _log_entry("main1", 200, 80)],
            budget_tokens=1000,
            tier_map=tier_map(s),
        )
        assert [r.tier for r in d.records] == ["旗舰", "主力"]

    def test_by_tier_aggregates_with_unknown_bucket(self):
        s = _tier_settings()
        d = CostDashboard.from_call_log(
            [_log_entry("flag1", 100, 50), _log_entry("mystery", 10, 5)],
            budget_tokens=1000,
            tier_map=tier_map(s),
        )
        assert d.by_tier() == {"旗舰": 150, "未登记": 15}

    def test_routing_costs_numbers(self):
        d = CostDashboard(budget_tokens=1000)
        d.record("cheap", "评估", 1_000_000, 1_000_000, tier="轻量")
        d.record("flag1", "开发", 1_000_000, 0, tier="旗舰")
        costs = d.routing_costs(
            prices={
                "cheap": {"input": 1.0, "output": 2.0},
                "flag1": {"input": 10.0, "output": 20.0},
            },
            flagship_price={"input": 10.0, "output": 20.0},
        )
        # 实际 = (1M×1 + 1M×2)/1e6 + (1M×10 + 0)/1e6 = 3 + 10 = 13
        assert costs["available"] is True
        assert costs["actual_cost_usd"] == pytest.approx(13.0)
        # 假设 = (1M×10 + 1M×20)/1e6 + (1M×10)/1e6 = 30 + 10 = 40
        assert costs["flagship_cost_usd"] == pytest.approx(40.0)
        assert costs["saved_cost_usd"] == pytest.approx(27.0)

    def test_routing_costs_unavailable_without_flagship_price(self):
        d = CostDashboard(budget_tokens=1000)
        d.record("cheap", "评估", 100, 50, tier="轻量")
        costs = d.routing_costs(
            prices={"cheap": {"input": 1.0, "output": 2.0}},
            flagship_price=None,
        )
        assert costs["available"] is False
        assert costs["actual_cost_usd"] == 0.0

    def test_persist_payload_contains_tier_fields(self, tmp_path):
        s = _tier_settings()
        d = CostDashboard.from_call_log(
            [_log_entry("flag1", 100, 50)],
            budget_tokens=1000,
            tier_map=tier_map(s),
        )
        path = d.persist(
            tmp_path,
            prices={"flag1": {"input": 10.0, "output": 20.0}},
            flagship_price={"input": 10.0, "output": 20.0},
        )
        import json as _json

        payload = _json.loads(path.read_text(encoding="utf-8"))
        assert payload["by_tier"] == {"旗舰": 150}
        assert payload["routing_costs"]["available"] is True
        assert payload["calls"][0]["tier"] == "旗舰"

    def test_default_price_table_covers_default_models(self):
        """缺省价目表覆盖 DEFAULT_MODELS 全部四个模型（结构合法）。"""
        s = Settings()
        assert set(s.model_prices) >= set(s.models)
        assert all(
            set(p) == {"input", "output"} for p in s.model_prices.values()
        )


class TestDashboardDictSerialization:
    """server._dashboard_dict 实时看板携带档位与成本对比。"""

    def test_dashboard_dict_fields(self):
        from app.server import _dashboard_dict

        s = _tier_settings()
        d = CostDashboard.from_call_log(
            [_log_entry("flag1", 100, 50)],
            budget_tokens=1000,
            tier_map=tier_map(s),
        )
        d.attach_routing_costs(
            prices={"flag1": {"input": 10.0, "output": 20.0}},
            flagship_price={"input": 10.0, "output": 20.0},
        )
        payload = _dashboard_dict(d)
        assert payload["by_tier"] == {"旗舰": 150}
        assert payload["routing_costs"]["available"] is True
        assert payload["calls"][0]["tier"] == "旗舰"

    def test_dashboard_dict_without_snapshot_falls_back(self):
        """未 attach（无价格上下文）时回退为不可用计算，不抛错。"""
        from app.server import _dashboard_dict

        d = CostDashboard(budget_tokens=1000)
        d.record("mystery", "评估", 10, 5)
        payload = _dashboard_dict(d)
        assert payload["routing_costs"]["available"] is False


class TestClientCostContract:
    """client.html 契约：成本看板档位列与成本对比摘要（落盘验证）。"""

    _ROOT = Path(__file__).resolve().parent.parent

    def test_cost_panel_contract(self):
        html = (self._ROOT / "client.html").read_text(encoding="utf-8")
        assert 'id="c-routing"' in html          # 成本对比摘要行
        assert 'id="c-cost-actual"' in html
        assert "renderCostRows" in html          # 逐调用明细渲染
        assert "renderRoutingCosts" in html
        assert "<th>档位</th>" in html           # 明细表档位列


class TestClientThemeContract:
    """M12-8 契约：浅色 token 双套 + 主题切换（落盘验证）。"""

    _ROOT = Path(__file__).resolve().parent.parent

    def test_theme_contract(self):
        html = (self._ROOT / "client.html").read_text(encoding="utf-8")
        assert 'html[data-theme="light"]' in html   # 浅色 token 覆盖块
        assert "prefers-color-scheme" in html       # 跟随系统（matchMedia）
        assert "tb_theme" in html                   # 主题偏好持久化键
        assert 'id="btn-theme"' in html             # 切换按钮
        assert "applyTheme" in html                 # 应用函数
        assert "dataset.theme" in html              # html data-theme 切换
        # 浅色块必须覆盖全部配色 token（19 个）与两个阴影
        # （按 "html[data-theme=\"light\"] {" 精确匹配 CSS 块起点，避开注释）
        marker = 'html[data-theme="light"] {'
        block = html.split(marker)[1].split("}")[0]
        for var in ("--bg", "--panel", "--panel-2", "--border",
                    "--border-strong", "--text", "--text-2", "--muted",
                    "--accent", "--accent-hover", "--accent-ink",
                    "--accent-soft", "--accent2",
                    "--ok", "--ok-soft", "--warn", "--warn-soft",
                    "--bad", "--bad-soft",
                    "--shadow-sm", "--shadow-lg"):
            assert var in block, f"浅色主题缺 {var}"


class TestClientSettingsContract:
    """M12-7 契约：分类设置页（外观/模型/预算/安全）落盘验证。"""

    _ROOT = Path(__file__).resolve().parent.parent

    def test_settings_page_contract(self):
        html = (self._ROOT / "client.html").read_text(encoding="utf-8")
        assert 'id="tab-settings"' in html        # 设置页签
        assert 'id="main-settings"' in html       # 设置视图容器
        assert 'name="theme-pref"' in html        # 外观组：主题三选
        assert 'id="set-models"' in html          # 模型组（后端预设只读）
        assert 'id="set-budget"' in html          # 预算组（后端档位只读）
        assert 'id="set-auto-confirm"' in html    # 安全组：二次确认开关
        assert "tb_auto_confirm" in html          # 安全开关持久化键
        assert "openSettings" in html             # 设置页加载函数
        assert "/api/config" in html              # 配置数据源端点
        # switchView 三态：设置页可从工作台/项目库切换进入
        assert 'switchView("settings")' in html
