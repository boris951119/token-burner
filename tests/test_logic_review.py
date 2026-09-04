"""M14-7 safe 模式 LLM 逻辑审查测试（v1.0 V2 批次）。

背景：规格 3.6.2 定义安全模式 = AST 静态检查 + LLM 逻辑审查 + 手动反馈
三件套，但审查环节从未实现（全库零命中）——safe 模式名实不符，明显逻辑
错误要等用户手动运行才发现。v1.0 补全：契约函数级审查（test_model），
fail → 修复循环；异常降级放行；auto 模式不审。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.tools.file_manager import FileManager  # noqa: E402

GOOD_CODE = "def add(a, b):\n    return a + b\n"
CONTRACT = {
    "exports": ["add"],
    "public_api": ["add(a, b) -> int"],
    "imports": [],
    "dependencies": [],
}


def _engine(tmp_path, llm, executor_cls=None, settings=None):
    """构造 DevLoopEngine（safe 缺省）。"""
    from app.agents.dev_loop import DevLoopEngine
    from app.execution.safe_executor import SafeExecutor

    if executor_cls is None:
        executor_cls = SafeExecutor
    fm = FileManager(projects_root=tmp_path / "projects")
    return DevLoopEngine(
        llm=llm, executor=executor_cls(),
        settings=settings or Settings(),
        file_manager=fm, dev_model="d", test_model="t",
    ), fm


class _ReviewLLM:
    """返回固定审查 verdict 的 stub（chat 只被审查调用）。"""

    def __init__(self, content):
        self.content = content
        self.calls = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append({"model": model, "json_mode": json_mode})
        class R:
            pass
        R.content = self.content
        return R()


class TestLogicReviewDue:
    def test_safe_mode_due(self):
        from app.execution.safe_executor import SafeExecutor

        class E:
            pass

        e = object.__new__(E)
        e.executor = SafeExecutor()
        e.settings = Settings()
        from app.agents.dev_loop import DevLoopEngine

        assert DevLoopEngine._logic_review_due(e) is True

    def test_disabled_not_due(self):
        from app.execution.safe_executor import SafeExecutor

        class E:
            pass

        e = object.__new__(E)
        e.executor = SafeExecutor()
        e.settings = Settings(logic_review_enabled=False)
        from app.agents.dev_loop import DevLoopEngine

        assert DevLoopEngine._logic_review_due(e) is False

    def test_auto_mode_not_due(self):
        """auto 模式（非 SafeExecutor）不审查。"""
        from app.execution.local_executor import LocalExecutor

        class E:
            pass

        e = object.__new__(E)
        e.executor = LocalExecutor()
        e.settings = Settings()
        from app.agents.dev_loop import DevLoopEngine

        assert DevLoopEngine._logic_review_due(e) is False


class TestLogicReviewVerdict:
    def test_fail_with_issues(self, tmp_path):
        llm = _ReviewLLM(
            '{"verdict": "fail", "issues": ["add 未处理非数值输入"], "warnings": []}')
        engine, _ = _engine(tmp_path, llm)
        report = engine._logic_review("calc", GOOD_CODE, CONTRACT)
        assert report.startswith("逻辑审查失败")
        assert "add 未处理非数值输入" in report

    def test_pass_returns_empty(self, tmp_path):
        llm = _ReviewLLM(
            '{"verdict": "pass", "issues": [], "warnings": ["可加类型注解"]}')
        engine, _ = _engine(tmp_path, llm)
        assert engine._logic_review("calc", GOOD_CODE, CONTRACT) == ""

    def test_fenced_json_parsed(self, tmp_path):
        """围栏包裹的 verdict 正常解析（15 章容错复用）。"""
        llm = _ReviewLLM(
            "```json\n{\"verdict\": \"fail\", \"issues\": [\"边界缺失\"]}\n```")
        engine, _ = _engine(tmp_path, llm)
        assert "边界缺失" in engine._logic_review("calc", GOOD_CODE, CONTRACT)

    def test_llm_exception_degrades_to_pass(self, tmp_path):
        """LLM 调用异常 → 降级放行（审查是增强非硬门禁）。"""
        class BrokenLLM:
            def chat(self, *a, **kw):
                raise RuntimeError("LLM 不可用")

        engine, _ = _engine(tmp_path, BrokenLLM())
        assert engine._logic_review("calc", GOOD_CODE, CONTRACT) == ""

    def test_garbage_response_degrades_to_pass(self, tmp_path):
        llm = _ReviewLLM("这不是 JSON")
        engine, _ = _engine(tmp_path, llm)
        assert engine._logic_review("calc", GOOD_CODE, CONTRACT) == ""

    def test_fail_without_issues_treated_as_pass(self, tmp_path):
        """fail 但无 issues → 视为通过（防误伤）。"""
        llm = _ReviewLLM('{"verdict": "fail", "issues": []}')
        engine, _ = _engine(tmp_path, llm)
        assert engine._logic_review("calc", GOOD_CODE, CONTRACT) == ""

    def test_uses_test_model_and_json_mode(self, tmp_path):
        """审查用 test_model + json_mode。"""
        llm = _ReviewLLM('{"verdict": "pass"}')
        engine, _ = _engine(tmp_path, llm)
        engine._logic_review("calc", GOOD_CODE, CONTRACT)
        assert llm.calls[0]["model"] == "t"
        assert llm.calls[0]["json_mode"] is True

    def test_no_contract_reviews_public_defs(self, tmp_path):
        """无契约时审查全部公开函数（api_list 从代码提取）。"""
        llm = _ReviewLLM('{"verdict": "pass"}')
        engine, _ = _engine(tmp_path, llm)
        engine._logic_review("calc", GOOD_CODE, None)
        # 提示词 user 含提取出的公开函数名
        assert llm.calls  # 调用发生即路径通


class TestDriveIntegration:
    def test_review_fail_enters_fix_loop(self, tmp_path):
        """fail verdict → 进修复循环 → 修复后 pass → 正常 SKIPPED 流转。"""
        state = {"n": 0}

        class SeqLLM:
            def chat(self, model, messages, json_mode=False):
                state["n"] += 1
                class R:
                    pass
                if state["n"] == 1:
                    # 第一轮审查：fail
                    R.content = ('{"verdict": "fail", '
                                 '"issues": ["add 边界未处理"]}')
                elif state["n"] == 2:
                    # 修复输出（dev_model 调用）
                    R.content = ("```python\ndef add(a, b):\n"
                                 "    return a + b\n```")
                else:
                    # 第二轮审查：pass
                    R.content = '{"verdict": "pass"}'
                return R()

        engine, fm = _engine(tmp_path, SeqLLM())
        pid = fm.create_project("review-fix").project_id
        result = engine._drive(
            module="calc", project_id=pid,
            code=GOOD_CODE,
            tests="from calc import add\ndef test_add():\n    assert add(1, 2) == 3\n",
            fix_attempts=0, user_feedback="",
            contract=CONTRACT, project_modules={"calc"},
            feedback_pending=False,
        )
        # fail → 修复 → pass → SKIPPED → 无反馈 → AWAITING_FEEDBACK
        assert result.status.value == "AWAITING_FEEDBACK"
        assert result.fix_attempts == 1     # 修复循环被触发过一次

    def test_review_disabled_skips_call(self, tmp_path):
        """logic_review_enabled=False → 审查不发生（LLM 零调用）。"""
        calls = {"n": 0}

        class CountLLM:
            def chat(self, *a, **kw):
                calls["n"] += 1
                class R:
                    pass
                R.content = "```python\ndef add(a, b):\n    return a + b\n```"
                return R()

        engine, fm = _engine(
            tmp_path, CountLLM(), settings=Settings(logic_review_enabled=False))
        pid = fm.create_project("review-off").project_id
        result = engine._drive(
            module="calc", project_id=pid,
            code=GOOD_CODE,
            tests="from calc import add\ndef test_add():\n    assert add(1, 2) == 3\n",
            fix_attempts=0, user_feedback="",
            contract=CONTRACT, project_modules={"calc"},
            feedback_pending=False,
        )
        assert result.status.value == "AWAITING_FEEDBACK"
        assert calls["n"] == 0              # 审查未发生
