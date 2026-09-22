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
        # repatch=None → 每轮同一版错误补丁 → 失败输出本质相同 →
        # 2026-09-20 止损语义：第 2 轮判定无进展立即退出（烧满轮次
        # 却零收敛是平台双跑 ¥130 级失血点）
        llm = FakeLLM(PLAN, [STILL_BUGGY, STILL_BUGGY, STILL_BUGGY])
        fixer = _fixer(llm, repo, max_rounds=3)
        result = fixer.fix("calc.add 返回了差", test_files=["test_calc.py"])
        assert result.ok is False
        assert result.rounds == 2
        assert "无进展止损" in result.error

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


# ---- 语法拒收：护栏必须挡住垃圾写，但不得把文件踢出修复线 ----

BROKEN_CALC = "def add(a, b):\n    return a + b\n<<<<<<< HEAD\n"
PLAN_HELPER = {"analysis": "双文件", "files": [
    {"path": "calc.py", "change": "改和"},
    {"path": "helper.py", "change": "新增常量"},
]}


@pytest.mark.usefixtures("_git_guard")
class TestSyntaxRejection:
    def test_rejected_file_is_not_written(self, repo):
        """垃圾写不落盘：坏内容进不了磁盘，旧合法版本原样保留。"""
        fixer = _fixer(FakeLLM(PLAN, [BROKEN_CALC]), repo, max_rounds=1)
        result = fixer.fix("calc.add 返回了差", test_files=["test_calc.py"])
        assert result.ok is False
        assert (repo / "calc.py").read_text(encoding="utf-8") == BUGGY_CALC

    def test_rejected_file_stays_in_repair_line(self, repo):
        """keep 彩排取证：同一文件连拒 4 轮——旧实现把拒收文件从 changed
        弹出，模型此后再没机会改它，且下一轮提示词里看到的是自己那份
        非法草稿。现：打回磁盘版 + 点名拒收原因。"""
        llm = FakeLLM(PLAN, [BROKEN_CALC],
                      repatch=[{"path": "calc.py", "content": FIXED_CALC}])
        result = _fixer(llm, repo, max_rounds=3).fix(
            "calc.add 返回了差", test_files=["test_calc.py"])
        assert result.ok is True
        assert result.rounds == 2
        assert (repo / "calc.py").read_text(encoding="utf-8").strip() \
            == FIXED_CALC.strip()
        repatch_prompt = next(u for _, u in llm.prompts if "已改文件" in u)
        assert "系统拒收清单" in repatch_prompt
        assert "invalid syntax" in repatch_prompt        # 带原因，不是空喊
        assert "<<<<<<< HEAD" not in repatch_prompt      # 草稿未污染下一轮
        assert "return a - b" in repatch_prompt          # 起点是磁盘现行版

    def test_repatch_omitting_a_file_does_not_shrink_repair_set(self, repo):
        """模型漏发某个已改文件时沿用上一版内容，修复集只增不减。"""
        llm = FakeLLM(PLAN_HELPER, ["def add(a, b):\n    return a - b\n",
                                    "ANSWER = 5\n"],
                      repatch=[{"path": "calc.py", "content": FIXED_CALC}])
        result = _fixer(llm, repo, max_rounds=3).fix(
            "add 错误", test_files=["test_calc.py"])
        assert result.ok is True
        assert sorted(result.changed_files) == ["calc.py", "helper.py"]
        assert (repo / "helper.py").read_text(encoding="utf-8").strip() == "ANSWER = 5"

    def test_verify_ignores_stale_bytecode(self, repo):
        """等长同秒覆写不得让验证跑在陈旧字节码上（假红 → 修复震荡）。

        BUGGY/FIXED 恰好同长度，pyc 的「mtime 秒级 + 源大小」双重校验
        双双命中时子进程仍导入旧代码——arcbench_smoke 早已为此清缓存，
        repo_fixer 的验证通道漏了同源的一手（测试污染时真实复现过）。
        """
        import os
        import py_compile

        calc = repo / "calc.py"
        stamp = 1_700_000_000                      # 钉死整秒，绕开 mtime 失效
        calc.write_text(BUGGY_CALC, encoding="utf-8")
        os.utime(calc, (stamp, stamp))
        py_compile.compile(str(calc), doraise=True)
        calc.write_text(FIXED_CALC, encoding="utf-8")
        os.utime(calc, (stamp, stamp))             # 同秒等长：缓存自证有效

        cache = next(repo.rglob("__pycache__"), None)
        assert cache is not None, "前置失效：未生成 pyc"
        passed, out = _fixer(FakeLLM(PLAN, [FIXED_CALC]), repo)._verify(
            [sys.executable, "-m", "pytest", "-q"], ["test_calc.py"])
        assert passed is True, out[-400:]

    def test_verify_timeout_is_a_failed_round_not_a_crash(self, repo,
                                                          monkeypatch):
        """被测程序挂住（死循环/常驻服务）属于修复要处理的失败。

        旧行为：subprocess.TimeoutExpired 直接上抛，吃掉整条修复线与
        本轮已烧的 token，且调用方只能看到「自动修复异常」。
        """
        import subprocess as sp

        def boom(*a, **kw):
            raise sp.TimeoutExpired(cmd=["pytest"], timeout=300)

        monkeypatch.setattr("app.agents.repo_fixer.subprocess.run", boom)
        passed, out = _fixer(FakeLLM(PLAN, [FIXED_CALC]), repo)._verify(
            [sys.executable, "-m", "pytest", "-q"], ["test_calc.py"])
        assert passed is False
        assert "超时" in out and "无限循环" in out

        monkeypatch.setattr("app.agents.repo_fixer.subprocess.run",
                            lambda *a, **kw: (_ for _ in ()).throw(
                                FileNotFoundError("python")))
        passed, out = _fixer(FakeLLM(PLAN, [FIXED_CALC]), repo)._verify(
            ["python"], None)
        assert passed is False and "启动失败" in out

    def test_timeout_ends_fix_loop_with_reason(self, repo, monkeypatch):
        """端到端：超时走完 max_rounds 后给出可读 error，而非抛异常。"""
        import subprocess as sp

        def boom(*a, **kw):
            raise sp.TimeoutExpired(cmd=["pytest"], timeout=300)

        monkeypatch.setattr("app.agents.repo_fixer.subprocess.run", boom)
        llm = FakeLLM(PLAN, [FIXED_CALC],
                      repatch=[{"path": "calc.py", "content": FIXED_CALC}])
        result = _fixer(llm, repo, max_rounds=2).fix("add 错误",
                                                     test_files=["test_calc.py"])
        assert result.ok is False
        assert "超时" in result.error          # 原因可读，不是「自动修复异常」
        assert result.ok is False
        assert "超时" in result.error or "验证" in result.error
