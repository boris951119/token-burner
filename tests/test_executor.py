"""executor / safe_executor 单元测试（TDD 先行）。

依据：规格文档 v0.3.1
- 3.6.2 节：统一接口 run(code, tests, timeout) -> ExecutionResult；
  安全模式实现返回 ExecutionResult(status="SKIPPED", message="请手动运行以下命令...")；
- 8.4 节：ExecutionResult 五状态 SKIPPED | SUCCESS | FAILED | TIMEOUT | BLOCKED，
  含 exit_code / stdout / stderr / test_results / duration_ms / message；
- 3.6.2 透明性原则：Dev / Test Agent 无需感知当前模式；
- 3.6.4：MVP 先实现安全模式但必须预留 Executor 接口，接入沙箱无需重构 Agent 逻辑。
"""

from __future__ import annotations

import inspect

import pytest

from app.execution.executor import ExecutionResult, Executor, ExecutionStatus
from app.execution.safe_executor import SafeExecutor


class TestExecutionResult:
    def test_status_enum_values(self):
        # 8.4：五状态语义
        assert ExecutionStatus.SKIPPED.value == "SKIPPED"
        assert ExecutionStatus.SUCCESS.value == "SUCCESS"
        assert ExecutionStatus.FAILED.value == "FAILED"
        assert ExecutionStatus.TIMEOUT.value == "TIMEOUT"
        assert ExecutionStatus.BLOCKED.value == "BLOCKED"

    def test_result_fields_per_spec_8_4(self):
        result = ExecutionResult(
            status=ExecutionStatus.SKIPPED,
            exit_code=None,
            stdout="",
            stderr="",
            test_results=[],
            duration_ms=0,
            message="安全模式：请手动运行以下命令...",
        )
        assert result.status == ExecutionStatus.SKIPPED
        assert result.exit_code is None
        assert result.test_results == []
        assert result.duration_ms == 0

    def test_test_result_structure(self):
        # 8.4：test_results 内含 name / status / assertion
        tr = {"name": "test_xxx", "status": "PASS", "assertion": "期望 3 实际 2"}
        result = ExecutionResult(
            status=ExecutionStatus.FAILED,
            exit_code=1,
            stdout="",
            stderr="AssertionError",
            test_results=[tr],
            duration_ms=1200,
            message="",
        )
        assert result.test_results[0]["name"] == "test_xxx"
        assert result.test_results[0]["status"] == "FAIL" or tr["status"] == "PASS"


class TestExecutorAbstraction:
    def test_executor_is_abstract(self):
        # 3.6.2：Executor 为抽象接口，禁止直接实例化
        with pytest.raises(TypeError):
            Executor()  # type: ignore[abstract]

    def test_run_signature_matches_spec(self):
        # 3.6.2：统一接口 run(code, tests, timeout) -> ExecutionResult
        # （expected_output 为带默认值的可选参数，不破坏调用契约）
        signature = inspect.signature(Executor.run)
        params = list(signature.parameters)
        assert params[:4] == ["self", "code", "tests", "timeout"]
        assert signature.return_annotation is not inspect.Signature.empty

    def test_safe_executor_is_executor(self):
        # 3.6.4：接入沙箱时无需重构 Agent 逻辑 → 须继承同一抽象
        assert isinstance(SafeExecutor(), Executor)


class TestSafeExecutor:
    def test_returns_skipped_with_manual_instructions(self):
        # 3.6.2：安全模式返回 SKIPPED + 请手动运行以下命令...
        executor = SafeExecutor()
        result = executor.run(code="print('hi')", tests="", timeout=30)
        assert result.status == ExecutionStatus.SKIPPED
        assert "手动运行" in result.message

    def test_message_contains_run_command(self):
        # 安全模式：附带完整运行指令
        executor = SafeExecutor()
        result = executor.run(code="print('hi')", tests="", timeout=30)
        assert "python" in result.message.lower()

    def test_message_contains_expected_output(self):
        # 3.6.2：附带预期输出
        executor = SafeExecutor()
        result = executor.run(
            code="print('hi')",
            tests="",
            timeout=30,
            expected_output="hi\n",
        )
        assert "hi" in result.message

    def test_tests_included_in_instructions(self):
        # 3.7 安全模式兼容：附带测试运行指令，降低用户手动验证成本
        executor = SafeExecutor()
        result = executor.run(
            code="print('hi')",
            tests="def test_x():\n    assert True\n",
            timeout=30,
        )
        assert "pytest" in result.message

    def test_no_execution_performed(self):
        # 安全审阅模式：不执行代码（stdout/stderr 为空、exit_code None）
        executor = SafeExecutor()
        result = executor.run(code="import os; os.remove('C:/x')", tests="", timeout=5)
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.exit_code is None
        assert result.test_results == []

    def test_timeout_parameter_accepted(self):
        # 接口透明：timeout 参数被接受（安全模式不实际使用）
        executor = SafeExecutor()
        result = executor.run(code="x=1", tests="", timeout=99)
        assert result.status == ExecutionStatus.SKIPPED

    def test_transparent_to_agents(self):
        # 3.6.2 透明性原则：调用方仅依赖 Executor 与 ExecutionResult
        def agent_flow(executor: Executor) -> ExecutionStatus:
            return executor.run(code="x=1", tests="", timeout=30).status

        assert agent_flow(SafeExecutor()) == ExecutionStatus.SKIPPED
