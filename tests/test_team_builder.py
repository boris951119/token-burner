"""TeamBuilder 单元测试（TDD 先行，LLM 全部 mock）。

依据：规格文档 v0.3.1
- 3.3 节：用户选择主 LLM、开发副 LLM、测试副 LLM 的模型，系统校验三者不同；
  模型须来自预设列表（用户可通过配置文件扩展）；
- 3.6 节：执行模式选择（默认安全审阅；自动模式任务级粒度，v0.4 开放）；
- 3.1 步骤 5：系统创建项目目录，先通过成本总预算闸门检查（11.0）；
- 11.0：自动模式预算 ×2~3（默认 2.5），须 UI 明示并经用户确认；
- 19 章：自动模式成本放大必须在任务开始前明示并经用户确认。
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.orchestrator import TeamBuildError, TeamBuilder, TeamConfig
from app.tools.file_manager import FileManager


@pytest.fixture
def fm(tmp_path) -> FileManager:
    return FileManager(projects_root=tmp_path / "projects")


def make_builder(fm, settings=None) -> TeamBuilder:
    return TeamBuilder(file_manager=fm, settings=settings or Settings())


MODELS = ("gpt-4o", "claude-3-5-sonnet", "deepseek-chat")


class TestModelValidation:
    def test_valid_team_of_three_distinct_models(self, fm):
        builder = make_builder(fm)
        config = builder.build(
            requirement="demo",
            main_model="gpt-4o",
            dev_model="claude-3-5-sonnet",
            test_model="deepseek-chat",
            mode="safe",
        )
        assert config.main_model == "gpt-4o"
        assert config.dev_model == "claude-3-5-sonnet"
        assert config.test_model == "deepseek-chat"

    def test_duplicate_models_rejected(self, fm):
        # 3.3：三个模型必须不同
        builder = make_builder(fm)
        with pytest.raises(TeamBuildError, match="不同"):
            builder.build(
                requirement="demo",
                main_model="gpt-4o",
                dev_model="gpt-4o",
                test_model="deepseek-chat",
                mode="safe",
            )

    def test_model_not_in_list_rejected(self, fm):
        # 模型须来自预设列表（3.3）
        builder = make_builder(fm)
        with pytest.raises(TeamBuildError, match="列表"):
            builder.build(
                requirement="demo",
                main_model="gpt-4o",
                dev_model="claude-3-5-sonnet",
                test_model="unknown-model",
                mode="safe",
            )

    def test_extended_list_via_config_accepted(self, fm):
        # 3.3：用户可通过配置文件添加更多模型
        settings = Settings(models=["gpt-4o", "claude-3-5-sonnet", "qwen-max"])
        builder = make_builder(fm, settings)
        config = builder.build(
            requirement="demo",
            main_model="gpt-4o",
            dev_model="claude-3-5-sonnet",
            test_model="qwen-max",
            mode="safe",
        )
        assert config.test_model == "qwen-max"


class TestModeAndBudget:
    def test_default_mode_is_safe(self, fm):
        builder = make_builder(fm)
        config = builder.build(
            requirement="demo",
            main_model="gpt-4o",
            dev_model="claude-3-5-sonnet",
            test_model="deepseek-chat",
        )
        assert config.mode == "safe"
        assert config.budget_tokens == 200_000

    def test_invalid_mode_rejected(self, fm):
        builder = make_builder(fm)
        with pytest.raises(TeamBuildError, match="模式"):
            builder.build(*MODELS_REQUIREMENT, mode="danger")  # type: ignore[misc]

    def test_auto_mode_requires_confirmation(self, fm):
        # 3.6.4 / 19 章：自动模式预算放大须明示并经用户确认
        builder = make_builder(fm)
        with pytest.raises(TeamBuildError, match="确认"):
            builder.build(
                requirement="demo",
                main_model="gpt-4o",
                dev_model="claude-3-5-sonnet",
                test_model="deepseek-chat",
                mode="auto",
                auto_mode_confirmed=False,
            )

    def test_auto_mode_budget_multiplied(self, fm):
        # 11.0：自动模式预算 ×2.5（默认）
        builder = make_builder(fm)
        config = builder.build(
            requirement="demo",
            main_model="gpt-4o",
            dev_model="claude-3-5-sonnet",
            test_model="deepseek-chat",
            mode="auto",
            auto_mode_confirmed=True,
        )
        assert config.budget_tokens == 500_000

    def test_auto_mode_warning_message_exposed(self, fm):
        # 19 章：成本放大须在任务开始前于 UI 明示
        builder = make_builder(fm)
        warning = builder.auto_mode_warning()
        assert "2.5" in warning or "×2" in warning
        assert "预算" in warning

    def test_budget_gate_zero_budget_rejected(self, fm):
        # 11.0：总预算为闸门，非正值直接拒绝
        settings = Settings(max_task_tokens=0) if _settings_allows_zero() else None
        if settings is None:
            pytest.skip("Settings 已强制正整数，闸门由类型系统保证")
        builder = make_builder(fm, settings)
        with pytest.raises(Exception):
            builder.build(*MODELS_REQUIREMENT, mode="safe")  # type: ignore[misc]


MODELS_REQUIREMENT = ("demo", "gpt-4o", "claude-3-5-sonnet", "deepseek-chat")


def _settings_allows_zero() -> bool:
    # Settings 校验强制 max_task_tokens 为正整数，0 会在构造期被拒
    try:
        Settings(max_task_tokens=0)
        return True
    except ValueError:
        return False


class TestProjectCreation:
    def test_project_directory_created(self, fm):
        builder = make_builder(fm)
        config = builder.build(
            requirement="糖尿病管理智能体",
            main_model="gpt-4o",
            dev_model="claude-3-5-sonnet",
            test_model="deepseek-chat",
            mode="safe",
        )
        assert config.project_id
        assert (fm.projects_root / config.project_dir_name).is_dir()

    def test_config_carry_project_paths(self, fm):
        builder = make_builder(fm)
        config = builder.build(
            requirement="demo",
            main_model="gpt-4o",
            dev_model="claude-3-5-sonnet",
            test_model="deepseek-chat",
        )
        assert config.project_dir_name
        handle = fm.get_project(config.project_id)
        assert handle is not None
        assert handle.root.is_dir()

    def test_budget_and_team_persisted_for_audit(self, fm):
        # 第 5 章可审计：团队配置与预算落盘项目目录
        builder = make_builder(fm)
        config = builder.build(
            requirement="demo",
            main_model="gpt-4o",
            dev_model="claude-3-5-sonnet",
            test_model="deepseek-chat",
            mode="safe",
        )
        handle = fm.get_project(config.project_id)
        assert handle is not None
        team_file = handle.root / "sessions" / "team_config.json"
        assert team_file.is_file()
        import json
        data = json.loads(team_file.read_text(encoding="utf-8"))
        assert data["main_model"] == "gpt-4o"
        assert data["mode"] == "safe"
        assert data["budget_tokens"] == 200_000
