"""M15-6 回归：测试侧绑定门禁 + 测试再生修复分支。

依据：bench_v1 round-3 取证（logs/bench_v1/pilot_r3/T2_bench.json）——
T2 六模块中三个（analytics/cli/export）冻结于同一签名：测试文件只
import pytest/mock 等第三方库，裸调用被测函数（NameError），修复循环
只修代码不修测试，5 轮震荡后冻结。修复：执行前 AST 校验契约符号在
测试中已绑定，未绑定 → 只重新生成测试（携带缺陷清单），代码不动。
"""

from __future__ import annotations

from app.utils.test_check import check_test_bindings
from app.config import Settings
from app.agents.dev_loop import DevLoopEngine, ModuleStatus
from app.tools.file_manager import FileManager
from app.utils.model_client import LLMResponse

CONTRACT = {
    "exports": ["evaluate_password_strength"],
    "public_api": ["evaluate_password_strength(password) -> int"],
    "dependencies": [],
}

CODE = "def evaluate_password_strength(password: str) -> int:\n    return 80\n"

GOOD_TESTS = (
    "from evaluate_check import evaluate_password_strength\n"
    "def test_ok():\n"
    "    assert evaluate_password_strength('a') == 80\n"
)
BAD_TESTS = (
    "import pytest\n"
    "def test_bare():\n"
    "    assert evaluate_password_strength('a') == 80\n"
)


class ScriptedLLM:
    def __init__(self, scripts: list[str]):
        self.scripts = list(scripts)
        self.calls: list[dict] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append({"model": model, "messages": messages})
        content = self.scripts.pop(0) if self.scripts else "print('default')"
        return LLMResponse(model=model, content=content, input_tokens=10, output_tokens=5)


class FakeExecutor:
    def __init__(self, statuses: list[str]):
        self.statuses = list(statuses)

    def run(self, code, tests, timeout, expected_output="", module=""):
        from app.execution.executor import ExecutionResult, ExecutionStatus
        status = self.statuses.pop(0) if self.statuses else "SUCCESS"
        return ExecutionResult(status=ExecutionStatus(status), message="")


def make_engine(llm, fm) -> DevLoopEngine:
    return DevLoopEngine(
        llm=llm,
        dev_model="dev-model",
        test_model="test-model",
        executor=FakeExecutor(["SUCCESS"]),
        settings=Settings(logic_review_enabled=False),
        file_manager=fm,
    )


def user_text(call: dict) -> str:
    return call["messages"][-1]["content"]


class TestCheckTestBindings:
    def test_bare_reference_flagged(self):
        issues = check_test_bindings(BAD_TESTS, "evaluate_check", CONTRACT)
        assert len(issues) == 1
        assert "evaluate_password_strength" in issues[0]
        assert "from evaluate_check import evaluate_password_strength" in issues[0]

    def test_from_import_clean(self):
        assert check_test_bindings(GOOD_TESTS, "evaluate_check", CONTRACT) == []

    def test_star_import_clean(self):
        tests = "from evaluate_check import *\ndef test_ok():\n    return 1\n"
        assert check_test_bindings(tests, "evaluate_check", CONTRACT) == []

    def test_no_contract_noop(self):
        assert check_test_bindings(BAD_TESTS, "evaluate_check", None) == []
        assert check_test_bindings(BAD_TESTS, "evaluate_check", {}) == []

    def test_syntax_error_flagged(self):
        issues = check_test_bindings("def broken(:\n", "evaluate_check", CONTRACT)
        assert issues and "语法错误" in issues[0]

    def test_builtin_name_not_flagged(self):
        # 契约符号与内建重名不误报（ conservatively bound via builtins）
        issues = check_test_bindings(
            "def test_ok():\n    return min(1, 2)\n",
            "evaluate_check",
            {"exports": ["min"], "public_api": []},
        )
        assert issues == []

    def test_public_api_name_extracted(self):
        # exports 缺失时 public_api 首名也纳入校验
        issues = check_test_bindings(
            BAD_TESTS, "evaluate_check",
            {"exports": [], "public_api": ["evaluate_password_strength(password) -> int"]},
        )
        assert len(issues) == 1


class TestTestGateInDrive:
    def test_bad_binding_triggers_test_regen_not_code_fix(self, tmp_path):
        fm = FileManager(projects_root=tmp_path / "p")
        llm = ScriptedLLM([CODE, BAD_TESTS, GOOD_TESTS])
        engine = make_engine(llm, fm)
        project_id = fm.create_project("demo").project_id
        result = engine.run_module(
            "evaluate_check", project_id=project_id, contract=CONTRACT,
        )
        assert result.status == ModuleStatus.SUCCESS
        # 三次调用：写代码(dev) → 写测试(test) → 测试再生(test)
        models = [c["model"] for c in llm.calls]
        assert models == ["dev-model", "test-model", "test-model"]
        # 再生提示词携带缺陷清单与契约段；代码未被修复调用触碰
        regen = user_text(llm.calls[2])
        assert "上一版测试缺陷" in regen
        assert "测试导入门禁（M15-6）" in regen
        assert "模块接口契约" in regen
        assert "from evaluate_check import evaluate_password_strength" in regen

    def test_good_binding_single_pass(self, tmp_path):
        fm = FileManager(projects_root=tmp_path / "p")
        llm = ScriptedLLM([CODE, GOOD_TESTS])
        engine = make_engine(llm, fm)
        project_id = fm.create_project("demo").project_id
        result = engine.run_module(
            "evaluate_check", project_id=project_id, contract=CONTRACT,
        )
        assert result.status == ModuleStatus.SUCCESS
        assert [c["model"] for c in llm.calls] == ["dev-model", "test-model"]


CLASS_TESTS = (
    "import pytest\n"
    "class TestEval:\n"
    "    def test_inner(self):\n"
    "        assert True\n"
    "def test_bare_call():\n"
    "    assert evaluate_password_strength('a') == 80\n"
)


class TestRound4Regression:
    def test_classdef_does_not_crash(self):
        """round-4 T3 取证：ClassDef 分支曾 AttributeError 炸死任务。"""
        issues = check_test_bindings(CLASS_TESTS, "evaluate_check", CONTRACT)
        # 类定义不崩溃；裸调用的契约符号仍被精确拦截
        assert len(issues) == 1
        assert "evaluate_password_strength" in issues[0]

    def test_class_only_tests_clean(self):
        tests = (
            "from evaluate_check import evaluate_password_strength\n"
            "class TestEval:\n"
            "    def test_inner(self):\n"
            "        assert evaluate_password_strength('a') == 80\n"
        )
        assert check_test_bindings(tests, "evaluate_check", CONTRACT) == []

    def test_gate_exception_degrades_open(self, tmp_path, monkeypatch):
        """门禁自身异常 → 降级放行（不杀任务，不进测试再生）。"""
        import app.utils.test_check as tc

        def boom(*a, **kw):
            raise RuntimeError("gate internal error")

        monkeypatch.setattr(tc, "check_test_bindings", boom)
        fm = FileManager(projects_root=tmp_path / "p")
        llm = ScriptedLLM([CODE, BAD_TESTS])
        engine = make_engine(llm, fm)
        project_id = fm.create_project("demo").project_id
        result = engine.run_module(
            "evaluate_check", project_id=project_id, contract=CONTRACT,
        )
        # 门禁炸了也照常走执行（FakeExecutor SUCCESS），无再生调用
        assert result.status == ModuleStatus.SUCCESS
        assert [c["model"] for c in llm.calls] == ["dev-model", "test-model"]
