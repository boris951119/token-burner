"""M15-8 回归：修复轮测试重写（过度规格解药）+ 契约私有化防护。

依据：V3 全量基准第一轮取证（logs/bench_v1/full/bench_report.json，
26/55=47%）——29 个 FROZEN 中断言失败 16、接口门禁 extra 7、收集错误 4。
两个代表性铁证：
- T1/passmint_scorer：测试 import DefaultScoringRule，代码实现为
  _DefaultScoringRule（私有化误伤契约符号）；
- T1/passmint_history：17/18 通过，仅 1 个平台相关权限断言拖死整模块。
"""

from __future__ import annotations

from app.config import Settings
from app.agents.dev_loop import DevLoopEngine, ModuleStatus
from app.tools.file_manager import FileManager
from app.utils.model_client import LLMResponse

CONTRACT = {
    "exports": ["score_password"],
    "public_api": ["score_password(password) -> int"],
    "dependencies": [],
}


class ScriptedLLM:
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append({"model": model, "messages": messages})
        return LLMResponse(
            model=model, content=self.scripts.pop(0),
            input_tokens=1, output_tokens=1,
        )


class FakeExecutor:
    """FAILED/TIMEOUT 之外的编排；runs 记录每次执行。"""

    def __init__(self, statuses):
        self.statuses = list(statuses)

    def run(self, code, tests, timeout, expected_output="", module=""):
        from app.execution.executor import ExecutionResult, ExecutionStatus
        status = self.statuses.pop(0) if self.statuses else "SUCCESS"
        # FAILED 对齐真实 pytest 语义：exit_code=1（M15-8 触发条件依赖它）
        return ExecutionResult(
            status=ExecutionStatus(status),
            exit_code=1 if status == "FAILED" else None,
            message="",
        )


def make_engine(llm, fm, executor) -> DevLoopEngine:
    return DevLoopEngine(
        llm=llm, dev_model="dev", test_model="test",
        executor=executor,
        settings=Settings(logic_review_enabled=False),
        file_manager=fm,
    )


def user_text(call):
    return call["messages"][-1]["content"]


GOOD_CODE = "def score_password(password: str) -> int:\n    return 80\n"
BAD_TESTS = "from score_pw import score_password\n\ndef test_ok():\n    assert score_password('a') == 1\n"
GOOD_TESTS = "from score_pw import score_password\n\ndef test_ok():\n    assert score_password('a') == 80\n"
GOOD_CODE2 = "def score_password(password: str) -> int:\n    return 80\n\n\ndef extra():\n    return 1\n"


class TestRound3TestRewrite:
    def test_assertion_failure_round3_rewrites_tests(self, tmp_path):
        """exit_code=1 连续 3 轮 → 第 3 修复轮重写测试（M15-8 核心行为）。"""
        fm = FileManager(projects_root=tmp_path / "p")
        llm = ScriptedLLM([GOOD_CODE, BAD_TESTS, GOOD_CODE, GOOD_CODE, GOOD_TESTS])
        engine = make_engine(
            llm, fm, FakeExecutor(["FAILED", "FAILED", "FAILED", "SUCCESS"]))
        pid = fm.create_project("demo").project_id
        result = engine.run_module("score_pw", project_id=pid, contract=CONTRACT)
        assert result.status is ModuleStatus.SUCCESS
        models = [c["model"] for c in llm.calls]
        # dev(写码) → test(写测试) → 修复1(dev) → 修复2(dev) → 修复3=重写测试(test)
        assert models == ["dev", "test", "dev", "dev", "test"]
        rewrite = user_text(llm.calls[4])
        assert "过度规格" in rewrite
        assert "禁止断言平台相关行为" in rewrite
        assert "保持契约覆盖不变" in rewrite

    def test_exit_code_2_still_fixes_code(self, tmp_path):
        """收集错误(exit_code=2)不触发测试重写——仍走修代码路径。"""
        fm = FileManager(projects_root=tmp_path / "p")
        llm = ScriptedLLM([GOOD_CODE, BAD_TESTS, GOOD_CODE])
        engine = make_engine(
            llm, fm, FakeExecutor(["FAILED", "SUCCESS"]))
        pid = fm.create_project("demo").project_id
        result = engine.run_module("score_pw", project_id=pid, contract=CONTRACT)
        assert result.status is ModuleStatus.SUCCESS
        models = [c["model"] for c in llm.calls]
        assert models == ["dev", "test", "dev"]

    def test_early_success_never_rewrites(self, tmp_path):
        fm = FileManager(projects_root=tmp_path / "p")
        llm = ScriptedLLM([GOOD_CODE, GOOD_TESTS])
        engine = make_engine(llm, fm, FakeExecutor(["SUCCESS"]))
        pid = fm.create_project("demo").project_id
        result = engine.run_module("score_pw", project_id=pid, contract=CONTRACT)
        assert result.status is ModuleStatus.SUCCESS
        assert len(llm.calls) == 2


class TestPrivatizationGuard:
    def test_contract_prompt_warns_against_underscore(self, tmp_path):
        from app.tools.file_manager import FileManager

        fm = FileManager(projects_root=tmp_path / "p")
        llm = ScriptedLLM(["x = 1"])
        engine = make_engine(llm, fm, FakeExecutor([]))
        engine._write_code(
            "score_pw", "评分",
            contract={"exports": ["score_password"],
                      "public_api": ["score_password(password) -> int"]},
        )
        text = user_text(llm.calls[0])
        assert "禁止加下划线前缀" in text
        assert "_X 不满足 X 的契约" in text

    def test_write_tests_template_bans_platform_assertions(self):
        from app.tools.prompt_templates import WRITE_TESTS_USER

        assert "平台相关行为" in WRITE_TESTS_USER
        assert "权限位" in WRITE_TESTS_USER
