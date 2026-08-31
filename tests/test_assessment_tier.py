"""M9-5 评估降档测试：System-2 评估/复核调用固定用主力档。

设计锚点（v0.4.md M9-5，复用 B7 分层，无新逻辑）：
- 评估是轻量分类任务，固定降档：主力档 → models[1] → 单模型不降；
- 方案讨论/团队协作等重决策仍用旗舰（TeamBuilder/route_models 不受影响）；
- 确定性程序职责（D.1）：档位选择是纯函数，无 LLM 参与选模。
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.orchestrator import TeamBuildError, assessment_model
from app.pipeline import Pipeline
from app.tools.file_manager import FileManager
from tests.test_fast_triage import _CODING_ASSESSMENT, ScriptedLLM


class TestAssessmentModelPureFunction:
    def test_main_tier_preferred(self):
        s = Settings(
            models=["flagship", "main", "light"],
            model_tier_main=["main"],
        )
        assert assessment_model(s) == "main"

    def test_tier_order_respected(self):
        s = Settings(
            models=["a", "b", "c"],
            model_tier_main=["c", "b"],  # 档内按配置顺序取第一个
        )
        assert assessment_model(s) == "c"

    def test_empty_tier_falls_to_second_model(self):
        # 缺省 tier 默认值（gpt-4o 等）不在 models 中 → 过滤后为空 → models[1]
        s = Settings(models=["flagship", "main", "light"])
        assert assessment_model(s) == "main"

    def test_tier_entry_not_in_models_ignored(self):
        s = Settings(models=["a", "b"], model_tier_main=["ghost"])
        assert assessment_model(s) == "b"

    def test_single_model_no_degrade(self):
        s = Settings(models=["only"])
        assert assessment_model(s) == "only"


class TestPipelineIntegration:
    def test_pipeline_routes_assessment_to_main_tier(self, tmp_path):
        """端到端：System-2 评估调用收到的是主力档，而非旗舰。

        评估后流程进入团队协作（executor=None 必然在下游失败）——
        本测试只关心第一次调用的模型档位。
        """
        s = Settings(
            models=["flagship", "main", "light"],
            model_tier_main=["main"],
            model_tier_flagship=["flagship"],
            model_tier_light=["light"],
        )
        llm = ScriptedLLM([_CODING_ASSESSMENT])
        pipeline = Pipeline(
            llm=llm, executor=None, settings=s,
            file_manager=FileManager(projects_root=tmp_path / "projects"),
        )
        with pytest.raises(Exception):
            pipeline.run("开发一个记账脚本")
        assert llm.calls, "应发生评估调用"
        assert llm.calls[0]["model"] == "main"

    def test_pipeline_without_tier_uses_second_model(self, tmp_path):
        """缺省 tier 配置下降档到预设第二顺位（v0.3.1 用户零配置即生效）。

        默认旗舰档（gpt-4o 等）不在测试 models 中 → 团队组建必然
        TeamBuildError——恰好作为评估之后的确定性断点。
        """
        s = Settings(models=["flagship", "main", "light"])
        llm = ScriptedLLM([_CODING_ASSESSMENT])
        pipeline = Pipeline(
            llm=llm, executor=None, settings=s,
            file_manager=FileManager(projects_root=tmp_path / "projects"),
        )
        with pytest.raises(TeamBuildError):
            pipeline.run("开发一个记账脚本")
        assert llm.calls[0]["model"] == "main"

    def test_recheck_follows_degraded_model(self, tmp_path):
        """复核（_recheck）与评估共用 TaskRouter.main_model，自动跟随降档。"""
        s = Settings(
            models=["flagship", "main", "light"],
            model_tier_main=["main"],
        )
        # 评估判基础（direct_answer），内容触发执行类边界信号 → 复核
        assessment = json.dumps({
            "task_type": "基础", "difficulty_score": 2,
            "difficulty_level": "简单", "estimated_files": 0, "reason": "r",
        })
        llm = ScriptedLLM([assessment, assessment])  # 复核维持基础判定
        pipeline = Pipeline(
            llm=llm, executor=None, settings=s,
            file_manager=FileManager(projects_root=tmp_path / "projects"),
        )
        pipeline.run("帮我写一段介绍，然后运行 API 测试一下")  # 含执行类信号
        assert len(llm.calls) >= 2, "评估 + 复核应至少两次调用"
        assert llm.calls[0]["model"] == "main"  # 评估
        assert llm.calls[1]["model"] == "main"  # 复核
