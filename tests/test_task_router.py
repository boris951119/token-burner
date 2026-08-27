"""TaskRouter 单元测试（TDD 先行，LLM 全部 mock）。

依据：规格文档 v0.3.1 3.2 节 + 总则 D 节 + 15.3 节：
- 三分类路由：基础 / 研究·分析 → 主 LLM 直出；编程 → 团队流程；
- 简单编程节流：难度分 ≤ simple_threshold（默认 3）→ direct_simple_coding；
- 空白带：simple_threshold < 难度 < 模块化阈值 → 标准团队流程（不跳过不降级）；
- 边界护栏（D.1）：程序不发回自判，发现矛盾信号 → 请求主 LLM 复核后重新决策；
- 难度评估 JSON 解析失败 → 保守降级视作编程任务 + 交用户确认（15.3）；
- 研究任务难度 ≥8 可选用评审确认（仍不强制组队）。
"""

from __future__ import annotations

import pytest

from app.orchestrator import Route, TaskRouter
from app.utils.model_client import LLMResponse


def eval_json(
    score: int = 7,
    task_type: str = "编程",
    reason: str = "复杂",
) -> str:
    import json
    return json.dumps(
        {
            "difficulty_score": score,
            "difficulty_level": "简单" if score <= 3 else "中等" if score <= 6 else "困难",
            "task_type": task_type,
            "reason": reason,
        },
        ensure_ascii=False,
    )


class FakeRouterLLM:
    """按脚本返回评估结果的桩。calls 记录每次调用收到的 prompt。"""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[list] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append(messages)
        from app.utils.model_client import LLMResponse
        return LLMResponse(
            model=model,
            content=self.responses.pop(0) if self.responses else eval_json(),
            input_tokens=10,
            output_tokens=5,
        )


def make_router(llm, settings=None) -> TaskRouter:
    from app.config import Settings
    s = settings or Settings()
    return TaskRouter(llm=llm, main_model="gpt-4o", settings=s)


class TestBasicRouting:
    def test_basic_task_direct(self):
        llm = FakeRouterLLM([eval_json(score=2, task_type="基础")])
        result = make_router(llm).route("写一份方案文本")
        assert result.route == Route.DIRECT_OUTPUT
        assert result.task_type == "基础"
        assert result.needs_user_confirm is False

    def test_research_task_direct(self):
        llm = FakeRouterLLM([eval_json(score=5, task_type="研究/分析")])
        result = make_router(llm).route("竞品对比")
        assert result.route == Route.DIRECT_OUTPUT
        assert result.task_type == "研究/分析"

    def test_research_hard_task_suggests_review(self):
        # 3.2：研究任务难度 ≥8 可选用一次评审确认
        llm = FakeRouterLLM([eval_json(score=8, task_type="研究/分析")])
        result = make_router(llm).route("深度行业研判")
        assert result.route == Route.DIRECT_OUTPUT
        assert result.suggest_review is True

    def test_coding_task_team_flow(self):
        llm = FakeRouterLLM([eval_json(score=7, task_type="编程")])
        result = make_router(llm).route("开发一个管理系统")
        assert result.route == Route.TEAM_FLOW

    def test_coding_simple_throttle(self):
        # 难度 ≤3 的编程任务：主 LLM 直出、跳过团队
        llm = FakeRouterLLM([eval_json(score=2, task_type="编程")])
        result = make_router(llm).route("写个小脚本")
        assert result.route == Route.DIRECT_SIMPLE_CODING

    def test_coding_boundary_throttle_exclusive(self):
        # 难度恰好 = simple_threshold（3）→ 节流命中（≤ 语义）
        llm = FakeRouterLLM([eval_json(score=3, task_type="编程")])
        result = make_router(llm).route("简单脚本")
        assert result.route == Route.DIRECT_SIMPLE_CODING

    def test_coding_blank_band_standard_team_flow(self):
        # 空白带：3 < 难度 < 5 → 标准团队流程，不跳过不降级
        llm = FakeRouterLLM([eval_json(score=4, task_type="编程")])
        result = make_router(llm).route("中等任务")
        assert result.route == Route.TEAM_FLOW


class TestGuardrailContradiction:
    def test_basic_task_with_execution_signal_triggers_recheck(self):
        # D.1 边界护栏示例：判为基础任务但需求含「运行 .py / API / 脚本」→ 程序请求复核
        llm = FakeRouterLLM([
            eval_json(score=2, task_type="基础", reason="简单"),
            eval_json(score=6, task_type="编程", reason="需求要求运行脚本，属于编程"),
        ])
        result = make_router(llm).route("帮我写一个脚本运行 data.py 并输出结果")
        assert result.route == Route.TEAM_FLOW
        assert result.task_type == "编程"
        assert len(llm.calls) == 2  # 复核发生

    def test_recheck_result_respected_not_overridden(self):
        # 复核后模型坚持原判 → 程序尊重模型决策（不抢决策权）
        llm = FakeRouterLLM([
            eval_json(score=2, task_type="基础", reason="含脚本字样但不涉及运行"),
            eval_json(score=2, task_type="基础", reason="确认：仅是文本整理"),
        ])
        result = make_router(llm).route("写一份运行说明文档 script")
        assert result.route == Route.DIRECT_OUTPUT
        assert result.rechecked is True

    def test_no_recheck_for_pure_basic(self):
        llm = FakeRouterLLM([eval_json(score=2, task_type="基础")])
        make_router(llm).route("写一份方案文本")
        assert len(llm.calls) == 1


class TestParseFallback:
    def test_unparseable_json_conservative_coding(self):
        # 15.3：解析失败 → 保守默认视作编程 + 交用户确认
        llm = FakeRouterLLM(["这不是JSON" * 3, eval_json(score=7, task_type="编程")])
        # 重试用更严格 prompt 仍失败 → 硬回退
        llm.responses = ["坏的", "还是坏的", "依旧坏的", "彻底坏的"]
        result = make_router(llm).route("任意需求")
        assert result.route == Route.TEAM_FLOW
        assert result.task_type == "编程"
        assert result.needs_user_confirm is True
        assert result.fallback is True

    def test_retry_with_stricter_prompt_succeeds(self):
        # 15.3：重试（默认 3 次）内成功 → 正常路由
        llm = FakeRouterLLM(["前置说明" + eval_json(score=2, task_type="基础")])
        # 第 1 次原生/提取块即可成功（前后缀文本），无需真实重试
        result = make_router(llm).route("需求")
        assert result.route == Route.DIRECT_OUTPUT
        assert result.fallback is False


class TestAssessmentResult:
    def test_result_carries_score_and_reason(self):
        llm = FakeRouterLLM([eval_json(score=7, task_type="编程", reason="涉及数据库")])
        result = make_router(llm).route("x")
        assert result.difficulty_score == 7
        assert result.reason == "涉及数据库"
        assert result.difficulty_level == "困难"

    def test_json_mode_used_for_assessment(self):
        # 评估调用应请求 JSON 模式（15.1 第 4 级）
        llm = FakeRouterLLM([eval_json()])
        class _Probe(FakeRouterLLM):
            def chat(self, model, messages, json_mode=False):
                self.last_json_mode = json_mode
                return super().chat(model, messages, json_mode)
        probe = _Probe([eval_json()])
        make_router(probe).route("x")
        assert probe.last_json_mode is True

    def test_invalid_task_type_value_triggers_fallback(self):
        # 判定标准要求稳定：task_type 非三值之一 → 视为解析失败走保守降级
        llm = FakeRouterLLM([
            '{"difficulty_score": 5, "task_type": "绘画", "reason": "x"}',
            '{"difficulty_score": 5, "task_type": "绘画", "reason": "x"}',
            '{"difficulty_score": 5, "task_type": "绘画", "reason": "x"}',
            '{"difficulty_score": 5, "task_type": "绘画", "reason": "x"}',
        ])
        result = make_router(llm).route("x")
        assert result.fallback is True
        assert result.route == Route.TEAM_FLOW
        assert result.needs_user_confirm is True

    def test_score_out_of_range_triggers_fallback(self):
        # difficulty_score 须落在 0-10
        bad = '{"difficulty_score": 99, "task_type": "基础", "reason": "x"}'
        llm = FakeRouterLLM([bad, bad, bad, bad])
        result = make_router(llm).route("x")
        assert result.fallback is True
