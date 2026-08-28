"""复用外部路由结果测试（产品审计问题 5 修复，TDD 先行）。

问题：CLI 先调 router.route() 展示评估，Pipeline.run() 内部再评估一次
——每次任务重复消耗一次评估调用，且两次评估可能不一致（用户看到的
难度与实际执行所用不同）。

修复约定：run() 增加可选 route 参数（RoutingResult）；外部已评估时
直接复用（零重复调用）；未传时保持自评估（测试/程序化调用兼容）。
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.pipeline import Pipeline
from app.tools.file_manager import FileManager


class CountingRouterLLM:
    """直答任务桩：统计评估调用次数。"""

    def __init__(self):
        self.calls = 0
        self.call_log = []

    def chat(self, model, messages, json_mode=False, **kw):
        from app.utils.model_client import LLMResponse
        self.calls += 1
        # 首个 json_mode 调用 = 评估；返回「基础」类型（→ 直接回答路由）
        if json_mode:
            content = '{"task_type": "基础", "difficulty_score": 2, "reason": "简单"}'
            return LLMResponse(model=model, content=content,
                               input_tokens=5, output_tokens=5)
        return LLMResponse(model=model, content="直答内容",
                           input_tokens=5, output_tokens=5)


def _route_result():
    from app.orchestrator import Route, RoutingResult
    return RoutingResult(
        route=Route.DIRECT_OUTPUT, task_type="闲聊",
        difficulty_score=2, difficulty_level="低", reason="外部已评估",
    )


@pytest.fixture
def fm(tmp_path):
    return FileManager(projects_root=tmp_path / "projects")


class TestRouteReuse:
    def test_route_passed_skips_internal_assessment(self, fm):
        # 外部传入 route → 零评估调用（LLM 仅被用于直答）
        llm = CountingRouterLLM()
        pipeline = Pipeline(llm=llm, executor=None,
                            settings=Settings(), file_manager=fm)
        result = pipeline.run("你好", route=_route_result())
        assert result.kind == "direct_answer"
        assert llm.calls == 1          # 仅直答，无评估

    def test_no_route_still_self_assesses(self, fm):
        # 不传 route → 保持原自评估行为（兼容）
        llm = CountingRouterLLM()
        pipeline = Pipeline(llm=llm, executor=None,
                            settings=Settings(), file_manager=fm)
        result = pipeline.run("你好")
        assert result.kind == "direct_answer"
        assert llm.calls == 2          # 评估 + 直答

    def test_reused_route_in_result(self, fm):
        # 返回结果携带外部传入的 route（评估元数据一致）
        llm = CountingRouterLLM()
        pipeline = Pipeline(llm=llm, executor=None,
                            settings=Settings(), file_manager=fm)
        route = _route_result()
        result = pipeline.run("你好", route=route)
        assert result.route is route
        assert result.route.reason == "外部已评估"
