"""3.8 用户反馈与修复交互闭环测试（TDD 先行）。

规格依据（v0.3.1）：
- 3.1 步骤 7-9：安全模式提示本地运行 → 用户反馈 → 修复 →
  循环直至用户确认成功 / 达修复上限 / 手动结束；
- 3.8：反馈交开发副 LLM 修复；同一模块连续修复失败 ≥2 轮 →
  建议 Researcher 调研（Beta v0.5，MVP 以提示落地，4.6 降级）；
- 8.4：SKIPPED = 安全模式未执行，等待用户反馈（而非空耗修复轮）；
- 11.4：反馈轮同样受 max_fix_rounds 约束，达上限输出
  「已知问题与降级方案」交用户决定。
"""

from __future__ import annotations

import pytest

from app.agents.dev_loop import DevLoopEngine, ModuleResult, ModuleStatus
from app.config import Settings
from app.utils.model_client import LLMResponse


# ---------------------------------------------------------------------------
# 桩
# ---------------------------------------------------------------------------


class ScriptedLLM:
    """按序返回内容的桩（dev_loop 级测试用）。"""

    def __init__(self, scripts: list[str] | None = None):
        self.scripts = list(scripts or [])
        self.calls: list[dict] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append({"model": model, "json_mode": json_mode})
        content = self.scripts.pop(0) if self.scripts else "print('default')"
        return LLMResponse(model=model, content=content, input_tokens=10, output_tokens=5)


class FakeExecutor:
    def __init__(self, statuses: list[str]):
        self.statuses = list(statuses)
        self.runs: list[dict] = []

    def run(self, code, tests, timeout, expected_output="", module=""):
        from app.execution.executor import ExecutionResult, ExecutionStatus

        status = self.statuses.pop(0) if self.statuses else "SUCCESS"
        self.runs.append({"code": code, "tests": tests, "status": status})
        return ExecutionResult(
            status=ExecutionStatus(status),
            message="安全模式：请手动运行以下命令..." if status == "SKIPPED" else "",
        )


class ScriptedFeedback:
    """按序返回用户反馈的桩：记录每一轮 prompt（供提示语断言）。"""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else "exit"


@pytest.fixture
def fm(tmp_path):
    from app.tools.file_manager import FileManager

    return FileManager(projects_root=tmp_path / "projects")


def _create(fm):
    return fm.create_project("demo").project_id


def make_engine(llm, executor, fm, settings=None) -> DevLoopEngine:
    return DevLoopEngine(
        llm=llm,
        dev_model="deepseek-chat",
        test_model="claude-3-5-sonnet",
        executor=executor,
        settings=settings or Settings(),
        file_manager=fm,
    )


def _awaiting(fix_attempts: int = 0, code: str = "CODE", tests: str = "TEST") -> ModuleResult:
    """构造「等待用户反馈」的模块结果（反馈闭环的输入态）。"""
    return ModuleResult(
        module="user",
        status=ModuleStatus.AWAITING_FEEDBACK,
        fix_attempts=fix_attempts,
        message="",
        code=code,
        tests=tests,
    )


# ---------------------------------------------------------------------------
# DevLoop：SKIPPED 无反馈 → 等待用户（不空耗修复轮）
# ---------------------------------------------------------------------------


class TestAwaitingFeedback:
    def test_skipped_without_feedback_awaits(self, fm):
        # 8.4/3.8：SKIPPED 且无反馈 → 等待用户手动运行，不消耗修复轮
        llm = ScriptedLLM(["CODE_A", "TEST_A"])
        executor = FakeExecutor(["SKIPPED"])
        engine = make_engine(llm, executor, fm)
        result = engine.run_module("user", project_id=_create(fm))
        assert result.status == ModuleStatus.AWAITING_FEEDBACK
        assert result.fix_attempts == 0
        assert len(llm.calls) == 2  # 仅写码+写测试，未触发修复调用
        assert "手动运行" in result.message

    def test_awaiting_persists_code_and_tests(self, fm):
        # 12.3：等待反馈状态保留现场（代码与测试已落盘，供用户运行）
        project_id = _create(fm)
        llm = ScriptedLLM(["CODE_A", "TEST_A"])
        engine = make_engine(llm, FakeExecutor(["SKIPPED"]), fm)
        engine.run_module("user", project_id=project_id)
        handle = fm.get_project(project_id)
        assert handle is not None
        assert (handle.root / "code" / "user" / "user.py").is_file()
        assert (handle.root / "tests" / "user" / "test_user.py").is_file()

    def test_error_feedback_fixes_once_then_awaits_new_feedback(self, fm):
        # 3.8：报错反馈 → 修复一轮 → 修复后仍 SKIPPED → 等待「新」反馈
        #（不重复消费旧反馈空耗修复轮）
        llm = ScriptedLLM(["CODE_A", "TEST_A", "FIX_1"])
        executor = FakeExecutor(["SKIPPED", "SKIPPED"])
        engine = make_engine(llm, executor, fm)
        result = engine.run_module(
            "user",
            project_id=_create(fm),
            user_feedback="运行报错：NameError: name 'x' is not defined",
        )
        assert result.status == ModuleStatus.AWAITING_FEEDBACK
        assert result.fix_attempts == 1
        assert result.code == "FIX_1"
        assert len(llm.calls) == 3  # 写码 + 写测试 + 一轮修复


# ---------------------------------------------------------------------------
# DevLoop：resume_with_feedback（反馈闭环入口）
# ---------------------------------------------------------------------------


class TestResumeWithFeedback:
    def test_success_feedback_confirms_without_cost(self, fm):
        # 3.8：用户确认成功 → 模块完成，不消耗修复轮、不发起 LLM 调用
        llm = ScriptedLLM([])
        engine = make_engine(llm, FakeExecutor([]), fm)
        result = engine.resume_with_feedback(
            "user", _awaiting(fix_attempts=2), "手动运行成功，输出符合预期",
            project_id=_create(fm),
        )
        assert result.status == ModuleStatus.SUCCESS
        assert result.fix_attempts == 2
        assert llm.calls == []

    def test_error_feedback_fixes_then_awaits(self, fm):
        # 3.8：报错反馈 → 修复（计入轮次）→ SKIPPED → 等待新反馈
        llm = ScriptedLLM(["FIX_1"])
        executor = FakeExecutor(["SKIPPED", "SKIPPED"])
        engine = make_engine(llm, executor, fm)
        result = engine.resume_with_feedback(
            "user", _awaiting(fix_attempts=1), "还是报错：ValueError",
            project_id=_create(fm),
        )
        assert result.status == ModuleStatus.AWAITING_FEEDBACK
        assert result.fix_attempts == 2
        assert result.code == "FIX_1"

    def test_at_limit_freezes_with_known_issues(self, fm):
        # 11.4/3.8：反馈轮达修复上限 → 冻结并输出「已知问题与降级方案」
        llm = ScriptedLLM([])
        engine = make_engine(llm, FakeExecutor([]), fm, settings=Settings(max_fix_rounds=3))
        result = engine.resume_with_feedback(
            "user", _awaiting(fix_attempts=3), "仍然失败",
            project_id=_create(fm),
        )
        assert result.status == ModuleStatus.FROZEN
        assert "已知问题" in result.message
        assert llm.calls == []  # 上限已至，不再发起修复调用

    def test_resume_fix_history_persisted(self, fm):
        # 12.4：反馈轮修复同样落盘修复历史
        project_id = _create(fm)
        llm = ScriptedLLM(["FIX_1"])
        engine = make_engine(llm, FakeExecutor(["SKIPPED"]), fm)
        engine.resume_with_feedback(
            "user", _awaiting(fix_attempts=1), "报错信息", project_id=project_id
        )
        handle = fm.get_project(project_id)
        assert handle is not None
        history = (handle.root / "changelog" / "user" / "fix_history.md").read_text(
            encoding="utf-8"
        )
        assert "第 2 次修复" in history


# ---------------------------------------------------------------------------
# Pipeline：反馈交互闭环（feedback_fn 回调驱动）
# ---------------------------------------------------------------------------

_SIMPLE_FIX = "def core_fn():\n    return 1\n"
_AUTH_FIX = (
    "from user import core_fn as user_core_fn\n"
    "from data import core_fn as data_core_fn\n"
    "def core_fn():\n    return user_core_fn() + data_core_fn()\n"
)


def _team_pipeline(fm, scripts, statuses, settings=None):
    from app.pipeline import Pipeline
    from tests.test_pipeline import ScriptedLLM as PipelineScriptedLLM

    return Pipeline(
        llm=PipelineScriptedLLM(scripts),
        executor=FakeExecutor(statuses),
        settings=settings or Settings(),
        file_manager=fm,
    )


_RUN_KWARGS = dict(
    requirement="开发用户系统",
    models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
    mode="safe",
    spec_confirm="确认",
)


class TestPipelineFeedbackLoop:
    def test_success_feedback_completes_all_modules(self, fm):
        # 3.1 步骤 9：全模块 SKIPPED → 一轮"成功"反馈 → 全部完成
        from tests.test_pipeline import team_scripts

        pipeline = _team_pipeline(fm, team_scripts(), ["SKIPPED"] * 3)
        feedback = ScriptedFeedback(["运行成功，输出符合预期"])
        result = pipeline.run(feedback_fn=feedback, **_RUN_KWARGS)
        assert result.kind == "team_flow"
        assert "完成" in result.deliverable_summary
        assert "待用户反馈" not in result.deliverable_summary
        assert len(feedback.prompts) == 1

    def test_error_feedback_fixes_then_success(self, fm):
        # 3.8：报错反馈触发修复 → 修复后等待新反馈 → "成功"确认
        from tests.test_pipeline import team_scripts

        scripts = team_scripts() + [_SIMPLE_FIX, _SIMPLE_FIX, _AUTH_FIX]
        pipeline = _team_pipeline(fm, scripts, ["SKIPPED"] * 6)
        feedback = ScriptedFeedback(["Traceback: NameError: 'x' is not defined", "运行成功"])
        result = pipeline.run(feedback_fn=feedback, **_RUN_KWARGS)
        assert result.kind == "team_flow"
        assert "完成" in result.deliverable_summary
        assert "待用户反馈" not in result.deliverable_summary
        assert len(feedback.prompts) == 2  # 报错一轮 + 成功确认一轮

    def test_exit_stops_leaving_awaiting_modules(self, fm):
        # 3.8：用户手动停止（exit）→ 循环结束，模块保持待反馈状态
        from tests.test_pipeline import team_scripts

        pipeline = _team_pipeline(fm, team_scripts(), ["SKIPPED"] * 3)
        feedback = ScriptedFeedback(["exit"])
        result = pipeline.run(feedback_fn=feedback, **_RUN_KWARGS)
        assert result.kind == "team_flow"
        assert "待用户反馈" in result.deliverable_summary

    def test_limit_reached_reports_known_issues(self, fm):
        # 11.4：反馈轮达上限 → 冻结 + 已知问题交用户决定，循环终止
        from tests.test_pipeline import team_scripts

        scripts = team_scripts() + [_SIMPLE_FIX, _SIMPLE_FIX, _AUTH_FIX]
        settings = Settings(max_fix_rounds=1)
        # 初次 3 次 + 第 1 轮报错修复后执行 3×2 次（修复前/后各一次）
        pipeline = _team_pipeline(fm, scripts, ["SKIPPED"] * 9, settings=settings)
        # 第 1 轮报错（消耗唯一修复轮）→ 第 2 轮再报错 → 冻结 → 循环终止
        feedback = ScriptedFeedback(["报错：NameError", "还是报错"])
        result = pipeline.run(feedback_fn=feedback, **_RUN_KWARGS)
        assert result.kind == "team_flow"
        assert "已知问题" in result.deliverable_summary
        assert len(feedback.prompts) == 2  # 冻结后不再征询

    def test_researcher_hint_after_two_failed_rounds(self, fm):
        # 3.8/4.5：连续修复 ≥2 轮未确认成功 → 提示建议 Researcher 调研
        from tests.test_pipeline import team_scripts

        scripts = (
            team_scripts()
            + [_SIMPLE_FIX, _SIMPLE_FIX, _AUTH_FIX]   # 第 1 轮报错的修复
            + [_SIMPLE_FIX, _SIMPLE_FIX, _AUTH_FIX]   # 第 2 轮报错的修复
        )
        pipeline = _team_pipeline(fm, scripts, ["SKIPPED"] * 15)
        feedback = ScriptedFeedback(["报错A", "报错B", "运行成功"])
        result = pipeline.run(feedback_fn=feedback, **_RUN_KWARGS)
        assert result.kind == "team_flow"
        # 第 3 轮 prompt（两轮修复后）应含 Researcher 建议
        assert "Researcher" in feedback.prompts[2]


class TestFeedbackBudgetStop:
    def test_budget_exceeded_in_feedback_round(self, fm):
        # 11.0：反馈修复轮同样受总预算约束 → 中止落盘
        from tests.test_pipeline import team_scripts

        # 前置 15 次调用 × 15 token = 225；预算 240 →
        # 反馈轮第 1 个模块修复（+15=240）后，第 2 个模块修复前被拦
        scripts = team_scripts() + [_SIMPLE_FIX]
        settings = Settings(max_task_tokens=240)
        # 初次 3 + data 修复轮 2 + user 修复轮 1（在修复前被预算拦截）
        pipeline = _team_pipeline(fm, scripts, ["SKIPPED"] * 6, settings=settings)
        feedback = ScriptedFeedback(["报错：失败"])
        result = pipeline.run(feedback_fn=feedback, **_RUN_KWARGS)
        assert result.kind == "budget_exceeded"
        handle = fm.get_project(result.project_id)
        report = (handle.root / "sessions" / "budget_stop.md").read_text(encoding="utf-8")
        assert "反馈修复" in report
