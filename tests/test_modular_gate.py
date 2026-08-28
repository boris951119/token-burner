"""12.2 模块化启用条件测试（TDD 先行）。

规格依据（v0.3.1 12.2 节）：
- 模块化拆分启用条件：难度 ≥5 或预估文件数 ≥6（二者满足其一）；
- 不满足 → 单份 spec 直出：跳过模块拆分与接口契约生成，
  spec 作为单一模块进入开发循环；
- 决策归属（总则 D.1）：难度/文件数预估由大模型评估输出，
  阈值判定为程序确定性校验（should_modularize）。
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings


@pytest.fixture
def fm(tmp_path):
    from app.tools.file_manager import FileManager

    return FileManager(projects_root=tmp_path / "projects")


# ---------------------------------------------------------------------------
# 程序门控：should_modularize（确定性阈值判定）
# ---------------------------------------------------------------------------


class TestShouldModularize:
    def test_difficulty_at_threshold(self):
        # 难度 =5 → 启用模块化
        from app.agents.module_builder import should_modularize

        assert should_modularize(5, 0, Settings()) is True

    def test_difficulty_below_threshold_files_below(self):
        # 难度 4 且文件数 5 → 不启用（单 spec 直出）
        from app.agents.module_builder import should_modularize

        assert should_modularize(4, 5, Settings()) is False

    def test_files_at_threshold(self):
        # 难度低但预估文件数 =6 → 启用
        from app.agents.module_builder import should_modularize

        assert should_modularize(4, 6, Settings()) is True

    def test_zero_disables(self):
        # 未知难度（0，含评估降级场景）且无文件预估 → 单 spec 直出
        from app.agents.module_builder import should_modularize

        assert should_modularize(0, 0, Settings()) is False

    def test_custom_thresholds(self):
        from app.agents.module_builder import should_modularize

        settings = Settings(modular_difficulty_threshold=7, modular_file_count_threshold=10)
        assert should_modularize(6, 9, settings) is False
        assert should_modularize(7, 0, settings) is True
        assert should_modularize(0, 10, settings) is True


# ---------------------------------------------------------------------------
# 评估元数据：estimated_files 解析与净化
# ---------------------------------------------------------------------------


def _assess(files_field) -> "object":
    """用桩 LLM 跑一次路由，返回 RoutingResult。"""
    from app.orchestrator import TaskRouter
    from tests.test_pipeline import ScriptedLLM

    payload = {
        "difficulty_score": 4,
        "difficulty_level": "中等",
        "task_type": "编程",
        "reason": "理由",
    }
    if files_field is not ...:
        payload["estimated_files"] = files_field
    llm = ScriptedLLM([json.dumps(payload, ensure_ascii=False)])
    return TaskRouter(llm, "gpt-4o", Settings()).route("开发工具")


class TestEstimatedFilesParsing:
    def test_valid_estimated_files_carried(self):
        assert _assess(7).estimated_files == 7

    def test_missing_field_defaults_zero(self):
        # 旧格式/字段缺失 → 0（向后兼容）
        assert _assess(...).estimated_files == 0

    def test_invalid_value_sanitized_to_zero(self):
        # 非法值（负数/布尔/字符串）→ 归零，不使评估整体失效
        assert _assess(-3).estimated_files == 0
        assert _assess(True).estimated_files == 0
        assert _assess("many").estimated_files == 0


# ---------------------------------------------------------------------------
# Pipeline：模块化门控接入团队流程
# ---------------------------------------------------------------------------

_POSITIVE = json.dumps(
    {"scores": {"feasibility": 9, "security": 9, "maintainability": 9},
     "strengths": ["完善"], "weaknesses": [], "risks": []},
    ensure_ascii=False,
)

_CODE = "def core_fn():\n    return 1\n"


def _low_scripts(score: int = 4, files: int | None = None) -> list[str]:
    """低难度团队流程脚本：评估→讨论→收敛（无拆分/接口）。"""
    payload = {
        "difficulty_score": score, "difficulty_level": "中等",
        "task_type": "编程", "reason": "理由",
    }
    if files is not None:
        payload["estimated_files"] = files
    return [
        json.dumps(payload, ensure_ascii=False),
        "初始方案", _POSITIVE, _POSITIVE, "最终 spec",
        _CODE, "TEST",
    ]


_RUN_KWARGS = dict(
    requirement="开发小工具",
    models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
    mode="safe",
    spec_confirm="确认",
)


def _pipeline(fm, scripts, statuses, settings=None):
    from app.pipeline import Pipeline
    from tests.test_pipeline import ScriptedLLM

    from app.execution.executor import ExecutionResult, ExecutionStatus

    class _Exec:
        def __init__(self):
            self.runs = 0

        def run(self, code, tests, timeout, expected_output="", module=""):
            self.runs += 1
            return ExecutionResult(status=ExecutionStatus.SUCCESS)

    return Pipeline(
        llm=ScriptedLLM(scripts),
        executor=_Exec(),
        settings=settings or Settings(),
        file_manager=fm,
    )


class TestPipelineModularGate:
    def test_low_difficulty_single_spec_direct(self, fm):
        # 12.2：难度 4 且文件数 <6 → 单份 spec 直出（无拆分/接口调用）
        llm_scripts = _low_scripts(score=4, files=3)
        from tests.test_pipeline import ScriptedLLM

        from app.pipeline import Pipeline

        class _Exec:
            def run(self, code, tests, timeout, expected_output="", module=""):
                from app.execution.executor import ExecutionResult, ExecutionStatus

                return ExecutionResult(status=ExecutionStatus.SUCCESS)

        llm = ScriptedLLM(llm_scripts)
        pipeline = Pipeline(llm=llm, executor=_Exec(), settings=Settings(), file_manager=fm)
        result = pipeline.run(**_RUN_KWARGS)
        assert result.kind == "team_flow"
        handle = fm.get_project(result.project_id)
        assert handle is not None
        root = handle.root
        # 单模块交付：spec + main 模块代码/测试；无 interfaces.json
        assert (root / "spec.md").is_file()
        assert (root / "modules" / "main.md").is_file()
        assert (root / "code" / "main" / "main.py").is_file()
        assert (root / "tests" / "main" / "test_main.py").is_file()
        assert not (root / "interfaces.json").exists()
        # LLM 调用数：评估1 + 方案1 + 评审2 + spec1 + 写码1 + 写测试1 = 7
        assert len(llm.calls) == 7

    def test_low_difficulty_high_file_count_modularizes(self, fm):
        # 12.2：难度 4 但预估文件数 6 → 启用模块化拆分
        from tests.test_pipeline import team_scripts

        scripts = _low_scripts(score=4, files=6)
        # 单 spec 直出的脚本不含拆分/接口，追加拆分相关脚本
        split = json.dumps(
            {"modules": [
                {"name": "user", "responsibility": "用户管理",
                 "dependencies": [], "priority": 1},
            ]},
            ensure_ascii=False,
        )
        iface = json.dumps(
            {"imports": [], "exports": ["core_fn"],
             "public_api": ["core_fn"], "dependencies": []},
            ensure_ascii=False,
        )
        scripts = scripts[:5] + [split, iface, _CODE, "TEST"]

        from tests.test_pipeline import ScriptedLLM

        from app.pipeline import Pipeline

        class _Exec:
            def run(self, code, tests, timeout, expected_output="", module=""):
                from app.execution.executor import ExecutionResult, ExecutionStatus

                return ExecutionResult(status=ExecutionStatus.SUCCESS)

        llm = ScriptedLLM(scripts)
        pipeline = Pipeline(llm=llm, executor=_Exec(), settings=Settings(), file_manager=fm)
        result = pipeline.run(**_RUN_KWARGS)
        assert result.kind == "team_flow"
        handle = fm.get_project(result.project_id)
        assert handle is not None
        assert (handle.root / "interfaces.json").is_file()
        assert (handle.root / "modules" / "user.md").is_file()

    def test_high_difficulty_keeps_modular(self, fm):
        # 回归：难度 ≥5 仍走拆分（既有行为不变）
        from tests.test_pipeline import ScriptedLLM, team_scripts

        from app.pipeline import Pipeline

        class _Exec:
            def run(self, code, tests, timeout, expected_output="", module=""):
                from app.execution.executor import ExecutionResult, ExecutionStatus

                return ExecutionResult(status=ExecutionStatus.SUCCESS)

        llm = ScriptedLLM(team_scripts())
        pipeline = Pipeline(llm=llm, executor=_Exec(), settings=Settings(), file_manager=fm)
        result = pipeline.run(requirement="开发用户系统", **{
            k: v for k, v in _RUN_KWARGS.items() if k != "requirement"
        })
        assert result.kind == "team_flow"
        handle = fm.get_project(result.project_id)
        assert handle is not None
        assert (handle.root / "interfaces.json").is_file()
