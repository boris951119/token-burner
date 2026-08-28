"""12.7 修复时同步更新模块文档测试（TDD 先行）。

规格依据（v0.3.1 12.7 节，文档即代码原则）：
- 修复循环修改模块代码时，modules/<module>.md 须同步更新，
  使模块文档始终反映当前实现状态；
- 同步内容（程序确定性追加，无 LLM 调用）：
  · 「修复记录」章节：每次修复追加一条（轮次 + 失败摘要 + 时间）；
  · 「当前状态」章节：终态（SUCCESS / FROZEN / AWAITING_FEEDBACK）
    时整节替换（幂等，重跑不重复堆积）。
"""

from __future__ import annotations

import pytest

from app.agents.dev_loop import DevLoopEngine, ModuleStatus
from app.config import Settings
from app.utils.model_client import LLMResponse


# ---------------------------------------------------------------------------
# 桩
# ---------------------------------------------------------------------------


class ScriptedLLM:
    def __init__(self, scripts: list[str] | None = None):
        self.scripts = list(scripts or [])

    def chat(self, model, messages, json_mode=False):
        content = self.scripts.pop(0) if self.scripts else "print('default')"
        return LLMResponse(model=model, content=content, input_tokens=10, output_tokens=5)


class FakeExecutor:
    def __init__(self, statuses: list[str]):
        self.statuses = list(statuses)

    def run(self, code, tests, timeout, expected_output="", module=""):
        from app.execution.executor import ExecutionResult, ExecutionStatus

        status = self.statuses.pop(0) if self.statuses else "SUCCESS"
        return ExecutionResult(status=ExecutionStatus(status))


@pytest.fixture
def fm(tmp_path):
    from app.tools.file_manager import FileManager

    return FileManager(projects_root=tmp_path / "projects")


def _create_with_module_md(fm) -> str:
    """创建项目并预生成 modules/user.md（模拟拆分阶段落盘）。"""
    project_id = fm.create_project("demo").project_id
    handle = fm.get_project(project_id)
    (handle.root / "modules" / "user.md").write_text(
        "# 模块 user\n\n## 职责\n用户管理\n\n## 依赖\n- data\n\n## 优先级\n1\n",
        encoding="utf-8",
    )
    return project_id


def _module_md(fm, project_id: str) -> str:
    handle = fm.get_project(project_id)
    return (handle.root / "modules" / "user.md").read_text(encoding="utf-8")


def make_engine(llm, executor, fm, settings=None) -> DevLoopEngine:
    return DevLoopEngine(
        llm=llm,
        dev_model="deepseek-chat",
        test_model="claude-3-5-sonnet",
        executor=executor,
        settings=settings or Settings(),
        file_manager=fm,
    )


def _ok_code() -> str:
    return "def core_fn():\n    return 1\n"


def _ok_tests() -> str:
    return "from user import core_fn\n\n\ndef test_ok():\n    assert core_fn() == 1\n"


# ---------------------------------------------------------------------------
# 修复记录追加（12.7）
# ---------------------------------------------------------------------------


class TestFixRecordSync:
    def test_fix_round_appends_record_to_module_md(self, fm):
        # 修复一轮 → modules/user.md 追加「修复记录」条目（文档即代码）
        project_id = _create_with_module_md(fm)
        llm = ScriptedLLM([_ok_code(), _ok_tests(), "FIXED_CODE"])
        executor = FakeExecutor(["FAILED", "SUCCESS"])
        engine = make_engine(llm, executor, fm)
        result = engine.run_module("user", project_id=project_id)
        assert result.status is ModuleStatus.SUCCESS
        md = _module_md(fm, project_id)
        assert "## 修复记录" in md
        assert "第 1 次修复" in md
        # 原有职责/依赖章节保留（追加而非覆写）
        assert "## 职责" in md and "## 依赖" in md

    def test_multiple_fix_rounds_accumulate(self, fm):
        # 多轮修复逐条追加（顺序递增）
        project_id = _create_with_module_md(fm)
        llm = ScriptedLLM([
            _ok_code(), _ok_tests(), "FIX_1", "FIX_2", "FIX_3",
        ])
        executor = FakeExecutor(["FAILED", "FAILED", "FAILED", "SUCCESS"])
        engine = make_engine(llm, executor, fm)
        result = engine.run_module("user", project_id=project_id)
        assert result.status is ModuleStatus.SUCCESS
        md = _module_md(fm, project_id)
        assert "第 1 次修复" in md
        assert "第 2 次修复" in md
        assert "第 3 次修复" in md

    def test_fix_record_contains_failure_digest(self, fm):
        # 修复记录含失败摘要（长报告截断，单行可读）
        project_id = _create_with_module_md(fm)
        llm = ScriptedLLM([_ok_code(), _ok_tests(), _ok_code()])
        executor = FakeExecutor(["FAILED", "SUCCESS"])
        engine = make_engine(llm, executor, fm)
        engine.run_module("user", project_id=project_id)
        md = _module_md(fm, project_id)
        assert "exit_code" in md  # 失败报告摘要可见

    def test_no_fix_no_record_section(self, fm):
        # 一次通过（零修复）→ 不追加修复记录章节
        project_id = _create_with_module_md(fm)
        llm = ScriptedLLM([_ok_code(), _ok_tests()])
        engine = make_engine(llm, FakeExecutor(["SUCCESS"]), fm)
        engine.run_module("user", project_id=project_id)
        md = _module_md(fm, project_id)
        assert "修复记录" not in md

    def test_missing_module_md_tolerated(self, fm):
        # modules/<module>.md 不存在（如部分流程未落盘）→ 不报错，流程正常
        project_id = fm.create_project("demo").project_id
        llm = ScriptedLLM([_ok_code(), _ok_tests(), _ok_code()])
        executor = FakeExecutor(["FAILED", "SUCCESS"])
        engine = make_engine(llm, executor, fm)
        result = engine.run_module("user", project_id=project_id)
        assert result.status is ModuleStatus.SUCCESS  # 容错不中断


# ---------------------------------------------------------------------------
# 当前状态章节（终态同步，幂等）
# ---------------------------------------------------------------------------


class TestStatusSectionSync:
    def test_success_writes_current_status(self, fm):
        # 终态 SUCCESS → 「当前状态」章节记录状态与修复次数
        project_id = _create_with_module_md(fm)
        llm = ScriptedLLM([_ok_code(), _ok_tests()])
        engine = make_engine(llm, FakeExecutor(["SUCCESS"]), fm)
        engine.run_module("user", project_id=project_id)
        md = _module_md(fm, project_id)
        assert "## 当前状态" in md
        assert "SUCCESS" in md

    def test_status_section_idempotent(self, fm):
        # 状态章节整节替换（重跑/多终态不重复堆积）
        project_id = _create_with_module_md(fm)
        llm = ScriptedLLM([_ok_code(), _ok_tests()])
        engine = make_engine(llm, FakeExecutor(["SUCCESS"]), fm)
        engine.run_module("user", project_id=project_id)
        engine.run_module("user", project_id=project_id)  # 二次运行
        md = _module_md(fm, project_id)
        assert md.count("## 当前状态") == 1

    def test_frozen_status_written(self, fm):
        # 冻结终态同样写入（含已知问题提示）
        project_id = _create_with_module_md(fm)
        settings = Settings(max_fix_rounds=1)
        llm = ScriptedLLM([_ok_code(), _ok_tests(), _ok_code()])
        engine = make_engine(llm, FakeExecutor(["FAILED", "FAILED"]), fm, settings=settings)
        result = engine.run_module("user", project_id=project_id)
        assert result.status is ModuleStatus.FROZEN
        md = _module_md(fm, project_id)
        assert "## 当前状态" in md and "FROZEN" in md

    def test_awaiting_feedback_status_written(self, fm):
        # 3.8：等待用户反馈也是可观测终态 → 状态章节同步
        project_id = _create_with_module_md(fm)
        llm = ScriptedLLM([_ok_code(), _ok_tests()])
        engine = make_engine(llm, FakeExecutor(["SKIPPED"]), fm)
        result = engine.run_module("user", project_id=project_id)
        assert result.status is ModuleStatus.AWAITING_FEEDBACK
        md = _module_md(fm, project_id)
        assert "AWAITING_FEEDBACK" in md


# ---------------------------------------------------------------------------
# 反馈闭环轮同步（3.8 × 12.7）
# ---------------------------------------------------------------------------


class TestFeedbackRoundSync:
    def test_feedback_fix_round_syncs_module_md(self, fm):
        # 反馈轮修复同样追加修复记录 + 状态更新
        project_id = _create_with_module_md(fm)
        llm = ScriptedLLM([_ok_code(), _ok_tests(), "FIX_1"])
        engine = make_engine(
            llm, FakeExecutor(["SKIPPED", "SKIPPED", "SKIPPED"]), fm
        )
        awaiting = engine.run_module("user", project_id=project_id)
        assert awaiting.status is ModuleStatus.AWAITING_FEEDBACK
        result = engine.resume_with_feedback(
            "user", awaiting, "报错：NameError", project_id=project_id
        )
        assert result.status is ModuleStatus.AWAITING_FEEDBACK
        md = _module_md(fm, project_id)
        assert "第 1 次修复" in md          # 反馈轮修复已记录
        assert "AWAITING_FEEDBACK" in md    # 状态同步

    def test_feedback_success_updates_status(self, fm):
        # 用户确认成功 → 状态章节更新为 SUCCESS
        project_id = _create_with_module_md(fm)
        llm = ScriptedLLM([_ok_code(), _ok_tests()])
        engine = make_engine(llm, FakeExecutor(["SKIPPED"]), fm)
        awaiting = engine.run_module("user", project_id=project_id)
        engine.resume_with_feedback(
            "user", awaiting, "手动运行成功", project_id=project_id
        )
        md = _module_md(fm, project_id)
        assert "SUCCESS" in md
        assert "AWAITING_FEEDBACK" not in md  # 旧状态被替换
