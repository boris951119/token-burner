"""双模式意图识别测试（M9-1 快判契约 / M9-2 FastTriage，TDD 先行）。

设计决策回归锚点（v0.4.md M9）：
- 档位切换是确定性程序规则；意图与置信度由 LLM 输出（D.1 兼容）；
- 快判只承接最便宜的出口：高置信闲聊/无意义 → declined、
  高置信基础 → direct_answer；编程 / 研究·分析一律升级 System-2；
- 失败方向单一：解析失败 / 取值非法 / 调用异常 / 低置信 /
  执行类边界信号 → 一律静默升级 System-2，不新增失败模式；
- `fast_triage_enabled` 缺省关闭：关闭时路由行为与 v0.3.1 完全一致。
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from app.config import Settings
from app.orchestrator import (
    FAST_TRIAGE_INTENTS,
    FastTriage,
    Route,
    RoutingResult,
    TaskRouter,
)
from app.pipeline import Pipeline
from app.tools.file_manager import FileManager
from app.utils.model_client import LLMResponse


class ScriptedLLM:
    """按序回放响应的桩：记录 (model, system 首句) 供断言。"""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, model, messages, json_mode=False, **kw):
        self.calls.append({
            "model": model,
            "system": messages[0]["content"],
        })
        content = self.responses.pop(0) if self.responses else "{}"
        return LLMResponse(model=model, content=content,
                           input_tokens=1, output_tokens=1)

    def fail(self, model, messages, json_mode=False, **kw):
        self.calls.append({"model": model, "system": messages[0]["content"]})
        raise RuntimeError("快判模型超时")


_CODING_ASSESSMENT = json.dumps({
    "task_type": "编程", "difficulty_score": 7,
    "difficulty_level": "困难", "estimated_files": 6, "reason": "多模块",
}, ensure_ascii=False)


def triage_json(intent: str, confidence: float, reason: str = "r") -> str:
    return json.dumps(
        {"intent": intent, "confidence": confidence, "reason": reason},
        ensure_ascii=False,
    )


def make_router(responses: list[str], settings: Settings) -> tuple[ScriptedLLM, TaskRouter]:
    llm = ScriptedLLM(responses)
    return llm, TaskRouter(llm, settings.models[0], settings)


# ---------------------------------------------------------------------------
# M9-1 契约校验（FastTriage._validate：非法值视同解析失败）
# ---------------------------------------------------------------------------

class TestTriageContract:
    def test_valid_result_parsed(self):
        llm = ScriptedLLM([triage_json("闲聊", 0.95, "问候语")])
        result = FastTriage(llm, Settings()).classify("你好")
        assert result is not None
        assert result.intent == "闲聊"
        assert result.confidence == 0.95
        assert result.reason == "问候语"

    def test_intent_out_of_domain_rejected(self):
        llm = ScriptedLLM([triage_json("情感陪伴", 0.99)])
        assert FastTriage(llm, Settings()).classify("你好") is None

    def test_confidence_out_of_range_rejected(self):
        llm = ScriptedLLM([triage_json("基础", 1.5)])
        assert FastTriage(llm, Settings()).classify("hello") is None

    def test_confidence_non_numeric_rejected(self):
        llm = ScriptedLLM([triage_json("基础", "0.9")])
        assert FastTriage(llm, Settings()).classify("hello") is None

    def test_confidence_bool_rejected(self):
        llm = ScriptedLLM([triage_json("基础", True)])
        assert FastTriage(llm, Settings()).classify("hello") is None

    def test_reason_missing_defaults_empty(self):
        llm = ScriptedLLM([json.dumps({"intent": "基础", "confidence": 0.9})])
        result = FastTriage(llm, Settings()).classify("hello")
        assert result is not None and result.reason == ""

    def test_non_dict_output_rejected(self):
        llm = ScriptedLLM(["我就不输出 JSON"])
        assert FastTriage(llm, Settings()).classify("hello") is None

    def test_intent_domain_frozen(self):
        assert FAST_TRIAGE_INTENTS == ("编程", "研究/分析", "基础", "闲聊", "无意义")


# ---------------------------------------------------------------------------
# M9-2 确定性升级/承接规则（fast_triage_enabled=True）
# ---------------------------------------------------------------------------

ENABLED = Settings(fast_triage_enabled=True)


class TestFastRouteRules:
    def test_high_confidence_chat_declined(self):
        llm, router = make_router([triage_json("闲聊", 0.95)], ENABLED)
        route = router.route("你好呀")
        assert route.route is Route.DECLINED
        assert route.task_type == "闲聊"
        assert len(llm.calls) == 1  # System-2 全量评估未发生
        assert route.reason.startswith("[快判]")

    def test_high_confidence_nonsense_declined(self):
        llm, router = make_router([triage_json("无意义", 0.9)], ENABLED)
        assert router.route("asdfgh").route is Route.DECLINED

    def test_high_confidence_basic_direct_output(self):
        llm, router = make_router([triage_json("基础", 0.9)], ENABLED)
        route = router.route("帮我把这段话翻译成英文")
        assert route.route is Route.DIRECT_OUTPUT
        assert route.task_type == "基础"
        assert len(llm.calls) == 1

    def test_confidence_at_threshold_accepted(self):
        # 阈值语义：< threshold 升级，== threshold 承接（宁升勿误的边界）
        llm, router = make_router([triage_json("基础", ENABLED.fast_triage_confidence_threshold)], ENABLED)
        assert router.route("hello").route is Route.DIRECT_OUTPUT

    def test_low_confidence_upgrades_to_system2(self):
        llm, router = make_router(
            [triage_json("基础", 0.5), _CODING_ASSESSMENT], ENABLED
        )
        route = router.route("做个小工具")
        assert route.route is Route.TEAM_FLOW  # 走 System-2 评估结论
        assert len(llm.calls) == 2

    def test_coding_intent_always_upgrades(self):
        llm, router = make_router(
            [triage_json("编程", 0.99), _CODING_ASSESSMENT], ENABLED
        )
        route = router.route("开发一个用户管理系统")
        assert route.route is Route.TEAM_FLOW
        assert len(llm.calls) == 2

    def test_research_intent_always_upgrades(self):
        llm, router = make_router(
            [triage_json("研究/分析", 0.99), _CODING_ASSESSMENT], ENABLED
        )
        assert router.route("对比主流数据库").route is Route.TEAM_FLOW

    def test_execution_signal_overrides_fast_verdict(self):
        # D.1 边界护栏优先：命中执行类关键词 → 即使高置信闲聊也升级
        llm, router = make_router(
            [triage_json("闲聊", 0.99), _CODING_ASSESSMENT], ENABLED
        )
        route = router.route("在吗？帮我跑一下这个脚本")
        assert route.route is Route.TEAM_FLOW
        assert len(llm.calls) == 2

    def test_parse_failure_silently_upgrades(self):
        llm, router = make_router(["不是 JSON", _CODING_ASSESSMENT], ENABLED)
        assert router.route("写个爬虫").route is Route.TEAM_FLOW
        assert len(llm.calls) == 2

    def test_call_exception_silently_upgrades(self):
        class ExplodingTriageLLM(ScriptedLLM):
            def chat(self, model, messages, json_mode=False, **kw):
                if not self.calls:  # 首次（快判）调用即抛异常
                    self.calls.append({"model": model, "system": ""})
                    raise RuntimeError("快判模型超时")
                return super().chat(model, messages, json_mode, **kw)

        llm = ExplodingTriageLLM([_CODING_ASSESSMENT])
        router = TaskRouter(llm, ENABLED.models[0], ENABLED)
        route = router.route("写个爬虫")
        assert route.route is Route.TEAM_FLOW
        assert len(llm.calls) == 2

    def test_triage_uses_configured_light_model(self):
        llm, router = make_router([triage_json("闲聊", 0.95)], ENABLED)
        router.route("你好")
        assert llm.calls[0]["model"] == ENABLED.fast_triage_model


# ---------------------------------------------------------------------------
# 开关关闭：行为与 v0.3.1 完全一致（回归保证）
# ---------------------------------------------------------------------------

class TestFastTriageDisabled:
    def test_default_settings_disabled(self):
        assert Settings().fast_triage_enabled is False

    def test_disabled_skips_triage_entirely(self):
        llm, router = make_router([_CODING_ASSESSMENT], Settings())
        route = router.route("开发一个用户管理系统")
        assert route.route is Route.TEAM_FLOW
        assert len(llm.calls) == 1  # 仅 System-2 评估，无快判调用
        assert route.fallback is False and route.rechecked is False


# ---------------------------------------------------------------------------
# Pipeline declined 出口 + 配置校验 + server 反序列化
# ---------------------------------------------------------------------------

class TestDeclinedIntegration:
    def test_pipeline_declined_no_llm_no_project(self, tmp_path):
        llm = ScriptedLLM([])
        pipeline = Pipeline(
            llm=llm, executor=None, settings=Settings(),
            file_manager=FileManager(projects_root=tmp_path / "projects"),
        )
        route = RoutingResult(
            route=Route.DECLINED, task_type="闲聊",
            difficulty_score=0, difficulty_level="未知", reason="[快判] 问候",
        )
        result = pipeline.run("你好", route=route)
        assert result.kind == "declined"
        assert llm.calls == []          # 全程零 LLM 调用
        assert result.project_id is None

    def test_config_rejects_unknown_triage_model(self):
        with pytest.raises(ValueError, match="fast_triage_model"):
            Settings(fast_triage_enabled=True, fast_triage_model="gpt-999")

    def test_config_accepts_default_triage_model(self):
        settings = Settings(fast_triage_enabled=True)
        assert settings.fast_triage_model in settings.models

    def test_config_rejects_bad_threshold(self):
        with pytest.raises(ValueError, match="fast_triage_confidence_threshold"):
            Settings(fast_triage_confidence_threshold=1.5)

    def test_server_route_roundtrip_declined(self):
        from app.server import _route_from_dict

        route = RoutingResult(
            route=Route.DECLINED, task_type="无意义",
            difficulty_score=0, difficulty_level="未知", reason="[快判]",
        )
        data = asdict(route)
        data["route"] = route.route.value
        restored = _route_from_dict(data)
        assert restored.route is Route.DECLINED
        assert restored.task_type == "无意义"
