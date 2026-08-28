"""14.4/12.7 _shared 变更触发依赖模块整包回归测试（TDD 先行）。

规格依据（v0.3.1）：
- 12.7：_shared/ 被多模块共用，其变更牵动全局，须触发对依赖模块的回归检查；
- 14.4：_shared/ 变更时，触发对其全部依赖模块的整包回归；
- 14.5：依赖者整包回归**仅**在 _shared/ 变更时触发（普通模块修复不触发全量回归）；
- 14.2：依赖判定为 AST 零执行抽取（import 语句），非自然语言猜测。

约定（提示词层）：开发副 LLM 输出中，公共依赖代码以标记块输出：
  # ==== shared: <filename> ====
  <代码>
  # ==== end shared ====
程序解析后落盘 code/_shared/<filename>，其余为模块自身代码。
"""

from __future__ import annotations

import json

import pytest

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
        self.runs: list[str] = []  # 每次执行的代码首行（回归计数依据）

    def run(self, code, tests, timeout, expected_output="", module=""):
        from app.execution.executor import ExecutionResult, ExecutionStatus

        self.runs.append(code.strip().splitlines()[0] if code.strip() else "")
        status = self.statuses.pop(0) if self.statuses else "SUCCESS"
        return ExecutionResult(status=ExecutionStatus(status))


@pytest.fixture
def fm(tmp_path):
    from app.tools.file_manager import FileManager

    return FileManager(projects_root=tmp_path / "projects")


# ---------------------------------------------------------------------------
# 依赖判定（AST 零执行）
# ---------------------------------------------------------------------------


class TestUsesShared:
    def test_from_shared_import(self):
        from app.utils.shared_check import uses_shared

        assert uses_shared("from _shared.utils import helper\n\n\ndef f():\n    return helper()\n")

    def test_import_shared(self):
        from app.utils.shared_check import uses_shared

        assert uses_shared("import _shared\n\n\ndef f():\n    return _shared.helper()\n")

    def test_no_shared_reference(self):
        from app.utils.shared_check import uses_shared

        assert not uses_shared("import os\n\n\ndef f():\n    return 1\n")

    def test_find_shared_dependents_from_disk(self, fm):
        # 扫描落盘代码：仅 user 依赖 _shared（data/auth 不依赖）
        from app.utils.shared_check import find_shared_dependents

        project_id = fm.create_project("demo").project_id
        fm.write_code_file(project_id, "user", "user.py",
                           "from _shared.utils import helper\n\n\ndef core_fn():\n    return helper()\n")
        fm.write_code_file(project_id, "data", "data.py", "def core_fn():\n    return 1\n")
        fm.write_code_file(project_id, "auth", "auth.py",
                           "from user import core_fn\n\n\ndef core_fn():\n    return core_fn()\n")
        dependents = find_shared_dependents(
            fm.get_project(project_id).root, ["user", "data", "auth"]
        )
        assert dependents == ["user"]


# ---------------------------------------------------------------------------
# 变更检测（内容 hash 基线）
# ---------------------------------------------------------------------------


class TestSharedSignature:
    def test_empty_dir_baseline(self, fm):
        project_id = fm.create_project("demo").project_id
        assert fm.shared_signature(project_id) != fm.shared_signature(project_id) or True
        # 空目录签名稳定（两次一致）
        assert fm.shared_signature(project_id) == fm.shared_signature(project_id)

    def test_write_new_file_changes_signature(self, fm):
        project_id = fm.create_project("demo").project_id
        before = fm.shared_signature(project_id)
        fm.write_shared_file(project_id, "utils.py", "def helper():\n    return 1\n")
        assert fm.shared_signature(project_id) != before

    def test_modify_changes_same_content_noop(self, fm):
        project_id = fm.create_project("demo").project_id
        fm.write_shared_file(project_id, "utils.py", "def helper():\n    return 1\n")
        after_first = fm.shared_signature(project_id)
        # 同内容重写 → 签名不变（幂等，14.5：仅真实变更触发回归）
        fm.write_shared_file(project_id, "utils.py", "def helper():\n    return 1\n")
        assert fm.shared_signature(project_id) == after_first
        # 内容修改 → 签名变化
        fm.write_shared_file(project_id, "utils.py", "def helper():\n    return 2\n")
        assert fm.shared_signature(project_id) != after_first


# ---------------------------------------------------------------------------
# shared 标记块解析与落盘
# ---------------------------------------------------------------------------


class TestExtractSharedBlocks:
    def test_extracts_and_strips(self):
        from app.agents.dev_loop import _extract_shared_blocks

        raw = (
            "from _shared.utils import helper\n\n\n"
            "def core_fn():\n    return helper()\n\n"
            "# ==== shared: utils.py ====\n"
            "def helper():\n    return 1\n"
            "# ==== end shared ====\n"
        )
        shared, rest = _extract_shared_blocks(raw)
        assert shared == {"utils.py": "def helper():\n    return 1\n"}
        assert "shared:" not in rest and "helper():\n    return 1" not in rest
        assert "def core_fn" in rest  # 模块代码保留

    def test_no_blocks_passthrough(self):
        from app.agents.dev_loop import _extract_shared_blocks

        raw = "def core_fn():\n    return 1\n"
        shared, rest = _extract_shared_blocks(raw)
        assert shared == {}
        assert rest == raw


class TestWriteSharedViaDevLoop:
    def _engine(self, llm, executor, fm):
        from app.agents.dev_loop import DevLoopEngine

        return DevLoopEngine(
            llm=llm, dev_model="d", test_model="t",
            executor=executor, settings=Settings(), file_manager=fm,
        )

    def test_write_code_with_shared_block_persists(self, fm):
        # 写码输出含 shared 块 → _shared/utils.py 落盘 + 模块代码剥离标记块
        project_id = fm.create_project("demo").project_id
        raw = (
            "from _shared.utils import helper\n\n\n"
            "def core_fn():\n    return helper()\n\n"
            "# ==== shared: utils.py ====\n"
            "def helper():\n    return 1\n"
            "# ==== end shared ====\n"
        )
        llm = ScriptedLLM([raw, "TEST"])
        engine = self._engine(llm, FakeExecutor(["SUCCESS"]), fm)
        result = engine.run_module("user", project_id=project_id)
        handle = fm.get_project(project_id)
        assert (handle.root / "code" / "_shared" / "utils.py").is_file()
        assert "# ==== shared" not in result.code  # 模块代码已剥离
        assert "def core_fn" in result.code

    def test_fix_code_with_shared_block_persists(self, fm):
        # 修复轮输出含 shared 块 → 同样落盘（shared 变更主来源）
        project_id = fm.create_project("demo").project_id
        fixed = (
            "from _shared.utils import helper\n\n\n"
            "def core_fn():\n    return helper()\n\n"
            "# ==== shared: utils.py ====\n"
            "def helper():\n    return 2\n"
            "# ==== end shared ====\n"
        )
        llm = ScriptedLLM(["def core_fn():\n    return 1\n", "TEST", fixed])
        engine = self._engine(llm, FakeExecutor(["FAILED", "SUCCESS"]), fm)
        result = engine.run_module("user", project_id=project_id)
        handle = fm.get_project(project_id)
        shared_code = (handle.root / "code" / "_shared" / "utils.py").read_text(encoding="utf-8")
        assert "return 2" in shared_code
        assert result.fix_attempts == 1


# ---------------------------------------------------------------------------
# regress_module（回归三态）
# ---------------------------------------------------------------------------


def _ok_result():
    from app.agents.dev_loop import ModuleResult, ModuleStatus

    return ModuleResult(
        module="user", status=ModuleStatus.SUCCESS, fix_attempts=0,
        message="", code="from _shared.utils import helper\n\n\ndef core_fn():\n    return helper()\n",
        tests="TEST",
    )


class TestRegressModule:
    def _engine(self, executor, fm, settings=None):
        from app.agents.dev_loop import DevLoopEngine

        return DevLoopEngine(
            llm=ScriptedLLM(), dev_model="d", test_model="t",
            executor=executor, settings=settings or Settings(), file_manager=fm,
        )

    def test_regression_pass_keeps_success(self, fm):
        # 回归通过 → 保持 SUCCESS（fix_attempts 不变，无 LLM 消耗）
        project_id = fm.create_project("demo").project_id
        engine = self._engine(FakeExecutor(["SUCCESS"]), fm)
        result = engine.regress_module("user", _ok_result(), project_id=project_id)
        assert result.status.value == "SUCCESS"
        assert result.fix_attempts == 0

    def test_regression_failure_enters_fix_loop(self, fm):
        # 回归失败（shared 变更破坏依赖模块）→ 进入修复循环
        project_id = fm.create_project("demo").project_id
        llm = ScriptedLLM(["FIXED_CODE"])
        from app.agents.dev_loop import DevLoopEngine

        engine = DevLoopEngine(
            llm=llm, dev_model="d", test_model="t",
            executor=FakeExecutor(["FAILED", "SUCCESS"]),
            settings=Settings(), file_manager=fm,
        )
        result = engine.regress_module("user", _ok_result(), project_id=project_id)
        assert result.status.value == "SUCCESS"
        assert result.fix_attempts == 1  # 回归失败计入修复轮

    def test_regression_skipped_awaits_feedback(self, fm):
        # 安全模式 SKIPPED → 等待用户反馈（3.8 语义，回归不强制执行）
        project_id = fm.create_project("demo").project_id
        engine = self._engine(FakeExecutor(["SKIPPED"]), fm)
        result = engine.regress_module("user", _ok_result(), project_id=project_id)
        assert result.status.value == "AWAITING_FEEDBACK"


# ---------------------------------------------------------------------------
# Pipeline：_shared 变更触发依赖者整包回归（14.4 / 14.5）
# ---------------------------------------------------------------------------


def _positive() -> str:
    return json.dumps(
        {"scores": {"feasibility": 9, "security": 9, "maintainability": 9},
         "strengths": ["完善"], "weaknesses": [], "risks": []},
        ensure_ascii=False,
    )


def _team_scripts_with_shared() -> list[str]:
    """团队流程脚本：user 依赖 _shared；auth 修复轮写 shared。"""
    split = json.dumps(
        {"modules": [
            {"name": "user", "responsibility": "用户管理", "dependencies": [], "priority": 1},
            {"name": "data", "responsibility": "数据存储", "dependencies": [], "priority": 1},
            {"name": "auth", "responsibility": "认证", "dependencies": ["user", "data"], "priority": 2},
        ]},
        ensure_ascii=False,
    )
    iface = lambda deps: json.dumps(
        {"imports": ["core_fn" for _ in deps] if deps else [],
         "exports": ["core_fn"], "public_api": ["core_fn"], "dependencies": deps},
        ensure_ascii=False,
    )
    user_code = (
        "from _shared.utils import helper\n\n\ndef core_fn():\n    return helper()\n"
    )
    data_code = "def core_fn():\n    return 1\n"
    auth_code = (
        "from user import core_fn as user_core_fn\n"
        "from data import core_fn as data_core_fn\n"
        "def core_fn():\n    return user_core_fn() + data_core_fn()\n"
    )
    auth_fixed = (
        auth_code
        + "\n# ==== shared: utils.py ====\n"
        + "def helper():\n    return 2\n"
        + "# ==== end shared ====\n"
    )
    return [
        json.dumps({"difficulty_score": 7, "difficulty_level": "中",
                    "task_type": "编程", "reason": "理由"}, ensure_ascii=False),
        "初始方案", _positive(), _positive(), "最终 spec", split,
        iface([]), iface([]), iface(["user", "data"]),
        # build_order: data, user, auth
        data_code, "TEST",
        user_code, "TEST",
        auth_code, "TEST",        # auth 首轮执行 FAILED → 修复
        auth_fixed,               # 修复输出含 shared 块 → 触发 user 回归
    ]


def _run(fm, scripts, statuses):
    from app.pipeline import Pipeline

    from tests.test_pipeline import ScriptedLLM as PipelineScriptedLLM

    llm = PipelineScriptedLLM(scripts)
    executor = FakeExecutor(statuses)
    pipeline = Pipeline(llm=llm, executor=executor, settings=Settings(), file_manager=fm)
    result = pipeline.run(
        requirement="开发用户系统",
        models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
        mode="safe", spec_confirm="确认",
    )
    return result, executor


class TestPipelineSharedRegression:
    def test_shared_change_triggers_dependent_regression(self, fm):
        # auth 修复轮写 _shared → 已完成的 user（依赖 _shared）被整包回归重跑
        # 执行序列：data、user、auth(FAILED)、auth 修复后(SUCCESS)、user 回归(SUCCESS)
        result, executor = _run(
            fm, _team_scripts_with_shared(),
            ["SUCCESS", "SUCCESS", "FAILED", "SUCCESS", "SUCCESS"],
        )
        assert result.kind == "team_flow"
        # user 代码被运行 2 次（初始 + 回归），data 仅 1 次（不依赖 _shared）
        user_runs = sum(1 for r in executor.runs if "_shared.utils" in r)
        data_runs = sum(1 for r in executor.runs if r.startswith("def core_fn"))
        assert user_runs == 2
        assert data_runs == 1

    def test_regression_event_persisted(self, fm):
        # 14.4：回归事件落盘可审计（changelog/shared_regression.md）
        result, executor = _run(
            fm, _team_scripts_with_shared(),
            ["SUCCESS", "SUCCESS", "FAILED", "SUCCESS", "SUCCESS"],
        )
        handle = fm.get_project(result.project_id)
        report = (handle.root / "changelog" / "shared_regression.md").read_text(encoding="utf-8")
        assert "user" in report  # 回归范围记录
        assert "_shared" in report or "shared" in report.lower()

    def test_no_shared_change_no_regression(self, fm):
        # 14.5：无 _shared 变更 → 不触发回归（普通修复仅重验本模块）
        scripts = _team_scripts_with_shared()
        # auth 修复输出不含 shared 块（普通修复）
        scripts[-1] = (
            "from user import core_fn as user_core_fn\n"
            "from data import core_fn as data_core_fn\n"
            "def core_fn():\n    return user_core_fn() + data_core_fn()\n"
        )
        result, executor = _run(
            fm, scripts,
            ["SUCCESS", "SUCCESS", "FAILED", "SUCCESS"],
        )
        assert result.kind == "team_flow"
        user_runs = sum(1 for r in executor.runs if "_shared.utils" in r)
        assert user_runs == 1  # 仅初始执行，无回归

    def test_regression_failure_triggers_fix(self, fm):
        # 回归失败 → user 重新进入修复循环（LLM 修复脚本消耗）
        scripts = _team_scripts_with_shared() + [
            "from _shared.utils import helper\n\n\ndef core_fn():\n    return helper()\n",
        ]
        # 序列：data、user、auth(FAILED)、auth 修复(SUCCESS)、user 回归(FAILED)、user 修复后(SUCCESS)
        result, executor = _run(
            fm, scripts,
            ["SUCCESS", "SUCCESS", "FAILED", "SUCCESS", "FAILED", "SUCCESS"],
        )
        assert result.kind == "team_flow"
        assert result.frozen_modules == []
        user_runs = sum(1 for r in executor.runs if "_shared.utils" in r)
        assert user_runs == 3  # 初始 + 回归失败 + 修复后重跑
