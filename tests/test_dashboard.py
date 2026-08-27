"""成本统计仪表盘测试（TDD 先行）。

依据：规格文档 8.5 节（session 级 token 明细，表 1 口径）与
11.0 节（预算闸门）：每次调用的 input/output token 记录，
按模型 / 环节聚合，预算对比与剩余百分比，落盘 logs/。
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.dashboard.cost_dashboard import CostDashboard, StageTracker


@pytest.fixture
def dashboard():
    return CostDashboard(budget_tokens=200_000)


class TestRecordAndTotals:
    def test_record_single_call(self, dashboard):
        dashboard.record(model="gpt-4o", stage="评估", input_tokens=100, output_tokens=50)
        assert dashboard.total_tokens == 150

    def test_totals_by_model(self, dashboard):
        dashboard.record("gpt-4o", "评估", 100, 50)
        dashboard.record("deepseek-chat", "写码", 200, 80)
        dashboard.record("gpt-4o", "写码", 10, 5)
        by_model = dashboard.by_model()
        assert by_model["gpt-4o"] == 165
        assert by_model["deepseek-chat"] == 280

    def test_totals_by_stage(self, dashboard):
        dashboard.record("gpt-4o", "评估", 100, 50)
        dashboard.record("deepseek-chat", "写码", 200, 80)
        dashboard.record("deepseek-chat", "写码", 20, 10)
        by_stage = dashboard.by_stage()
        assert by_stage["评估"] == 150
        assert by_stage["写码"] == 310

    def test_input_output_breakdown(self, dashboard):
        # 8.5 表 1：输入 / 输出分列
        dashboard.record("gpt-4o", "评估", 100, 50)
        dashboard.record("gpt-4o", "写码", 30, 20)
        io = dashboard.input_output_totals()
        assert io == {"input": 130, "output": 70}


class TestBudget:
    def test_budget_remaining(self, dashboard):
        dashboard.record("gpt-4o", "评估", 100_000, 50_000)
        remaining = dashboard.budget_remaining()
        assert remaining == 50_000
        assert dashboard.budget_used_ratio() == pytest.approx(0.75)

    def test_over_budget_flagged(self, dashboard):
        dashboard.record("gpt-4o", "写码", 150_000, 60_000)
        assert dashboard.is_over_budget() is True

    def test_within_budget(self, dashboard):
        dashboard.record("gpt-4o", "写码", 100, 50)
        assert dashboard.is_over_budget() is False


class TestPersist:
    def test_report_written_to_logs(self, dashboard, tmp_path):
        # 8.5：session 级明细落盘 logs/cost_report.json
        dashboard.record("gpt-4o", "评估", 100, 50)
        path = dashboard.persist(tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["total_tokens"] == 150
        assert data["budget_tokens"] == 200_000
        assert len(data["calls"]) == 1
        assert data["calls"][0]["stage"] == "评估"

    def test_text_summary_contains_breakdown(self, dashboard):
        dashboard.record("gpt-4o", "评估", 100, 50)
        dashboard.record("deepseek-chat", "写码", 200, 80)
        summary = dashboard.text_summary()
        assert "gpt-4o" in summary and "deepseek-chat" in summary
        assert "评估" in summary and "写码" in summary
        assert "430" in summary  # 总计


class TestStageTracker:
    def test_tracker_classifies_stage_by_prompt(self):
        # 环节归属：按 system 提示词首句确定性分类（无 LLM 参与）
        assert StageTracker.stage_of("你是一名需求评估专家（项目经理）") == "评估"
        assert StageTracker.stage_of("你是项目经理（主 LLM），负责初始技术方案") == "方案讨论"
        assert StageTracker.stage_of("你是架构师（主 LLM），负责模块拆分与接口定义") == "拆分接口"
        assert StageTracker.stage_of("你是开发工程师（开发副 LLM）") == "开发"
        assert StageTracker.stage_of("你是测试工程师（测试副 LLM）") == "测试"
        assert StageTracker.stage_of("未知提示") == "其他"

    def test_tracker_from_call_log(self):
        # 从 ModelClient.call_log 直接构建（含 messages 摘要的场景）
        log = [
            {"model": "gpt-4o", "input_tokens": 10, "output_tokens": 5,
             "system_hint": "你是一名需求评估专家"},
            {"model": "deepseek-chat", "input_tokens": 20, "output_tokens": 8,
             "system_hint": "你是开发工程师"},
        ]
        dashboard = CostDashboard.from_call_log(log, budget_tokens=1000)
        assert dashboard.total_tokens == 43
        assert dashboard.by_stage()["评估"] == 15


class TestPipelineIntegration:
    def test_pipeline_populates_dashboard(self, tmp_path):
        # 端到端：管线运行后仪表盘数据齐备（用 mock 桩）
        from tests.test_pipeline import FakeExecutor, ScriptedLLM, team_scripts
        from app.tools.file_manager import FileManager
        from app.pipeline import Pipeline

        llm = ScriptedLLM(team_scripts())
        pipeline = Pipeline(
            llm=llm,
            executor=FakeExecutor(["SUCCESS"] * 3),
            settings=Settings(),
            file_manager=FileManager(projects_root=tmp_path / "projects"),
        )
        result = pipeline.run(
            "开发用户系统",
            models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe",
            spec_confirm="确认",
        )
        assert result.cost_dashboard is not None
        assert result.cost_dashboard.total_tokens > 0
        assert result.cost_dashboard.budget_tokens == Settings().task_token_budget("safe")
        stages = result.cost_dashboard.by_stage()
        assert "评估" in stages and "开发" in stages
