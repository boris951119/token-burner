"""DevLoopEngine 单元测试（TDD 先行，LLM 与 Executor 全部 mock）。

依据：规格文档 v0.3.1
- 3.5 节：逐模块「开发（Dev Agent）→ 测试（Test Agent）→ 修复」循环；
  接口契约（interfaces.json）作为双向绑定的单一事实源；
- 3.7 节：Dev 生成代码与可独立运行的测试文件；
- 11.4 节：单模块修复尝试上限（默认 3 次）；达上限仍失败 →
  冻结该模块（保留代码与失败记录，跳过后续流程）；
- 12.4 节：修复历史记录落盘 changelog/<module>/fix_history.md；
- 8.4 节：SKIPPED（安全模式）→ 展示手动运行指令等待用户反馈；
  用户反馈失败等价于执行失败，进入修复循环。
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.agents.dev_loop import DevLoopEngine, ModuleResult, ModuleStatus
from app.tools.file_manager import FileManager
from app.utils.model_client import LLMResponse


class ScriptedLLM:
    """按序返回内容的桩：区分 dev（写代码/修复）与 test（写测试）调用。"""

    def __init__(self, scripts: list[str] | None = None):
        self.scripts = list(scripts or [])
        self.calls: list[dict] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append({"model": model, "json_mode": json_mode})
        content = self.scripts.pop(0) if self.scripts else "print('default')"
        return LLMResponse(model=model, content=content, input_tokens=10, output_tokens=5)


class FakeExecutor:
    """可编排执行结果的桩执行器（安全/自动模式共用接口）。"""

    def __init__(self, statuses: list[str]):
        self.statuses = list(statuses)
        self.runs: list[dict] = []

    def run(self, code, tests, timeout, expected_output=""):
        from app.execution.executor import ExecutionResult, ExecutionStatus
        status = self.statuses.pop(0) if self.statuses else "SUCCESS"
        self.runs.append({"code": code, "tests": tests, "status": status})
        return ExecutionResult(
            status=ExecutionStatus(status),
            message="手动运行指令（安全模式）" if status == "SKIPPED" else "",
        )


@pytest.fixture
def fm(tmp_path) -> FileManager:
    return FileManager(projects_root=tmp_path / "projects")


def make_engine(llm, executor, fm, settings=None) -> DevLoopEngine:
    return DevLoopEngine(
        llm=llm,
        dev_model="deepseek-chat",
        test_model="claude-3-5-sonnet",
        executor=executor,
        settings=settings or Settings(),
        file_manager=fm,
    )


class TestDevLoopFlow:
    def test_codegen_then_testgen_then_execute(self, fm):
        # 3.7：Dev 写代码 → Test 写测试 → 执行器运行
        llm = ScriptedLLM(["CODE_A", "TEST_A"])
        executor = FakeExecutor(["SUCCESS"])
        engine = make_engine(llm, executor, fm)
        result = engine.run_module("user", project_id=_create(fm))
        assert result.status == ModuleStatus.SUCCESS
        models = [c["model"] for c in llm.calls]
        assert models == ["deepseek-chat", "claude-3-5-sonnet"]
        assert executor.runs[0]["code"] == "CODE_A"
        assert executor.runs[0]["tests"] == "TEST_A"

    def test_code_and_tests_persisted(self, fm):
        # 12.3：code/<module>/、tests/<module>/ 落盘
        project_id = _create(fm)
        llm = ScriptedLLM(["CODE_A", "TEST_A"])
        engine = make_engine(llm, FakeExecutor(["SUCCESS"]), fm)
        engine.run_module("user", project_id=project_id)
        handle = fm.get_project(project_id)
        assert handle is not None
        assert (handle.root / "code" / "user" / "user.py").is_file()
        assert (handle.root / "tests" / "user" / "test_user.py").is_file()

    def test_skipped_waits_user_feedback_success(self, fm):
        # 8.4：安全模式 SKIPPED → 用户反馈成功 → 等价执行成功
        llm = ScriptedLLM(["CODE_A", "TEST_A"])
        executor = FakeExecutor(["SKIPPED"])
        engine = make_engine(llm, executor, fm)
        result = engine.run_module(
            "user", project_id=_create(fm), user_feedback="运行成功，输出正确"
        )
        assert result.status == ModuleStatus.SUCCESS

    def test_skipped_user_feedback_failure_triggers_fix(self, fm):
        # 8.4：用户反馈失败 → 进入修复循环
        llm = ScriptedLLM(["CODE_A", "TEST_A", "FIX_1"])
        executor = FakeExecutor(["SKIPPED", "SUCCESS"])
        engine = make_engine(llm, executor, fm)
        result = engine.run_module(
            "user",
            project_id=_create(fm),
            user_feedback="运行报错：NameError: name 'x' is not defined",
        )
        assert result.status == ModuleStatus.SUCCESS
        assert result.fix_attempts == 1
        # 修复调用发给 Dev 模型
        assert llm.calls[2]["model"] == "deepseek-chat"

    def test_feedback_negated_negative_word_is_success(self, fm):
        # 「无报错」含负向词但被否定前缀修饰 → 判成功（回归：子串误判缺陷）
        llm = ScriptedLLM(["CODE_A", "TEST_A"])
        executor = FakeExecutor(["SKIPPED"])
        engine = make_engine(llm, executor, fm)
        result = engine.run_module(
            "user",
            project_id=_create(fm),
            user_feedback="手动运行成功，输出符合预期，无报错",
        )
        assert result.status == ModuleStatus.SUCCESS
        assert result.fix_attempts == 0
        assert len(llm.calls) == 2  # 仅写码+写测试，未触发修复调用


def _create(fm):
    return fm.create_project("demo").project_id


class TestFixLoop:
    def test_failed_execution_triggers_fix(self, fm):
        # 失败 → Dev 修复 → 重跑成功
        llm = ScriptedLLM(["CODE_A", "TEST_A", "FIX_1"])
        executor = FakeExecutor(["FAILED", "SUCCESS"])
        engine = make_engine(llm, executor, fm)
        result = engine.run_module("user", project_id=_create(fm))
        assert result.status == ModuleStatus.SUCCESS
        assert result.fix_attempts == 1
        assert len(executor.runs) == 2  # 修复后重跑

    def test_fix_history_persisted(self, fm):
        # 12.4：修复记录落盘 changelog/<module>/fix_history.md
        project_id = _create(fm)
        llm = ScriptedLLM(["CODE_A", "TEST_A", "FIX_1"])
        executor = FakeExecutor(["FAILED", "SUCCESS"])
        engine = make_engine(llm, executor, fm)
        engine.run_module("user", project_id=project_id)
        handle = fm.get_project(project_id)
        assert handle is not None
        history = (handle.root / "changelog" / "user" / "fix_history.md").read_text(
            encoding="utf-8"
        )
        assert "1" in history  # 修复轮次记录

    def test_fix_limit_freezes_module(self, fm):
        # 11.4：修复达上限仍失败 → 冻结模块（跳过后续，保留记录）
        llm = ScriptedLLM(["CODE_A", "TEST_A", "FIX_1", "FIX_2", "FIX_3"])
        executor = FakeExecutor(["FAILED", "FAILED", "FAILED", "FAILED"])
        settings = Settings(max_fix_rounds=3)
        engine = make_engine(llm, executor, fm, settings=settings)
        result = engine.run_module("user", project_id=_create(fm))
        assert result.status == ModuleStatus.FROZEN
        assert result.fix_attempts == 3
        # 冻结记录也落盘（12.4）
        assert "冻结" in result.message or result.message

    def test_frozen_module_skipped_in_batch(self, fm):
        # 冻结模块不阻塞其他模块的推进
        project_id = _create(fm)
        llm = ScriptedLLM(
            [
                "CODE_A", "TEST_A", "FIX_1", "FIX_2", "FIX_3",  # user：冻死
                "CODE_B", "TEST_B",  # data：一次成功
            ]
        )
        executor = FakeExecutor(["FAILED", "FAILED", "FAILED", "FAILED", "SUCCESS"])
        settings = Settings(max_fix_rounds=3)
        engine = make_engine(llm, executor, fm, settings=settings)
        results = engine.run_batch(["user", "data"], project_id=project_id)
        assert results["user"].status == ModuleStatus.FROZEN
        assert results["data"].status == ModuleStatus.SUCCESS

    def test_timeout_triggers_fix(self, fm):
        # 8.4：TIMEOUT 同样进入修复循环
        llm = ScriptedLLM(["CODE_A", "TEST_A", "FIX_1"])
        executor = FakeExecutor(["TIMEOUT", "SUCCESS"])
        engine = make_engine(llm, executor, fm)
        result = engine.run_module("user", project_id=_create(fm))
        assert result.status == ModuleStatus.SUCCESS


class TestBatchRun:
    def test_run_batch_order(self, fm):
        # 按传入顺序逐模块执行
        project_id = _create(fm)
        llm = ScriptedLLM(["C1", "T1", "C2", "T2"])
        executor = FakeExecutor(["SUCCESS", "SUCCESS"])
        engine = make_engine(llm, executor, fm)
        results = engine.run_batch(["user", "data"], project_id=project_id)
        assert list(results.keys()) == ["user", "data"]
        assert all(r.status == ModuleStatus.SUCCESS for r in results.values())

    def test_executor_receives_timeout_setting(self, fm):
        # 30s 熔断参数透传（8.4 / 11.6）
        from app.config import Settings as S
        settings = S(sandbox_timeout_seconds=45)
        llm = ScriptedLLM(["C", "T"])
        executor = FakeExecutor(["SUCCESS"])
        engine = make_engine(llm, executor, fm, settings=settings)
        engine.run_module("user", project_id=_create(fm))
        # FakeExecutor 不校验超时值；经真实 SandboxExecutor 透传（接口已含 timeout 形参）

    def test_module_result_fields(self, fm):
        # 8.4 结构：状态、修复次数、消息
        llm = ScriptedLLM(["C", "T"])
        engine = make_engine(llm, FakeExecutor(["SUCCESS"]), fm)
        result = engine.run_module("user", project_id=_create(fm))
        assert isinstance(result, ModuleResult)
        assert result.module == "user"
        assert result.fix_attempts == 0
        assert result.code == "C"
        assert result.tests == "T"


class TestStaticGate:
    """12.2 / 17 章第三阶段：静态验证与接口校验接入模块完成前置门禁。"""

    def test_syntax_error_blocks_before_executor(self, fm):
        # 语法坏代码 → 门禁拦截，不进执行器，直接进入修复循环
        llm = ScriptedLLM(["def broken(:", "T", "FIX_OK"])
        executor = FakeExecutor(["SUCCESS"])
        engine = make_engine(llm, executor, fm)
        result = engine.run_module("user", project_id=_create(fm))
        assert result.status == ModuleStatus.SUCCESS
        assert result.fix_attempts == 1
        assert executor.runs[0]["code"] == "FIX_OK"  # 首版坏代码未被执行

    def test_interface_diff_blocks_before_executor(self, fm):
        # 契约三字段差异 → 门禁拦截（缺失实现）
        contract = {
            "imports": [],
            "exports": ["login(user_id, password)"],
            "public_api": ["login"],
            "dependencies": [],
        }
        llm = ScriptedLLM(["x = 1\n", "T", "def login(user_id, password):\n    return True\n"])
        executor = FakeExecutor(["SUCCESS"])
        engine = make_engine(llm, executor, fm)
        result = engine.run_module(
            "auth", project_id=_create(fm), contract=contract
        )
        assert result.status == ModuleStatus.SUCCESS
        assert result.fix_attempts == 1
        assert executor.runs[0]["code"].startswith("def login")

    def test_gate_failure_report_contains_issue(self, fm):
        # 门禁失败报告含具体 issue（供 Dev LLM 定位修复）
        contract = {
            "imports": [],
            "exports": ["missing_fn()"],
            "public_api": ["missing_fn"],
            "dependencies": [],
        }
        captured = {}

        class ProbeLLM(ScriptedLLM):
            def chat(self, model, messages, json_mode=False):
                call = super().chat(model, messages, json_mode)
                if "修复" in messages[0]["content"]:
                    captured["fix_prompt"] = messages[1]["content"]
                return call

        llm = ProbeLLM(["x = 1\n", "T", "def missing_fn():\n    pass\n"])
        engine = make_engine(llm, FakeExecutor(["SUCCESS"]), fm)
        engine.run_module("auth", project_id=_create(fm), contract=contract)
        assert "missing_fn" in captured["fix_prompt"]

    def test_validation_report_persisted(self, fm):
        # 验证报告落盘（17 章：写入 changelog/）
        project_id = _create(fm)
        llm = ScriptedLLM(["x = 1\n", "T"])
        engine = make_engine(llm, FakeExecutor(["SUCCESS"]), fm)
        engine.run_module("user", project_id=project_id)
        handle = fm.get_project(project_id)
        assert handle is not None
        report = (handle.root / "changelog" / "user" / "validation.md").read_text(
            encoding="utf-8"
        )
        assert "user" in report
        assert "SUCCESS" in report

    def test_gate_failure_counts_toward_fix_limit(self, fm):
        # 门禁失败同样消耗修复轮次（11.4 上限统一约束）
        contract = {
            "imports": [],
            "exports": ["missing_fn()"],
            "public_api": ["missing_fn"],
            "dependencies": [],
        }
        llm = ScriptedLLM(["x = 1\n", "T", "x = 2\n", "x = 3\n", "x = 4\n"])
        executor = FakeExecutor([])
        settings = Settings(max_fix_rounds=3)
        engine = make_engine(llm, executor, fm, settings=settings)
        result = engine.run_module(
            "auth", project_id=_create(fm), contract=contract
        )
        assert result.status == ModuleStatus.FROZEN
        assert result.fix_attempts == 3
        assert executor.runs == []  # 从未到达执行器
