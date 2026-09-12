"""v1.2 S1 测试:repo-patch 模式(issue → 最小补丁 → 仓库测试验证)。

场景:真实 git 仓库中 calc.add 存在减法 bug,issue 描述正确行为——
LLM(脚本桩)输出修复方案与完整新版文件,RepoFixer 应用并跑仓库测试;
覆盖 多文件/路径越界拒绝/修复轮不收敛/无 git 仓库 等边界。
"""

from __future__ import annotations

import json
import shutil
import sys
import subprocess

import pytest

from app.agents.repo_fixer import RepoFixer

BUGGY_CALC = "def add(a, b):\n    return a - b\n"
FIXED_CALC = "def add(a, b):\n    return a + b\n"
STILL_BUGGY = "def add(a, b):\n    return a - b - 1\n"
TEST_CALC = (
    "from calc import add\n\n"
    "def test_add():\n    assert add(2, 3) == 5\n"
)
PLAN = {
    "analysis": "add 实现为减法",
    "files": [{"path": "calc.py", "change": "改为 a + b"}],
}
PLAN_TRAVERSAL = {
    "analysis": "越界写入",
    "files": [{"path": "../evil.py", "change": "越界"}],
}


class FakeLLM:
    """按提示词特征路由的脚本桩:plan / patch / repatch。"""

    def __init__(self, plan, patch_contents, repatch=None):
        self.plan = plan
        self.patch_contents = list(patch_contents)
        self.repatch = repatch
        self.prompts = []

    def __call__(self, system, user):
        self.prompts.append((system, user))
        if "已改文件" in user:
            if self.repatch is None:
                return "{}"
            return json.dumps({"files": self.repatch}, ensure_ascii=False)
        if "仓库文件树" in user:
            return json.dumps(self.plan, ensure_ascii=False)
        if "当前文件内容" in user:
            content = (self.patch_contents.pop(0)
                       if self.patch_contents else STILL_BUGGY)
            return content
        return "ok"


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    def git(*args):
        subprocess.run(["git", *args], cwd=root, check=True,
                       capture_output=True, text=True)
    git("init", "-q")
    git("config", "user.name", "tester")
    git("config", "user.email", "t@local")
    (root / "calc.py").write_text(BUGGY_CALC, encoding="utf-8")
    (root / "test_calc.py").write_text(TEST_CALC, encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    return root


@pytest.fixture(scope="module")
def _git_guard():
    if shutil.which("git") is None:
        pytest.skip("环境无 git")


def _fixer(llm, repo, **kw):
    return RepoFixer(llm, repo, test_cmd=[sys.executable, "-m", "pytest", "-q"],
                     **kw)


@pytest.mark.usefixtures("_git_guard")
class TestRepoFixer:
    def test_minimal_patch_turns_tests_green(self, repo):
        fixer = _fixer(FakeLLM(PLAN, [FIXED_CALC]), repo, max_rounds=2)
        result = fixer.fix("calc.add 返回了差而不是和",
                           test_files=["test_calc.py"])
        assert result.ok is True
        assert result.changed_files == ["calc.py"]
        assert result.rounds == 1
        assert "calc.py" in result.diff
        assert (repo / "calc.py").read_text(encoding="utf-8").strip() == FIXED_CALC.strip()

    def test_multi_file_patch(self, repo):
        plan = {"analysis": "双文件", "files": [
            {"path": "calc.py", "change": "改和"},
            {"path": "helper.py", "change": "新增常量"},
        ]}
        llm = FakeLLM(plan, ["def add(a, b):\n    return a + b\n",
                             "ANSWER = 5\n"])
        fixer = _fixer(llm, repo, max_rounds=1)
        result = fixer.fix("add 错误", test_files=["test_calc.py"])
        assert result.ok is True
        assert sorted(result.changed_files) == ["calc.py", "helper.py"]
        assert (repo / "helper.py").exists()

    def test_fix_loop_recovers(self, repo):
        # 第 1 版补丁仍是错的 → 修复轮带失败输出重出正确版
        llm = FakeLLM(PLAN, [STILL_BUGGY],
                      repatch=[{"path": "calc.py", "content": FIXED_CALC}])
        fixer = _fixer(llm, repo, max_rounds=3)
        result = fixer.fix("calc.add 返回了差", test_files=["test_calc.py"])
        assert result.ok is True
        assert result.rounds == 2
        # 修复轮提示携带失败输出与已改文件
        repatch_prompts = [u for _, u in llm.prompts if "已改文件" in u]
        assert any("测试失败输出" in u for u in repatch_prompts)

    def test_never_converges_reports_error(self, repo):
        llm = FakeLLM(PLAN, [STILL_BUGGY, STILL_BUGGY, STILL_BUGGY])
        fixer = _fixer(llm, repo, max_rounds=3)
        result = fixer.fix("calc.add 返回了差", test_files=["test_calc.py"])
        assert result.ok is False
        assert result.rounds == 3
        assert "验证" in result.error

    def test_path_traversal_rejected(self, repo):
        llm = FakeLLM(PLAN_TRAVERSAL, [])
        fixer = _fixer(llm, repo, max_rounds=1)
        result = fixer.fix("越界", test_files=[])
        assert result.ok is False
        assert result.skipped_paths == ["../evil.py"]
        assert not (repo.parent / "evil.py").exists()

    def test_no_git_repo_still_repairs(self, tmp_path):
        """r4 修订：无 .git 照常修复（diff 为空）——平台路径 enable_git=False，
        旧硬拒绝曾让交付修复安全网在参赛路径恒为死路。"""
        bare = tmp_path / "not_a_repo"
        (bare / "calc").mkdir(parents=True)
        (bare / "calc" / "calc.py").write_text(BUGGY_CALC, encoding="utf-8")
        (bare / "tests").mkdir()
        (bare / "tests" / "test_calc.py").write_text(TEST_CALC, encoding="utf-8")
        fixer = _fixer(FakeLLM(PLAN, [FIXED_CALC]), bare)
        result = fixer.fix("add 应为加法")
        assert result.ok is True
        assert result.diff == ""  # 无 git，diff 报告为空但不影响修复
