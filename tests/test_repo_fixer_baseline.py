"""v55 RepoFixer 重写基线层：劣化回滚 / 改进接受。"""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from app.agents.repo_fixer import RepoFixer

# 基线：add 正确 + mul 正确 → 2 passed
BASELINE_CALC = (
    "def add(a, b):\n"
    "    return a + b\n"
    "\n"
    "def mul(a, b):\n"
    "    return a * b\n"
)
# 劣化：弄坏 mul → 1 passed
WORSE_CALC = (
    "def add(a, b):\n"
    "    return a + b\n"
    "\n"
    "def mul(a, b):\n"
    "    return a + b\n"  # 错
)
# 改进：再加 sub → 3 passed（测试文件同步多一条时）
BETTER_CALC = (
    "def add(a, b):\n"
    "    return a + b\n"
    "\n"
    "def mul(a, b):\n"
    "    return a * b\n"
    "\n"
    "def sub(a, b):\n"
    "    return a - b\n"
)

TEST_TWO = (
    "from calc import add, mul\n"
    "\n"
    "def test_add():\n"
    "    assert add(2, 3) == 5\n"
    "\n"
    "def test_mul():\n"
    "    assert mul(2, 3) == 6\n"
)
TEST_THREE = (
    TEST_TWO
    + "\n"
    "def test_sub():\n"
    "    from calc import sub\n"
    "    assert sub(5, 2) == 3\n"
)

PLAN = {
    "analysis": "rewrite calc",
    "files": [{"path": "calc.py", "change": "整文件重写"}],
}


class FakeLLM:
    _TARGET = re.compile(r"## 目标文件\n(.+)")

    def __init__(self, plan, patch_contents, repatch=None):
        self.plan = plan
        self.patch_contents = list(patch_contents)
        self.repatch = repatch or {}
        self.prompts = []

    def __call__(self, system, user):
        self.prompts.append((system, user))
        if "仓库文件树" in user:
            return json.dumps(self.plan, ensure_ascii=False)
        if "测试失败输出" in user:
            m = self._TARGET.search(user)
            return self.repatch.get(m.group(1).strip(), "") if m else ""
        if "当前文件内容" in user:
            return (self.patch_contents.pop(0)
                    if self.patch_contents else BASELINE_CALC)
        return "ok"


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        subprocess.run(
            ["git", *args], cwd=root, check=True,
            capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.name", "tester")
    git("config", "user.email", "t@local")
    (root / "calc.py").write_text(BASELINE_CALC, encoding="utf-8")
    (root / "test_calc.py").write_text(TEST_TWO, encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    return root


def _fixer(llm, repo, **kw):
    cmd = [sys.executable, "-m", "pytest", "-q"]
    return RepoFixer(
        llm, repo, test_cmd=cmd, baseline_test_cmd=cmd, **kw)


def test_rewrite_worse_than_baseline_rolls_back(repo):
    """基线 2 过 → 重写后 1 过 → 回滚到重写前内容。"""
    llm = FakeLLM(PLAN, [WORSE_CALC])
    fixer = _fixer(llm, repo, max_rounds=1)
    before = (repo / "calc.py").read_text(encoding="utf-8")
    result = fixer.fix("改 calc", test_files=["test_calc.py"])
    after = (repo / "calc.py").read_text(encoding="utf-8")
    assert after == before
    assert after.strip() == BASELINE_CALC.strip()
    assert result.ok is False


def test_rewrite_better_or_equal_is_accepted(repo):
    """基线 2 过 → 重写后 3 过 → 接受新版本。"""
    (repo / "test_calc.py").write_text(TEST_THREE, encoding="utf-8")
    llm = FakeLLM(PLAN, [BETTER_CALC])
    fixer = _fixer(llm, repo, max_rounds=1)
    result = fixer.fix("扩展 calc", test_files=["test_calc.py"])
    after = (repo / "calc.py").read_text(encoding="utf-8")
    assert after.strip() == BETTER_CALC.strip()
    assert result.ok is True


def test_degrade_note_appended_to_next_repatch(repo):
    """劣化回滚后，下一轮修复指令须含基线 X 过/新版 Y 过。"""
    # 第一轮劣化；第二轮仍劣化（max_rounds=2）→ 第二轮 user 含护栏文案
    llm = FakeLLM(PLAN, [WORSE_CALC], repatch={"calc.py": WORSE_CALC})
    fixer = _fixer(llm, repo, max_rounds=2)
    fixer.fix("改 calc", test_files=["test_calc.py"])
    joined = "\n".join(u for _, u in llm.prompts)
    assert "基线" in joined and "过" in joined
    assert "请换思路或最小化修改" in joined
