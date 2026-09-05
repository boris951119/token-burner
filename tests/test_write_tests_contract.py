"""M15-5 回归：写测试提示词必须注入接口契约。

依据：bench_v1 round-2f 取证（logs/bench_v1/pilot_r2/T1_bench.json）——
三个模块同签名冻结：测试 LLM 未见过契约，凭需求语义发明函数名
（calculate_strength / is_weak_password / generate_batch_passwords），
执行期 ImportError 后修复循环只修代码不修测试，与接口门禁来回
震荡 5 轮至 FROZEN。修复：契约的 public_api 注入 _write_tests 用户
提示词，测试调用强制按契约签名。
"""

from __future__ import annotations

from app.config import Settings
from app.agents.dev_loop import DevLoopEngine
from app.tools.file_manager import FileManager
from app.utils.model_client import LLMResponse

CONTRACT = {
    "exports": ["evaluate_password_strength", "is_password_strong"],
    "public_api": [
        "evaluate_password_strength(password) -> int",
        "is_password_strong(password, threshold=70) -> bool",
    ],
    "dependencies": [],
}

CODE = (
    "def evaluate_password_strength(password: str) -> int:\n"
    "    return 80\n"
    "\n"
    "def is_password_strong(password: str, threshold: int = 70) -> bool:\n"
    "    return True\n"
)


class CapturingLLM:
    """记录每次调用的 model 与 messages，按序返回脚本内容。"""

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


class TestContractInjection:
    def test_write_tests_prompt_contains_contract_api(self, tmp_path):
        llm = CapturingLLM(["TEST_CODE"])
        engine = make_engine(llm, FileManager(projects_root=tmp_path / "p"))
        engine._write_tests("strength_evaluator", CODE, contract=CONTRACT)
        text = user_text(llm.calls[0])
        assert "模块接口契约" in text
        assert "evaluate_password_strength(password) -> int" in text
        assert "is_password_strong(password, threshold=70) -> bool" in text

    def test_write_tests_without_contract_unchanged(self, tmp_path):
        llm = CapturingLLM(["TEST_CODE"])
        engine = make_engine(llm, FileManager(projects_root=tmp_path / "p"))
        engine._write_tests("strength_evaluator", CODE)
        assert "模块接口契约" not in user_text(llm.calls[0])

    def test_write_tests_empty_contract_unchanged(self, tmp_path):
        llm = CapturingLLM(["TEST_CODE"])
        engine = make_engine(llm, FileManager(projects_root=tmp_path / "p"))
        engine._write_tests("strength_evaluator", CODE, contract={"exports": []})
        assert "模块接口契约" not in user_text(llm.calls[0])

    def test_write_tests_falls_back_to_exports(self, tmp_path):
        llm = CapturingLLM(["TEST_CODE"])
        engine = make_engine(llm, FileManager(projects_root=tmp_path / "p"))
        engine._write_tests(
            "strength_evaluator", CODE,
            contract={"exports": ["evaluate_password_strength"]},
        )
        assert "- evaluate_password_strength" in user_text(llm.calls[0])

    def test_run_module_routes_contract_to_testgen_not_codegen(self, tmp_path):
        fm = FileManager(projects_root=tmp_path / "p")
        # M15-6 起，桩测试须绑定契约符号才能通过测试导入门禁
        test_code = (
            "from strength_evaluator import evaluate_password_strength, is_password_strong\n"
            "def test_ok():\n"
            "    assert evaluate_password_strength('a') == 1\n"
        )
        llm = CapturingLLM([CODE, test_code])
        engine = make_engine(llm, fm)
        project_id = fm.create_project("demo").project_id
        engine.run_module("strength_evaluator", project_id=project_id, contract=CONTRACT)
        assert len(llm.calls) == 2
        # M15-7 起，写码与写测试都携带契约段（成对注入）
        assert "模块接口契约" in user_text(llm.calls[0])
        assert "evaluate_password_strength(password) -> int" in user_text(llm.calls[1])


class TestWriteCodeContractInjection:
    """M15-7：写码提示词注入契约（paid_pilot2 取证：9/15 冻结同根）。"""

    def test_write_code_prompt_contains_contract(self, tmp_path):
        llm = CapturingLLM(["def evaluate_password_strength(p): return 1"])
        engine = make_engine(llm, FileManager(projects_root=tmp_path / "p"))
        engine._write_code("strength_evaluator", "评估强度", contract=CONTRACT)
        text = user_text(llm.calls[0])
        assert "模块接口契约" in text
        assert "evaluate_password_strength(password) -> int" in text
        assert "私有化" in text  # extra 处置指引前置

    def test_write_code_without_contract_unchanged(self, tmp_path):
        llm = CapturingLLM(["x = 1"])
        engine = make_engine(llm, FileManager(projects_root=tmp_path / "p"))
        engine._write_code("strength_evaluator", "评估强度")
        assert "模块接口契约" not in user_text(llm.calls[0])

    def test_run_module_routes_contract_to_codegen_and_testgen(self, tmp_path):
        fm = FileManager(projects_root=tmp_path / "p")
        test_code = (
            "from strength_evaluator import evaluate_password_strength\n"
            "def test_ok():\n    assert evaluate_password_strength('a') == 1\n"
        )
        llm = CapturingLLM([CODE, test_code])
        engine = make_engine(llm, fm)
        project_id = fm.create_project("demo").project_id
        engine.run_module("strength_evaluator", project_id=project_id, contract=CONTRACT)
        # 写码与写测试的 user 提示词都必须携带契约段
        assert "模块接口契约" in user_text(llm.calls[0])
        assert "模块接口契约" in user_text(llm.calls[1])
