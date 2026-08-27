"""git_manager 单元测试（TDD 先行）。

依据：规格文档 14 章——生成项目仓库的本地 git 版本管理：
- 项目创建后 git init（本地，免推送）；
- 阶段性提交：spec 确认后 / 每模块完成后 / 集成（交付汇总）后；
- 提交信息含阶段语义（可追溯哪个阶段产出了哪些文件）。
命令执行器可注入（单元测试零 git 依赖），并提供真实 git 集成测试。
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from app.tools.file_manager import FileManager
from app.tools.git_manager import GitManager


@pytest.fixture
def fm(tmp_path):
    return FileManager(projects_root=tmp_path / "projects")


class CommandRecorder:
    """记录全部命令的桩执行器。"""

    def __init__(self):
        self.commands: list[tuple[str, str]] = []  # (cwd, command)

    def __call__(self, cwd: str, *args: str) -> str:
        self.commands.append((str(cwd), "git " + " ".join(args)))
        return "ok"


class TestInit:
    def test_init_runs_git_init_in_project_root(self, fm):
        rec = CommandRecorder()
        project = fm.create_project("测试项目")
        GitManager(runner=rec).init(project.root)
        cwd, cmd = rec.commands[0]
        assert cwd == str(project.root)
        assert "git init" in cmd

    def test_no_push_commands_ever(self, fm):
        # 14 章：本地 git 免推送
        rec = CommandRecorder()
        project = fm.create_project("测试项目")
        gm = GitManager(runner=rec)
        gm.init(project.root)
        gm.commit_stage(project.root, "spec", "spec 确认")
        for _cwd, cmd in rec.commands:
            assert "push" not in cmd
            assert "remote" not in cmd


class TestCommitStages:
    def test_commit_spec_stage(self, fm):
        rec = CommandRecorder()
        project = fm.create_project("测试项目")
        gm = GitManager(runner=rec)
        gm.init(project.root)
        fm.write_module_spec(project.project_id, "user", "# spec")
        gm.commit_stage(project.root, "spec", "spec 确认")
        # add + commit 两条
        cmds = [c for _cwd, c in rec.commands]
        assert any("git add" in c for c in cmds)
        assert any("git commit" in c and "spec" in c for c in cmds)

    def test_commit_message_contains_stage_and_detail(self, fm):
        rec = CommandRecorder()
        project = fm.create_project("测试项目")
        GitManager(runner=rec).commit_stage(project.root, "module:user", "模块完成")
        commit_cmd = next(c for _c, c in rec.commands if "git commit" in c)
        assert "module:user" in commit_cmd
        assert "模块完成" in commit_cmd

    def test_stage_kinds_documented(self):
        # 14 章三阶段：spec / module / integration
        for stage in ("spec", "module:user", "integration"):
            assert ":" not in stage or stage.split(":")[0] == "module"


class TestRealGitIntegration:
    """真实 git 集成（无 git 时跳过）。"""

    @pytest.fixture(autouse=True)
    def _require_git(self):
        if shutil.which("git") is None:
            pytest.skip("环境无 git")

    def test_real_init_and_commits(self, fm):
        project = fm.create_project("git 集成测试")
        gm = GitManager()  # 真实执行器
        gm.init(project.root)
        fm.write_module_spec(project.project_id, "user", "# 用户模块 spec")
        gm.commit_stage(project.root, "spec", "spec 确认")
        fm.write_code_file(project.project_id, "user", "user.py", "x = 1\n")
        gm.commit_stage(project.root, "module:user", "模块完成")
        gm.commit_stage(project.root, "integration", "集成完成")
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=project.root, capture_output=True, text=True,
        )
        assert log.returncode == 0
        messages = log.stdout.strip().splitlines()
        assert len(messages) == 3
        assert "spec" in messages[2]
        assert "integration" in messages[0]


class TestPipelineIntegration:
    def test_pipeline_commits_three_stages(self, fm):
        # 端到端：管线在 spec / 每模块 / 集成 三阶段自动提交
        from tests.test_pipeline import FakeExecutor, ScriptedLLM, team_scripts
        from app.config import Settings
        from app.pipeline import Pipeline

        rec = CommandRecorder()
        llm = ScriptedLLM(team_scripts())
        pipeline = Pipeline(
            llm=llm,
            executor=FakeExecutor(["SUCCESS"] * 3),
            settings=Settings(enable_git=True),
            file_manager=fm,
            git_manager_factory=lambda: GitManager(runner=rec),
        )
        result = pipeline.run(
            "开发用户系统",
            models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe",
            spec_confirm="确认",
        )
        assert result.kind == "team_flow"
        commits = [c for _c, c in rec.commands if "git commit" in c]
        # spec 1 + 模块 3 + 集成 1 = 5
        assert len(commits) == 5
        assert any("spec" in c for c in commits)
        assert sum(1 for c in commits if "module:" in c) == 3
        assert any("integration" in c for c in commits)

    def test_git_disabled_no_commands(self, fm):
        from tests.test_pipeline import FakeExecutor, ScriptedLLM, team_scripts
        from app.config import Settings
        from app.pipeline import Pipeline

        rec = CommandRecorder()
        llm = ScriptedLLM(team_scripts())
        pipeline = Pipeline(
            llm=llm,
            executor=FakeExecutor(["SUCCESS"] * 3),
            settings=Settings(enable_git=False),
            file_manager=fm,
            git_manager_factory=lambda: GitManager(runner=rec),
        )
        result = pipeline.run(
            "开发用户系统",
            models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe",
            spec_confirm="确认",
        )
        assert result.kind == "team_flow"
        assert rec.commands == []  # 关闭后零 git 调用
