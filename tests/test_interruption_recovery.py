"""中断恢复测试（产品审计问题 4 修复，TDD 先行）。

问题：崩溃 / Ctrl+C 后零恢复——budget_stop.md 承诺「续跑」但程序上
不存在续跑入口；讨论/开发中断 = 已耗 token 全部作废。

修复约定：
- run() 进入模块开发前落盘 sessions/pipeline_state.json（恢复所需的
  最小充分状态：order / plans / interfaces / mode / models）；
- KeyboardInterrupt → 落盘 sessions/interruption.md（阶段/已完成/
  未完成/指引）并返回 kind="interrupted"；意外 Exception → 同样
  落盘后 re-raise（bug 暴露不吞）；
- Pipeline.resume(project_id)：从磁盘重建状态——validation.md 判定
  模块终态（SUCCESS 跳过、AWAITING_FEEDBACK 进反馈环、其余重跑），
  只对未完成模块消耗 LLM 调用，续走开发循环 → 交付。
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.pipeline import Pipeline
from app.tools.file_manager import FileManager


def _resp(content: str):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


class ScriptedLLM:
    def __init__(self, scripts, raise_at=None, exc=None):
        self.scripts = list(scripts)
        self.raise_at = raise_at   # 第 N 次调用（1-based）抛 exc
        self.exc = exc or KeyboardInterrupt()
        self.calls = 0
        self.call_log = []

    def chat(self, model, messages, json_mode=False, **kw):
        from app.utils.model_client import LLMResponse
        self.calls += 1
        if self.raise_at is not None and self.calls == self.raise_at:
            raise self.exc
        content = self.scripts.pop(0) if self.scripts else "ok"
        return LLMResponse(model=model, content=content,
                           input_tokens=10, output_tokens=5)


class FakeExecutor:
    def __init__(self, statuses=None):
        self.statuses = list(statuses or [])

    def run(self, code, tests, timeout, expected_output="", module=""):
        from app.execution.executor import ExecutionResult, ExecutionStatus
        status = self.statuses.pop(0) if self.statuses else "SUCCESS"
        return ExecutionResult(status=ExecutionStatus(status))


def _assessment():
    return json.dumps({"difficulty_score": 7, "difficulty_level": "中",
                       "task_type": "编程", "reason": "多模块",
                       "estimated_files": 7}, ensure_ascii=False)


def _review():
    return json.dumps({"scores": {"feasibility": 9, "security": 9, "maintainability": 9},
                       "strengths": ["ok"], "weaknesses": [], "risks": []},
                      ensure_ascii=False)


def _split(modules):
    return json.dumps({"modules": modules}, ensure_ascii=False)


def _iface(deps=()):
    return json.dumps({"imports": [], "exports": ["core_fn"],
                       "public_api": ["core_fn"], "dependencies": list(deps)},
                      ensure_ascii=False)


_TWO_MODULE_SCRIPTS = [
    _assessment(), "初始方案", _review(), _review(), "最终 spec",
    _split([
        {"name": "user", "responsibility": "用户", "dependencies": [], "priority": 1},
        {"name": "auth", "responsibility": "认证", "dependencies": ["user"], "priority": 2},
    ]),
    _iface(), _iface(["user"]),
    "def core_fn():\n    return 1\n",   # user 代码
    "TEST_user",                        # user 测试
]


def _pipeline(llm, fm, executor=None):
    return Pipeline(llm=llm, executor=executor or FakeExecutor(),
                    settings=Settings(), file_manager=fm)


# ---------------------------------------------------------------------------
# 中断快照：KeyboardInterrupt → interruption.md + interrupted 结果
# ---------------------------------------------------------------------------


class TestInterruptionSnapshot:
    def test_keyboard_interrupt_persists_report(self, tmp_path):
        # auth 代码生成时（第 11 次调用）中断 → 落盘 + kind=interrupted
        fm = FileManager(projects_root=tmp_path / "projects")
        llm = ScriptedLLM(_TWO_MODULE_SCRIPTS + ["auth code"],
                          raise_at=11, exc=KeyboardInterrupt())
        result = _pipeline(llm, fm).run(
            "双模块系统", models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe", spec_confirm="确认",
        )
        assert result.kind == "interrupted"
        root = fm.get_project(result.project_id).root
        report = (root / "sessions" / "interruption.md").read_text(encoding="utf-8")
        assert "模块开发" in report     # 中断阶段
        assert "user" in report         # 已完成部分
        assert "auth" in report         # 未完成清单

    def test_state_snapshot_before_module_dev(self, tmp_path):
        # 进入模块开发前落盘 pipeline_state.json（恢复的最小充分状态）
        fm = FileManager(projects_root=tmp_path / "projects")
        llm = ScriptedLLM(_TWO_MODULE_SCRIPTS + ["auth code", "TEST_auth"],
                          raise_at=13, exc=KeyboardInterrupt())
        result = _pipeline(llm, fm).run(
            "双模块系统", models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe", spec_confirm="确认",
        )
        root = fm.get_project(result.project_id).root
        state = json.loads(
            (root / "sessions" / "pipeline_state.json").read_text(encoding="utf-8")
        )
        assert state["order"] == ["user", "auth"]
        assert {p["name"] for p in state["plans"]} == {"user", "auth"}
        assert "user" in state["interfaces"]       # 契约可重建
        assert state["mode"] == "safe"
        assert state["models"][0] == "gpt-4o"

    def test_unexpected_exception_persisted_then_reraised(self, tmp_path):
        # 意外异常：先落盘现场再 re-raise（bug 暴露，不吞）
        fm = FileManager(projects_root=tmp_path / "projects")
        llm = ScriptedLLM(_TWO_MODULE_SCRIPTS + ["auth code"],
                          raise_at=11, exc=RuntimeError("boom"))
        pipeline = _pipeline(llm, fm)
        with pytest.raises(RuntimeError, match="boom"):
            pipeline.run("双模块系统",
                         models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
                         mode="safe", spec_confirm="确认")
        # 现场已落盘（恢复信息不丢失）
        projects = list((tmp_path / "projects").iterdir())
        report = (projects[0] / "sessions" / "interruption.md").read_text(encoding="utf-8")
        assert "RuntimeError" in report

    def test_budget_guard_detached_after_interrupt(self, tmp_path):
        # 中断后护栏卸载（不污染同客户端后续任务）
        fm = FileManager(projects_root=tmp_path / "projects")
        llm = ScriptedLLM(_TWO_MODULE_SCRIPTS + ["auth code"],
                          raise_at=11, exc=KeyboardInterrupt())
        _pipeline(llm, fm).run(
            "双模块系统", models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe", spec_confirm="确认",
        )
        assert llm.budget_guard is None


# ---------------------------------------------------------------------------
# resume：磁盘重建状态，只跑未完成模块
# ---------------------------------------------------------------------------


def _prepare_interrupted_project(tmp_path):
    """跑一个真实中断的项目（user 完成、auth 未开始）。"""
    fm = FileManager(projects_root=tmp_path / "projects")
    llm = ScriptedLLM(_TWO_MODULE_SCRIPTS + ["auth code"],
                      raise_at=11, exc=KeyboardInterrupt())
    result = _pipeline(llm, fm).run(
        "双模块系统", models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
        mode="safe", spec_confirm="确认",
    )
    assert result.kind == "interrupted"
    return fm, result.project_id


class TestResume:
    def test_resume_only_runs_pending_modules(self, tmp_path):
        # user 已 SUCCESS → 不再为其消耗 LLM 调用；auth 重跑并交付
        fm, project_id = _prepare_interrupted_project(tmp_path)
        root = fm.get_project(project_id).root

        # 恢复用的 LLM：只需 auth 的 2 次调用（代码 + 测试）
        resume_llm = ScriptedLLM([
            "def core_fn():\n    return 2\n", "TEST_auth",
        ])
        feedbacks = iter(["成功"])
        result = _pipeline(resume_llm, fm).resume(
            project_id, feedback_fn=lambda p: next(feedbacks),
        )
        assert result.kind == "team_flow"
        assert resume_llm.calls == 2          # 仅 auth 的代码+测试
        assert "user" in result.deliverable_summary
        assert "auth" in result.deliverable_summary
        # 中断报告被清理（任务已完成）
        assert not (root / "sessions" / "interruption.md").exists()

    def test_resume_awating_module_enters_feedback_loop(self, tmp_path):
        # AWAITING_FEEDBACK 模块：不重新生成代码，直接进反馈环
        fm = FileManager(projects_root=tmp_path / "projects")
        project_id = fm.create_project("反馈恢复").project_id
        root = fm.get_project(project_id).root
        # 手工搭状态：state.json + main 模块 AWAITING
        (root / "sessions" / "pipeline_state.json").write_text(json.dumps({
            "order": ["main"], "plans": [
                {"name": "main", "responsibility": "全部", "dependencies": [], "priority": 1},
            ],
            "interfaces": {}, "mode": "safe",
            "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
        }, ensure_ascii=False), encoding="utf-8")
        (root / "changelog" / "main").mkdir(parents=True)
        (root / "changelog" / "main" / "validation.md").write_text(
            "# 模块 main 验证报告\n\n- 最终状态: AWAITING_FEEDBACK\n- 修复次数: 0\n",
            encoding="utf-8",
        )
        (root / "code" / "main").mkdir(parents=True)
        (root / "code" / "main" / "main.py").write_text("x = 1\n", encoding="utf-8")
        (root / "tests" / "main").mkdir(parents=True)
        (root / "tests" / "main" / "test_main.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")

        resume_llm = ScriptedLLM([])  # 零 LLM 调用预期
        feedbacks = iter(["运行成功，无报错"])
        result = _pipeline(resume_llm, fm).resume(
            project_id, feedback_fn=lambda p: next(feedbacks),
        )
        assert result.kind == "team_flow"
        assert resume_llm.calls == 0    # 成功反馈 → 不消耗任何调用
        assert "完成" in result.deliverable_summary

    def test_resume_without_state_raises(self, tmp_path):
        # 无 pipeline_state.json（如中断发生在拆分前）→ 明确报错
        fm = FileManager(projects_root=tmp_path / "projects")
        project_id = fm.create_project("无状态").project_id
        with pytest.raises(ValueError, match="pipeline_state"):
            _pipeline(ScriptedLLM([]), fm).resume(project_id)

    def test_resume_frozen_module_kept_frozen(self, tmp_path):
        # FROZEN 模块：保持冻结不重跑（保留现场，交用户决定）
        fm = FileManager(projects_root=tmp_path / "projects")
        project_id = fm.create_project("冻结恢复").project_id
        root = fm.get_project(project_id).root
        (root / "sessions" / "pipeline_state.json").write_text(json.dumps({
            "order": ["user", "auth"], "plans": [
                {"name": "user", "responsibility": "用户", "dependencies": [], "priority": 1},
                {"name": "auth", "responsibility": "认证", "dependencies": ["user"], "priority": 2},
            ],
            "interfaces": {}, "mode": "safe",
            "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
        }, ensure_ascii=False), encoding="utf-8")
        for name, status in (("user", "SUCCESS"), ("auth", "FROZEN")):
            (root / "changelog" / name).mkdir(parents=True)
            (root / "changelog" / name / "validation.md").write_text(
                f"# 模块 {name} 验证报告\n\n- 最终状态: {status}\n- 修复次数: 5\n",
                encoding="utf-8",
            )
        resume_llm = ScriptedLLM([])
        result = _pipeline(resume_llm, fm).resume(project_id)
        assert result.kind == "team_flow"
        assert resume_llm.calls == 0          # 两模块均不重跑
        assert result.frozen_modules == ["auth"]
        assert "auth" in result.deliverable_summary
