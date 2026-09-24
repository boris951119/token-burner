"""11.0 单任务 token 总预算闸门测试（TDD 先行，第 0 层总闸）。

覆盖：
- BudgetGuard 单元：阈值判定（正常 / ≥90% 省 token 模式 / 超预算中止）；
- Settings：budget_throttle_threshold 默认值与取值域校验；
- ModelClient：挂接 guard 后调用前拦截超限、调用后累计用量；
- Pipeline 团队流程：预算耗尽 → kind=budget_exceeded + budget_stop.md 落盘
  （已完成部分 + 未完成清单 + 已耗 token，交用户决定续跑或止损）；
- DiscussionEngine：预算 ≥90% → 压缩讨论轮数提前收敛（省 token 模式）；
- DevLoopEngine：修复前预算耗尽 → 立即中止上抛。
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.utils.budget import BudgetExceededError, BudgetGuard


@pytest.fixture
def fm(tmp_path):
    from app.tools.file_manager import FileManager

    return FileManager(projects_root=tmp_path / "projects")


# ---------------------------------------------------------------------------
# BudgetGuard 单元
# ---------------------------------------------------------------------------


class TestBudgetGuard:
    def test_below_threshold_normal(self):
        guard = BudgetGuard(100, throttle_threshold=0.9)
        guard.record(50)
        assert not guard.throttling
        assert not guard.exceeded
        assert guard.ensure_allowed() is None

    def test_at_throttle_threshold_enters_throttle_mode(self):
        # 11.0：≥90% 进入省 token 模式（未超限，仍可调用）
        guard = BudgetGuard(100, throttle_threshold=0.9)
        guard.record(90)
        assert guard.throttling
        assert not guard.exceeded

    def test_exceeded_ensure_allowed_raises(self):
        guard = BudgetGuard(100, throttle_threshold=0.9)
        guard.record(100)
        assert guard.exceeded
        with pytest.raises(BudgetExceededError):
            guard.ensure_allowed()

    def test_summary_contains_numbers(self):
        guard = BudgetGuard(200, throttle_threshold=0.9)
        guard.record(100)
        summary = guard.summary()
        assert "100" in summary and "200" in summary and "50.0%" in summary

    def test_invalid_arguments_rejected(self):
        with pytest.raises(ValueError):
            BudgetGuard(0)
        with pytest.raises(ValueError):
            BudgetGuard(-10)
        with pytest.raises(ValueError):
            BudgetGuard(100, throttle_threshold=0)
        with pytest.raises(ValueError):
            BudgetGuard(100, throttle_threshold=1.5)


class TestSettingsThrottleThreshold:
    def test_default_is_0_9(self):
        assert Settings().budget_throttle_threshold == 0.9

    def test_out_of_range_rejected(self):
        with pytest.raises(ValueError):
            Settings(budget_throttle_threshold=1.5)
        with pytest.raises(ValueError):
            Settings(budget_throttle_threshold=0)


# ---------------------------------------------------------------------------
# ModelClient 挂接（调用前拦截 + 调用后累计）
# ---------------------------------------------------------------------------


def _fake_completion(**kwargs):
    return {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 60, "completion_tokens": 50},
    }


class TestModelClientGuard:
    def _client(self, guard):
        from app.utils.model_client import ModelClient

        client = ModelClient(
            Settings(models=["test-model"]), completion_fn=_fake_completion
        )
        client.budget_guard = guard
        return client

    def test_records_usage_after_each_call(self):
        guard = BudgetGuard(1000)
        client = self._client(guard)
        client.chat("test-model", [{"role": "user", "content": "hi"}])
        assert guard.used_tokens == 110

    def test_blocks_call_once_exceeded(self):
        # 每次调用 110 token；两次后 220 ≥ 200 → 第三次调用前拦截
        guard = BudgetGuard(200)
        client = self._client(guard)
        client.chat("test-model", [{"role": "user", "content": "1"}])
        client.chat("test-model", [{"role": "user", "content": "2"}])
        assert guard.exceeded
        with pytest.raises(BudgetExceededError):
            client.chat("test-model", [{"role": "user", "content": "3"}])

    def test_no_guard_no_interference(self):
        from app.utils.model_client import ModelClient

        client = ModelClient(
            Settings(models=["test-model"]), completion_fn=_fake_completion
        )
        assert client.chat("test-model", [{"role": "user", "content": "x"}]).content == "ok"


# ---------------------------------------------------------------------------
# Pipeline 团队流程：超预算中止 + 落盘
# ---------------------------------------------------------------------------


class TestPipelineBudgetStop:
    def test_team_flow_aborts_and_persists_report(self, fm):
        from app.pipeline import Pipeline
        from tests.test_pipeline import FakeExecutor, ScriptedLLM, team_scripts

        # 每次桩调用 15 token；前置 9 次调用（评估→接口）共 135，
        # 预算 150 → 模块开发阶段耗尽 → 中止并落盘
        settings = Settings(max_task_tokens=150)
        llm = ScriptedLLM(team_scripts())
        pipeline = Pipeline(
            llm=llm, executor=FakeExecutor([]), settings=settings, file_manager=fm
        )
        result = pipeline.run(
            "开发用户系统",
            models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe",
            spec_confirm="确认",
        )
        assert result.kind == "budget_exceeded"
        assert result.project_id
        assert result.pending_modules  # 未完成清单非空
        assert "auth" in result.pending_modules

        handle = fm.get_project(result.project_id)
        report = (handle.root / "sessions" / "budget_stop.md").read_text(
            encoding="utf-8"
        )
        # 11.0：已完成部分 + 未完成清单 + 已耗 token + 交用户决定
        assert "未完成" in report
        assert "token" in report
        assert "已完成" in report
        assert "续跑" in report and "止损" in report

    def test_budget_guard_detached_after_run(self, fm):
        # 任务结束后护栏卸载，不污染同客户端的后续任务
        from app.pipeline import Pipeline
        from tests.test_pipeline import FakeExecutor, ScriptedLLM, team_scripts

        llm = ScriptedLLM(team_scripts())
        pipeline = Pipeline(
            llm=llm,
            executor=FakeExecutor(["SUCCESS"] * 3),
            settings=Settings(),
            file_manager=fm,
        )
        pipeline.run(
            "开发用户系统",
            models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe",
            spec_confirm="确认",
        )
        assert llm.budget_guard is None


# ---------------------------------------------------------------------------
# 省 token 模式：讨论轮数压缩
# ---------------------------------------------------------------------------


class TestThrottleMode:
    def test_discussion_compressed_when_throttling(self):
        from app.orchestrator import DiscussionEngine
        from tests.test_pipeline import ScriptedLLM

        # 每次调用 15 token；第 1 轮（方案+双评审）后 45 ≥ 90%×48
        # → 跳过修订与后续轮，直接收敛（脚本仅剩收敛一条）
        guard = BudgetGuard(48, throttle_threshold=0.9)
        llm = ScriptedLLM([])
        llm.budget_guard = guard
        weak = json.dumps(
            {
                "scores": {"feasibility": 9, "security": 9, "maintainability": 9},
                "strengths": ["完善"],
                "weaknesses": ["权限粒度不足"],
                "risks": [],
            },
            ensure_ascii=False,
        )
        llm.scripts = ["初始方案", weak, weak, "最终spec"]
        engine = DiscussionEngine(
            llm=llm,
            main_model="gpt-4o",
            dev_model="deepseek-chat",
            test_model="claude-3-5-sonnet",
            settings=Settings(),
            budget_guard=guard,
        )
        outcome = engine.run_discussion("需求")
        assert outcome.rounds_completed == 1
        # 未消费「修订」脚本：收敛直接拿到第 4 条脚本
        assert outcome.spec_md == "最终spec"
        assert llm.remaining == 0
        assert "省 token" in outcome.discussion_summary

    def test_no_throttle_full_rounds(self):
        from app.orchestrator import DiscussionEngine
        from tests.test_pipeline import ScriptedLLM

        # 预算充足 → 不触发省 token 模式；相同论点第 3 次重复（第 2 轮
        # 测试评审）→ 循环检测冻结（11.3），收敛拿到最后一条脚本
        guard = BudgetGuard(10_000)
        llm = ScriptedLLM([])
        llm.budget_guard = guard
        weak = json.dumps(
            {
                "scores": {"feasibility": 9, "security": 9, "maintainability": 9},
                "strengths": [],
                "weaknesses": ["权限粒度不足"],
                "risks": [],
            },
            ensure_ascii=False,
        )
        llm.scripts = [
            "初始方案",
            weak, weak,            # 第 1 轮：双评审（首次入库 + 重复 1 次）
            "修订1",               # 第 1 轮修订
            weak, weak,            # 第 2 轮：双评审（重复 2、3 次 → 冻结）
            "最终spec",            # 收敛裁决
        ]
        engine = DiscussionEngine(
            llm=llm,
            main_model="gpt-4o",
            dev_model="deepseek-chat",
            test_model="claude-3-5-sonnet",
            settings=Settings(),
            budget_guard=guard,
        )
        outcome = engine.run_discussion("需求")
        assert outcome.spec_md == "最终spec"
        assert "省 token" not in outcome.discussion_summary


# ---------------------------------------------------------------------------
# DevLoop：修复前预算中止
# ---------------------------------------------------------------------------


class TestDevLoopBudgetStop:
    def test_fix_aborts_when_exceeded(self, fm):
        from app.agents.dev_loop import DevLoopEngine
        from tests.test_pipeline import FakeExecutor, ScriptedLLM

        # 写码+写测试共 30 token = 预算 → 门禁失败后修复前中止
        guard = BudgetGuard(30)
        llm = ScriptedLLM(["x = broken(", "TEST"])
        llm.budget_guard = guard
        engine = DevLoopEngine(
            llm=llm,
            dev_model="deepseek-chat",
            test_model="claude-3-5-sonnet",
            executor=FakeExecutor([]),
            settings=Settings(max_fix_rounds=5),
            file_manager=fm,
            budget_guard=guard,
        )
        with pytest.raises(BudgetExceededError):
            engine.run_module("m")


class TestSizeAwareBudget:
    """题面体量→token 信封折算（参赛入口用；官方容器零 config.json）。"""

    def test_small_task_still_covers_measured_minimum(self):
        """四需求那道题实测 518k 才走完生成+验收——信封必须容得下它加修复。"""
        from app.utils.budget import size_aware_budget

        assert size_aware_budget(4) > 518_424

    def test_grows_with_requirement_count_and_caps(self):
        from app.utils.budget import size_aware_budget

        assert size_aware_budget(32) < size_aware_budget(125)
        assert size_aware_budget(9999) == size_aware_budget(10**9)  # 顶格

    def test_garbage_input_falls_back_to_base_not_crash(self):
        """入口在生成前算体量：脏值不该把整跑换成一次启动异常。"""
        from app.utils.budget import size_aware_budget

        assert size_aware_budget(-5) == size_aware_budget(0)
        assert size_aware_budget(None) == size_aware_budget(0)
        assert size_aware_budget("32") == size_aware_budget(32)
        assert size_aware_budget(32, None) == size_aware_budget(32)
        assert size_aware_budget(32, -1) == size_aware_budget(32)
        assert size_aware_budget(32, "17797") == size_aware_budget(32, 17797)

    # ---------------- 字数项（9/24 正式赛真题面逼出来的第二折算口径） ----------------

    def test_char_term_never_shrinks_a_count_based_envelope(self):
        """两式取大 ⇒ 加字数项只会抬不会压：老题面不可能因此次跑比上次更早撞墙。"""
        from app.utils.budget import size_aware_budget

        for n, chars in ((32, 17_797), (34, 19_096), (66, 44_275), (117, 86_237),
                         (125, 58_223), (86, 40_235)):
            assert size_aware_budget(n, chars) >= size_aware_budget(n)

    def test_practice_tasks_envelopes_unchanged_by_char_term(self):
        """初赛六道实测数值逐条钉死：它们的每条需求 450~750 字符，字数项在带内
        永远低于条数项 ⇒ 本次改动对初赛任何一跑都是数值零变化（可归因）。"""
        from app.utils.budget import size_aware_budget

        measured = {32: (17_797, 1_440_000), 34: (19_096, 1_480_000),
                    66: (44_275, 2_120_000), 86: (40_235, 2_520_000),
                    117: (86_237, 3_140_000), 125: (58_223, 3_300_000)}
        for n, (chars, expect) in measured.items():
            assert size_aware_budget(n, chars) == expect, f"{n} 条/{chars} 字"

    def test_formal_tasks_get_char_driven_envelope(self):
        """正式赛两道「条少字多」出带题面：github 每条 3,120 字符（keep 的 5.6
        倍），条数口径只给 1.74M，按实测 30k token/千字它需要 4.40M。"""
        from app.utils.budget import size_aware_budget

        sheet, gh = size_aware_budget(24, 54_048), size_aware_budget(47, 146_637)
        assert sheet > size_aware_budget(24)
        assert gh > size_aware_budget(47)
        assert gh == 4_399_110 and sheet == 1_621_440
        # 两题都要做完才有分 ⇒ 配比按题面文字量，github 拿大头但不吃掉另一题
        assert 0.70 <= gh / (gh + sheet) <= 0.76

    def test_char_term_does_not_double_count_fixed_overhead(self):
        """30k/千字 是从含固定开销的总用量除出来的，字数项不再加 base，
        否则小体量题面会被虚高一档。"""
        from app.utils.budget import size_aware_budget

        assert size_aware_budget(0, 1_000) == 800_000          # 千字=30k < base
        assert size_aware_budget(0, 30_000) == 900_000          # 纯字数项
        assert size_aware_budget(10**9) == size_aware_budget(10**12) == 5_000_000

    def test_count_requirements_covers_root_level_atomics(self):
        """根级 ATOMIC（官方题面 REQ-0「打开首页」那一形）也计入体量。"""
        from app.arcbench_ingest import count_requirements

        tree = {"type": "FOLDER", "children": [
            {"type": "ATOMIC", "id": "REQ-0"},
            {"type": "FOLDER", "id": "REQ-1", "children": [
                {"type": "ATOMIC", "id": "REQ-1.1"},
                {"type": "ATOMIC", "id": "REQ-1.2"},
            ]},
        ]}
        assert count_requirements(tree) == 3


class TestRepairReserve:
    """11.0 修复保留额：总闸之前留一段给修复，越过保留线就地收敛。"""

    def test_default_off_behaviour_unchanged(self):
        g = BudgetGuard(1000)
        assert not g.throttling and g.repair_reserve == 0
        g.record(899)
        assert not g.throttling          # 旧口径：仍是 ≥90% 才节流
        g.record(101)
        assert g.exceeded

    def test_reserve_moves_the_throttle_line_not_the_hard_stop(self):
        g = BudgetGuard(1000, repair_reserve_ratio=0.25)
        assert g.repair_reserve == 250 and g.remaining == 1000
        g.record(700)
        assert not g.throttling and g.repair_fund_intact
        g.record(60)
        # 同一条线两副面孔：前置阶段到此收敛，修复通道到此仍开工
        assert g.throttling and not g.repair_fund_intact
        assert not g.exceeded            # 总闸口径不动（1000 才算耗尽）
        g.record(240)
        assert g.exceeded and not g.repair_fund_intact

    def test_reserve_below_throttle_line_wins(self):
        """保留额比 90% 线更靠前时按更靠前那条触发（隔离要有牙齿）。"""
        g = BudgetGuard(1000, throttle_threshold=0.9,
                        repair_reserve_ratio=0.3)
        g.record(701)
        assert g.throttling

    @pytest.mark.parametrize("bad", (1.0, -0.1, 1.5))
    def test_bad_reserve_rejected(self, bad):
        """保留额 ≥1 等于没有总闸、<0 无意义——构造期确定性拒绝。"""
        with pytest.raises(ValueError, match="repair_reserve_ratio"):
            BudgetGuard(1000, repair_reserve_ratio=bad)

    def test_settings_default_reserves_a_quarter_and_validates(self):
        assert Settings().budget_repair_reserve == 0.25
        with pytest.raises(ValueError, match="budget_repair_reserve"):
            Settings(budget_repair_reserve=1.0)
