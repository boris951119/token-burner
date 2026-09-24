# -*- coding: utf-8 -*-
"""同一文件连续语法非法即冻结整文件重写（run 088dd22be41b 实证）：那一跑的
修复日志里「拒收语法非法的修复内容」出现 4 次，每次背后都是一整轮 LLM 调用，
最后修环死于预算耗尽——4 轮换回 0 行落盘。语法非法是确定性事实，
不需要模型再猜第三次。"""
from __future__ import annotations

import json
import re
import sys

import pytest

import app.agents.repo_fixer as rfm
from app.agents.repo_fixer import RepoFixer

INVALID = "def broken(:\n    return 1\n"
VALID = "def broken(a):\n    return a + 1\n"
HELPER_NEW = "X = 2\n"
PLAN_CALC = {"analysis": "修 calc", "files": [{"path": "calc.py",
                                              "change": "补齐语法"}]}

FAIL_CMD = [sys.executable, "-c", "raise SystemExit(1)"]


@pytest.fixture(autouse=True)
def _reset_module_state():
    """冻结表挂在进程上（RepoFixer 按次构造，跨轮次计数只能这样）：
    测试之间必须互不残留，否则用例顺序一变就假红/假绿。"""
    rfm._SYNTAX_FAILS.clear()
    rfm._FROZEN.clear()
    yield
    rfm._SYNTAX_FAILS.clear()
    rfm._FROZEN.clear()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "calc.py").write_text("def add(a, b):\n    return a - b\n",
                                  encoding="utf-8")
    return root


class Stub:
    """按提示词特征分流的桩：计划轮出清单，内容轮按 `## 目标文件` 回内容。"""

    _TARGET = re.compile(r"## 目标文件\n(.+)")

    def __init__(self, plan, by_path, default=""):
        self.plan = plan
        self.by_path = by_path
        self.default = default
        self.calls = []

    def __call__(self, system, user):
        self.calls.append(user)
        if "仓库文件树" in user:
            return json.dumps(self.plan, ensure_ascii=False)
        m = self._TARGET.search(user)
        return self.by_path.get(m.group(1).strip(), self.default) if m else self.default


def test_second_rejection_freezes_the_file(repo):
    fixer = RepoFixer(Stub(PLAN_CALC, {}, VALID), repo, test_cmd=FAIL_CMD)
    key = f"{fixer.repo}::calc.py"

    rejected = fixer._apply({"calc.py": INVALID})
    assert len(rejected) == 1 and key not in rfm._FROZEN
    assert "冻结" not in rejected[0][1], "首次只报语法错，别提前吓退模型"

    rejected = fixer._apply({"calc.py": INVALID})
    assert key in rfm._FROZEN
    msg = rejected[0][1]
    assert "冻结" in msg and "别再重发这个文件" in msg


def test_counters_are_per_file(repo):
    """冻结判据必须是「同一个文件」连续两次：两个文件各撞一次不该冻结任何一个。"""
    fixer = RepoFixer(Stub(PLAN_CALC, {}, VALID), repo, test_cmd=FAIL_CMD)
    fixer._apply({"calc.py": INVALID})
    fixer._apply({"other.py": INVALID})
    assert not rfm._FROZEN, rfm._FROZEN
    fixer._apply({"calc.py": INVALID})
    assert rfm._FROZEN == {f"{fixer.repo}::calc.py"}


def test_fix_stops_before_burning_the_remaining_rounds(repo):
    """省额度的实证：max_rounds=3 时第 2 轮就收手，第 3 轮的 LLM 调用不发生。"""
    stub = Stub(PLAN_CALC, {"calc.py": INVALID})
    fixer = RepoFixer(stub, repo, test_cmd=FAIL_CMD, max_rounds=3)
    result = fixer.fix("calc.py 语法非法")
    assert result.rounds == 2
    assert "冻结" in result.error and "calc.py" in result.error
    # 1 次计划 + 1 次首轮出码 + 1 次拒收后重出 = 3 次；没有第 4 次
    assert len(stub.calls) == 3, len(stub.calls)
    assert (repo / "calc.py").read_text(encoding="utf-8").startswith("def add")


def test_one_frozen_file_does_not_veto_the_batch(repo):
    """冻结的是文件，不是整批修复：同批还有可改目标时必须继续烧完轮次。"""
    (repo / "helpers.py").write_text("X = 1\n", encoding="utf-8")
    plan = {"analysis": "两个文件", "files": [
        {"path": "calc.py", "change": "补齐语法"},
        {"path": "helpers.py", "change": "加一个常量"}]}
    stub = Stub(plan, {"calc.py": INVALID, "helpers.py": HELPER_NEW})
    fixer = RepoFixer(stub, repo, test_cmd=FAIL_CMD, max_rounds=2)
    rfm._FROZEN.add(f"{fixer.repo}::calc.py")
    result = fixer.fix("修两个文件")
    assert "冻结" not in result.error, "helpers 不在冻结名单，批次不该提前收手"
    assert result.rounds == 2
    assert (repo / "helpers.py").read_text(encoding="utf-8").strip() == \
        HELPER_NEW.strip()
    assert (repo / "calc.py").read_text(encoding="utf-8").startswith("def add")
