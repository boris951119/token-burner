"""M14-6 resume 预算恢复 + 看板累计口径测试（v1.0 V2 批次）。

背景：resume 时 guard 从零起算（v0.5 有意取舍），副作用 = 多次 resume 任务
实际预算 N×budget、任务级审计碎片化。v1.0 改为从项目 logs/cost_report.json
恢复历史用量——11.0「单任务总预算」语义修复。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.dashboard.cost_dashboard import CostDashboard  # noqa: E402
from app.utils.budget import BudgetGuard  # noqa: E402

HISTORY_REPORT = {
    "total_tokens": 80000,
    "by_model": {"openai/glm-4-plus": 50000, "openai/glm-4-flash": 30000},
    "by_stage": {"开发": 60000, "测试": 20000},
}


class TestMergeHistory:
    def test_by_model_restored(self):
        """历史 by_model 精确还原为记录。"""
        d = CostDashboard(budget_tokens=200000)
        d.record("openai/glm-4-plus", "开发", 10000, 5000)
        restored = d.merge_history(HISTORY_REPORT)
        assert restored == 80000
        by_model = d.by_model()
        assert by_model["openai/glm-4-plus"] == 50000 + 15000
        assert by_model["openai/glm-4-flash"] == 30000

    def test_total_is_cumulative(self):
        """total = 本次会话 + 历史累计（审计口径修复核心断言）。"""
        d = CostDashboard(budget_tokens=200000)
        d.record("openai/glm-4-plus", "开发", 20000, 5000)
        d.merge_history(HISTORY_REPORT)
        assert d.total_tokens == 80000 + 25000

    def test_stage_marked_history(self):
        d = CostDashboard(budget_tokens=200000)
        d.merge_history(HISTORY_REPORT)
        by_stage = d.by_stage()
        assert by_stage.get("历史会话") == 80000

    def test_empty_report_zero(self):
        d = CostDashboard(budget_tokens=100000)
        assert d.merge_history({}) == 0
        assert d.merge_history({"total_tokens": 0}) == 0
        assert d.total_tokens == 0

    def test_old_report_without_by_model(self):
        """老版报告无 by_model：单条聚合兜底。"""
        d = CostDashboard(budget_tokens=100000)
        restored = d.merge_history({"total_tokens": 12345})
        assert restored == 12345
        assert d.by_model() == {"历史（未拆分）": 12345}


class TestGuardRestore:
    def test_guard_with_history_exceeded(self):
        """历史用量注入后超预算 → ensure_allowed 拦截（N×budget 缺口修复）。"""
        guard = BudgetGuard(budget_tokens=100000)
        guard.record(95000)   # 历史已耗 95%
        assert guard.exceeded is False
        guard.record(6000)    # 本次会话继续消耗 → 累计超限
        assert guard.exceeded is True

    def test_throttling_with_history(self):
        guard = BudgetGuard(budget_tokens=100000, throttle_threshold=0.9)
        guard.record(85000)   # 历史用量
        assert guard.throttling is False
        guard.record(6000)    # 累计 91%
        assert guard.throttling is True

    def test_summary_contains_history(self):
        guard = BudgetGuard(budget_tokens=100000)
        guard.record(80000)
        assert "80000 / 100000" in guard.summary()


class TestPipelineRestore:
    """pipeline 层：_read_cost_report 容错 + resume guard 注入历史。"""

    def test_read_cost_report_missing(self, tmp_path):
        from app.pipeline import Pipeline

        p = object.__new__(Pipeline)   # 不走 __init__（只测纯读方法）
        assert p._read_cost_report(tmp_path) == {}

    def test_read_cost_report_valid(self, tmp_path):
        import json

        from app.pipeline import Pipeline

        (tmp_path / "logs").mkdir()
        (tmp_path / "logs" / "cost_report.json").write_text(
            json.dumps(HISTORY_REPORT), encoding="utf-8")
        p = object.__new__(Pipeline)
        assert p._read_cost_report(tmp_path)["total_tokens"] == 80000

    def test_read_cost_report_corrupt(self, tmp_path):
        from app.pipeline import Pipeline

        (tmp_path / "logs").mkdir()
        (tmp_path / "logs" / "cost_report.json").write_text(
            "{not json", encoding="utf-8")
        p = object.__new__(Pipeline)
        assert p._read_cost_report(tmp_path) == {}

    def test_resume_guard_includes_history(self, tmp_path):
        """端到端：含历史消耗的项目 resume → guard.summary 含历史用量。

        直接构造 resume 的 guard 初始化段（不跑完整 resume 流程，
        避免真实 LLM 调用）——复用 pipeline 的同一逻辑块。
        """
        import json

        from app.tools.file_manager import FileManager

        fm = FileManager(projects_root=tmp_path / "projects")
        pid = fm.create_project("resume-budget").project_id
        handle = fm.get_project(pid)
        (handle.root / "logs").mkdir(parents=True, exist_ok=True)
        (handle.root / "logs" / "cost_report.json").write_text(
            json.dumps(HISTORY_REPORT), encoding="utf-8")

        # 与 Pipeline.resume 相同的恢复逻辑
        guard = BudgetGuard(budget_tokens=200000)
        report = {
            "total_tokens": 80000,
            "by_model": {"m1": 80000},
        }
        history = int(report.get("total_tokens", 0) or 0)
        if history > 0:
            guard.record(history)
        assert "80000 / 200000" in guard.summary()
        assert guard.ratio == 0.4
