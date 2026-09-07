"""v1.2 S2 测试:SWE-bench 抽样器(分层/去重/黑名单/种子可复现)。

runner 本体为脚本(scripts/swebench_run.py),真实跑分需 API Key 与
数据集文件;此处对纯函数抽样逻辑做确定性验证。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from swebench_run import REPO_SKIP_HINTS, sample_instances  # noqa: E402


def _mk(repo, i):
    return {"repo": repo, "instance_id": f"{repo}-{i}",
            "base_commit": f"c{i}", "FAIL_TO_PASS": "[]"}


class TestSampler:
    def test_sample_size_respected(self):
        insts = [_mk("org/repo", i) for i in range(100)]
        picked = sample_instances(insts, 50, 42)
        assert len(picked) == 50

    def test_seed_reproducible(self):
        insts = [_mk("org/repo", i) for i in range(80)]
        a = sample_instances(insts, 30, 7)
        b = sample_instances(insts, 30, 7)
        assert [x["instance_id"] for x in a] == [x["instance_id"] for x in b]

    def test_heavy_runtime_repos_excluded(self):
        insts = ([_mk("django/django", i) for i in range(10)]
                 + [_mk("org/ok", i) for i in range(5)])
        picked = sample_instances(insts, 15, 42)
        assert all(not any(h in p["repo"].lower()
                           for h in REPO_SKIP_HINTS) for p in picked)
        assert {p["repo"] for p in picked} == {"org/ok"}

    def test_sample_larger_than_pool_terminates(self):
        """可用实例少于 sample 时必须终止(CI 第五跑取证:曾死循环)。"""
        insts = [_mk("org/only", i) for i in range(5)]
        picked = sample_instances(insts, 30, 42)
        assert len(picked) == 5

    def test_multi_repo_spread(self):
        insts = ([_mk(f"org{i}/repo", 0) for i in range(5)]
                 + [_mk(f"org{i}/repo", 1) for i in range(5)])
        picked = sample_instances(insts, 6, 42)
        repos = {p["repo"] for p in picked}
        assert len(repos) >= 3  # 分层:不把名额全给单一仓库
