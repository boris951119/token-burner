"""M7-2 性能基线（标准任务集 × 固定剧本：token / 时间 / 成功率可对比）。

产物 logs/perf_baseline.json（仓库根，.gitignore 已忽略）：
    {"version", "generated_at", "cases": [{name, tokens, elapsed_ms, status}]}
后续版本重跑同集对比，支撑「同等质量 Token 下降 ≥20%」叙事。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "perf_baseline.py"
if not _SCRIPT.is_file():
    raise ImportError(f"缺少性能基线脚本: {_SCRIPT}")
_spec = importlib.util.spec_from_file_location("perf_baseline", _SCRIPT)
perf = importlib.util.module_from_spec(_spec)
sys.modules["perf_baseline"] = perf
_spec.loader.exec_module(perf)


class TestPerfBaseline:
    def test_run_baseline_structure_and_success(self, tmp_path):
        """基线运行：3 档任务全部成功，指标结构完整。"""
        report = perf.run_baseline(out_path=tmp_path / "perf.json")
        assert report["version"]
        assert len(report["cases"]) == len(perf.CASES)
        for case in report["cases"]:
            assert case["status"] == "succeeded", case.get("error")
            assert case["tokens"] > 0
            assert case["elapsed_ms"] >= 0
        saved = json.loads((tmp_path / "perf.json").read_text(encoding="utf-8"))
        assert saved["cases"] == report["cases"]

    def test_baseline_is_deterministic_per_fixed_scripts(self, tmp_path):
        """固定剧本 → token 消耗可复现（对比不同版本的前提）。"""
        r1 = perf.run_baseline(out_path=tmp_path / "a.json")
        r2 = perf.run_baseline(out_path=tmp_path / "b.json")
        assert [c["tokens"] for c in r1["cases"]] == \
               [c["tokens"] for c in r2["cases"]]
