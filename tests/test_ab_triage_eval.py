"""M9-4 快慢双模式 A/B 评测测试（mock 离线；真实运行见 scripts/ab_triage_eval.py --real）。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ab_triage_eval.py"
_spec = importlib.util.spec_from_file_location("ab_triage_eval", _SCRIPT)
abe = importlib.util.module_from_spec(_spec)
sys.modules["ab_triage_eval"] = abe
_spec.loader.exec_module(abe)


class TestStandardCaseSet:
    def test_case_set_composition(self):
        """标准诉求集：4 类 × 5，期望出口齐全（单/双模式各自基线）。"""
        cats = {}
        for c in abe.CASES:
            cats.setdefault(c["cat"], 0)
            cats[c["cat"]] += 1
        assert cats == {"闲聊": 5, "基础问答": 5, "简单编程": 5, "复杂编程": 5}
        assert all(c["expect_dual"] in abe._EXPECTED_BY_ROUTE for c in abe.CASES)


class TestSingleMode:
    def test_single_mode_baseline(self):
        """单模式（快判关）：全部走 System-2 评估，路由出口正确、零误判。

        token 6300 = 20 条 × 300 + 300：「什么是 REST API？」命中执行类
        关键词（D.1 边界护栏）触发一次复核重评估——正确的护栏语义。
        """
        r = abe.run_suite(False)
        assert r["mode"] == "single"
        assert r["cases_total"] == 20
        assert r["misclassified"] == 0
        assert r["triaged_by_fast_path"] == 0
        assert r["llm_tokens"] == 6300
        assert r["llm_calls"] == 21


class TestDualMode:
    def test_dual_mode_triages_cheap_intents(self):
        """双模式：闲聊 5 + 基础 4 被快判承接；「REST API」命中执行类
        信号被护栏放行升级（D.1 优先于快判结论）+ 复核重评估。"""
        r = abe.run_suite(True)
        assert r["mode"] == "dual"
        assert r["misclassified"] == 0
        assert r["triaged_by_fast_path"] == 9
        assert r["triage_rate"] == 0.45
        # 20 快判 ×10 + 11 升级评估 ×300 + 1 复核重评估 ×300 = 3800
        assert r["llm_tokens"] == 3800
        assert r["llm_calls"] == 32

    def test_dual_mode_saves_tokens_vs_single(self):
        single = abe.run_suite(False)
        dual = abe.run_suite(True)
        assert dual["llm_tokens"] < single["llm_tokens"]


class TestCompare:
    def test_compare_kpi_structure(self):
        report = abe.compare(abe.run_suite(False), abe.run_suite(True))
        assert report["token_saved"] == 2500
        assert 0 < report["token_saved_ratio"] < 1
        assert set(report["kpi"]) == {"triage_rate_ge_60pct", "misjudge_rate_lt_5pct"}
        # mock 诉求集承接率 45%（<60%）：KPI 未达标属真实结论——
        # 标准集构成 ≠ 真实流量分布，真实达标判定以 --real 运行为准
        assert report["kpi"]["triage_rate_ge_60pct"] is False
        assert report["kpi"]["misjudge_rate_lt_5pct"] is True

    def test_main_mock_run_exits_zero(self):
        assert abe.main(["--mock"]) == 0
