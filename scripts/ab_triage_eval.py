# -*- coding: utf-8 -*-
"""M9-4 快慢双模式 A/B 评测（标准诉求集，支持 mock 离线 / 真实 LLM 两种运行）。

对比维度（v0.4.md M9-4 验收标准）：
- token 消耗：单模式（fast_triage_enabled=False）vs 双模式（True）；
- 误判率：实际路由出口 vs 期望出口（标准诉求集人工标注）；
- 端到端延迟：mock 运行无意义（无网络），真实运行时有效——框架保留。

标准诉求集（20 条，4 类 × 5）：闲聊→declined、基础问答→direct_output、
简单编程→direct_simple_coding、复杂编程→team_flow。

用法：
    python scripts/ab_triage_eval.py --mock            # 离线自检（mock LLM）
    python scripts/ab_triage_eval.py --real            # 真实 LLM（需环境变量密钥）
    python scripts/ab_triage_eval.py --mock --out out.json

输出：控制台对比表 + JSON 报告（KPI：快判承接 ≥60%、误判率 <5%）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent

from app.config import Settings  # noqa: E402
from app.orchestrator import TaskRouter, Route  # noqa: E402

# ---------------------------------------------------------------------------
# 标准诉求集（4 类 × 5，期望出口人工标注——单/双模式各自的正确行为基线：
# 单模式无 declined 出口（M9-3 前），闲聊按既有行为基线 direct_output）
# ---------------------------------------------------------------------------

CASES: list[dict] = [
    # 闲聊（单模式 direct_output 基线；双模式 declined）
    {"cat": "闲聊", "text": "你好呀，今天天气怎么样？", "expect_single": "direct_output", "expect_dual": "declined"},
    {"cat": "闲聊", "text": "你是谁？能介绍一下自己吗", "expect_single": "direct_output", "expect_dual": "declined"},
    {"cat": "闲聊", "text": "哈哈哈笑死我了", "expect_single": "direct_output", "expect_dual": "declined"},
    {"cat": "闲聊", "text": "帮我讲个笑话吧", "expect_single": "direct_output", "expect_dual": "declined"},
    {"cat": "闲聊", "text": "晚安，明天见", "expect_single": "direct_output", "expect_dual": "declined"},
    # 基础问答（两模式均 direct_output）
    {"cat": "基础问答", "text": "Python 的 list 和 tuple 有什么区别？", "expect_single": "direct_output", "expect_dual": "direct_output"},
    {"cat": "基础问答", "text": "什么是 REST API？", "expect_single": "direct_output", "expect_dual": "direct_output"},
    {"cat": "基础问答", "text": "Git 里 rebase 和 merge 的区别是什么", "expect_single": "direct_output", "expect_dual": "direct_output"},
    {"cat": "基础问答", "text": "SQL 中 LEFT JOIN 是什么意思？", "expect_single": "direct_output", "expect_dual": "direct_output"},
    {"cat": "基础问答", "text": "HTTP 404 状态码代表什么", "expect_single": "direct_output", "expect_dual": "direct_output"},
    # 简单编程（期望 direct_simple_coding，难度 ≤3）
    {"cat": "简单编程", "text": "写一个 Python 函数判断字符串是否是回文", "expect_single": "direct_simple_coding", "expect_dual": "direct_simple_coding"},
    {"cat": "简单编程", "text": "帮我写个脚本批量重命名当前目录的 txt 文件", "expect_single": "direct_simple_coding", "expect_dual": "direct_simple_coding"},
    {"cat": "简单编程", "text": "用正则表达式提取文本里的所有邮箱地址", "expect_single": "direct_simple_coding", "expect_dual": "direct_simple_coding"},
    {"cat": "简单编程", "text": "写一个计算斐波那契数列第 n 项的函数", "expect_single": "direct_simple_coding", "expect_dual": "direct_simple_coding"},
    {"cat": "简单编程", "text": "帮我把 CSV 的两列互换位置", "expect_single": "direct_simple_coding", "expect_dual": "direct_simple_coding"},
    # 复杂编程（期望 team_flow，难度 ≥5）
    {"cat": "复杂编程", "text": "开发一个双因素认证的用户管理系统，支持注册登录与权限校验", "expect_single": "team_flow", "expect_dual": "team_flow"},
    {"cat": "复杂编程", "text": "做一个电商购物车服务，含库存扣减、优惠券与订单持久化", "expect_single": "team_flow", "expect_dual": "team_flow"},
    {"cat": "复杂编程", "text": "开发一个通讯录管理命令行工具，支持增删改查、模糊搜索与 JSON 持久化", "expect_single": "team_flow", "expect_dual": "team_flow"},
    {"cat": "复杂编程", "text": "构建一个博客平台：文章管理、评论系统、标签分类与全文搜索", "expect_single": "team_flow", "expect_dual": "team_flow"},
    {"cat": "复杂编程", "text": "实现一个带断点续传的多线程文件下载器，支持校验与限速", "expect_single": "team_flow", "expect_dual": "team_flow"},
]

_EXPECTED_BY_ROUTE = {
    "declined": Route.DECLINED,
    "direct_output": Route.DIRECT_OUTPUT,
    "direct_simple_coding": Route.DIRECT_SIMPLE_CODING,
    "team_flow": Route.TEAM_FLOW,
}

# 类别 → 评估输出（mock 评估模型用；真实运行不经过此表）
_ASSESS_BY_CAT = {
    "闲聊": {"task_type": "基础", "difficulty_score": 1, "estimated_files": 1},
    "基础问答": {"task_type": "基础", "difficulty_score": 1, "estimated_files": 1},
    "简单编程": {"task_type": "编程", "difficulty_score": 3, "estimated_files": 2},
    "复杂编程": {"task_type": "编程", "difficulty_score": 7, "estimated_files": 7},
}
_TRIAGE_BY_CAT = {
    "闲聊": {"intent": "闲聊", "confidence": 0.97},
    "基础问答": {"intent": "基础", "confidence": 0.95},
    "简单编程": {"intent": "编程", "confidence": 0.96},
    "复杂编程": {"intent": "编程", "confidence": 0.98},
}
# mock token 计量（贴近真实量级：快判轻量、评估为一次主模型全量调用）
_TRIAGE_TOKENS = (5, 5)        # (input, output) 轻量模型
_ASSESS_TOKENS = (200, 100)    # 主模型 json_mode 评估


class MockTriageLLM:
    """离线评测桩：按文本类别返回快判 / 评估 JSON（token 计量贴近真实量级）。

    M12-5：支持外置诉求集（cases 参数，缺省内置标准集）。
    """

    def __init__(self, fast_model: str, cases: list[dict] | None = None):
        self.fast_model = fast_model
        self.cases = cases if cases is not None else CASES
        self.calls = 0
        self.tokens = 0
        self.call_log: list[dict] = []
        self.assessed_texts: set[str] = set()   # 真正进过 System-2 评估的诉求

    def chat(self, model: str, messages, json_mode=False, **kw):
        self.calls += 1
        user = messages[-1]["content"] if messages else ""
        if model == self.fast_model:
            tokens = sum(_TRIAGE_TOKENS)
            self.tokens += tokens
            self.call_log.append({"model": model, "tokens": tokens, "kind": "fast"})
            for cat, tri in _TRIAGE_BY_CAT.items():
                for case in self.cases:
                    if case["cat"] == cat and case["text"] in user:
                        return _resp(json.dumps(tri, ensure_ascii=False), tokens)
            return _resp(json.dumps({"intent": "无意义", "confidence": 0.9}), tokens)
        tokens = sum(_ASSESS_TOKENS)
        self.tokens += tokens
        self.call_log.append({"model": model, "tokens": tokens, "kind": "assess"})
        for cat, assess in _ASSESS_BY_CAT.items():
            for case in self.cases:
                if case["cat"] == cat and case["text"] in user:
                    self.assessed_texts.add(case["text"])
                    payload = {**assess, "reason": f"mock-{cat}"}
                    return _resp(json.dumps(payload, ensure_ascii=False), tokens)
        return _resp(json.dumps(
            {"task_type": "编程", "difficulty_score": 0, "reason": "mock-fallback"},
            ensure_ascii=False,
        ), tokens)


def _resp(content: str, tokens: int):
    """与 ModelClient 返回结构同形的轻量对象（duck typing）。"""
    class _R:
        pass
    r = _R()
    r.content = content
    r.input_tokens, r.output_tokens = tokens // 2, tokens - tokens // 2
    return r


def _route_case(router: TaskRouter, case: dict, dual: bool) -> dict:
    """跑单条诉求：路由 + 计时 + 误判判定（按模式各自的期望基线）。"""
    started = time.monotonic()
    result = router.route(case["text"])
    elapsed_ms = int((time.monotonic() - started) * 1000)
    actual = result.route.value
    expect = case["expect_dual"] if dual else case["expect_single"]
    return {
        "cat": case["cat"],
        "text": case["text"],
        "expect": expect,
        "actual": actual,
        "misclassified": actual != expect,
        "elapsed_ms": elapsed_ms,
    }


def _llm_tokens(llm) -> int:
    """计量兼容：mock 用 .tokens，真实 ModelClient 用 .total_tokens_used。"""
    for attr in ("tokens", "total_tokens_used"):
        v = getattr(llm, attr, None)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def _triage_model(settings: Settings) -> str:
    """快判模型 = 预设中的最轻量档（轻量档末位；未配轻量档取预设列表末位）。

    M9-4 口径「fast_triage_model = 预设列表中的轻量档」；真实评测在
    生产模型档位上动态选定，避免 config.json 未显式配置时校验失败。
    """
    if settings.model_tier_light:
        return settings.model_tier_light[-1]
    return settings.models[-1]


def run_suite(
    fast_triage_enabled: bool, llm=None, cases: list[dict] | None = None,
    settings: Settings | None = None,
) -> dict:
    """跑一个模式的全部用例，返回汇总（token / 误判 / 承接 / 延迟）。

    M12-5：cases 支持外置诉求集（缺省内置标准集）。
    M13-2 真实评测：settings 传入 load_settings() 结果（生产模型档位），
    快慢两跑各自覆盖 fast_triage_enabled（其余配置与生产完全一致）。
    """
    cases = cases if cases is not None else CASES
    if settings is None:
        settings = Settings(fast_triage_enabled=fast_triage_enabled)
    else:
        settings = replace(
            settings,
            fast_triage_enabled=fast_triage_enabled,
            fast_triage_model=_triage_model(settings),
        )
    if llm is None:
        llm = MockTriageLLM(settings.fast_triage_model, cases)
    router = TaskRouter(llm, settings.models[0], settings)

    per_case = [_route_case(router, c, fast_triage_enabled) for c in cases]

    misclassified = sum(1 for c in per_case if c["misclassified"])
    # 快判承接数：未进 System-2 评估的条目（精确口径——升级后出口恰好
    # 相同的条目不计入；真实 LLM 无此信息，回落出口估计）
    if isinstance(llm, MockTriageLLM):
        triaged = sum(1 for c in per_case if c["text"] not in llm.assessed_texts)
    else:
        triaged = sum(
            1 for c in per_case
            if fast_triage_enabled
            and c["actual"] in ("declined", "direct_output")
            and not c["misclassified"]
        )
    return {
        "mode": "dual" if fast_triage_enabled else "single",
        "cases_total": len(cases),
        "llm_tokens": _llm_tokens(llm),
        # 计量兼容：mock 用 .calls 计数；真实 ModelClient 读 call_log 长度
        "llm_calls": getattr(llm, "calls", None)
        if getattr(llm, "calls", None) is not None
        else len(getattr(llm, "call_log", [])),
        "misclassified": misclassified,
        "triaged_by_fast_path": triaged,
        "triage_rate": round(triaged / len(cases), 4),
        "misjudge_rate": round(misclassified / len(cases), 4),
        "avg_elapsed_ms": round(
            sum(c["elapsed_ms"] for c in per_case) / len(cases), 1,
        ),
        "per_case": per_case,
    }


def compare(single: dict, dual: dict) -> dict:
    """A/B 对比汇总 + KPI 达标判定（快判承接 ≥60%、误判率 <5%）。"""
    return {
        "single": {k: single[k] for k in (
            "llm_tokens", "llm_calls", "misclassified", "misjudge_rate",
            "avg_elapsed_ms")},
        "dual": {k: dual[k] for k in (
            "llm_tokens", "llm_calls", "misclassified", "triage_rate",
            "misjudge_rate", "avg_elapsed_ms")},
        "token_saved": single["llm_tokens"] - dual["llm_tokens"],
        "token_saved_ratio": round(
            1 - dual["llm_tokens"] / max(1, single["llm_tokens"]), 4),
        "kpi": {
            "triage_rate_ge_60pct": dual["triage_rate"] >= 0.6,
            "misjudge_rate_lt_5pct": dual["misjudge_rate"] < 0.05,
        },
    }


def load_cases(path: str | None) -> list[dict]:
    """M12-5：加载外置诉求集（JSON 数组）；None 返回内置标准集。

    fail-fast 校验（总则 D.1 确定性边界）：数组元素必须包含
    cat / text / expect_single / expect_dual，且期望出口合法。
    """
    if path is None:
        return CASES
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"诉求集 {path} 必须为非空 JSON 数组")
    for i, c in enumerate(cases):
        for field in ("cat", "text", "expect_single", "expect_dual"):
            if field not in c:
                raise ValueError(f"诉求集第 {i} 条缺少字段 {field}")
        for field in ("expect_single", "expect_dual"):
            if c[field] not in _EXPECTED_BY_ROUTE:
                raise ValueError(
                    f"诉求集第 {i} 条 {field} 非法: {c[field]}（合法值："
                    f"{sorted(_EXPECTED_BY_ROUTE)}）"
                )
    return cases


def _archive_path(out: str) -> Path:
    """M12-5：报告归档路径——--out 优先；缺省 logs/ab_reports/ 时间戳归档。"""
    if out:
        return Path(out)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return ROOT / "logs" / "ab_reports" / f"ab_{stamp}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M9-4 快慢双模式 A/B 评测")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mock", action="store_true", help="离线 mock LLM 自检")
    group.add_argument("--real", action="store_true", help="真实 LLM（需密钥）")
    parser.add_argument("--cases", default="", help="外置诉求集 JSON 路径（缺省内置标准集）")
    parser.add_argument("--out", default="", help="报告 JSON 输出路径（缺省归档 logs/ab_reports/）")
    args = parser.parse_args(argv)

    cases = load_cases(args.cases or None)

    if args.real:
        from app.utils.model_client import ModelClient  # 真实链路（需密钥）
        from app.config import load_settings
        # M13-2：真实评测使用生产配置（config.json 覆盖 → glm 三档），
        # 而非裸 Settings 的海外默认模型；密钥经环境变量注入。
        settings = load_settings()
        llm = ModelClient(settings)
    else:
        llm = None  # run_suite 内部构造 mock
        settings = None

    single = run_suite(False, llm, cases, settings)
    dual = run_suite(True, llm, cases, settings)
    report = {
        "cases": len(cases),
        "cases_file": args.cases or "内置标准集",
        **compare(single, dual),
        "per_case": {"single": single["per_case"], "dual": dual["per_case"]},
    }

    print("=" * 62)
    print(f"M9-4 快慢双模式 A/B 评测（诉求集 {len(cases)} 条）")
    print("=" * 62)
    print(f"单模式 token：{single['llm_tokens']:>8}  调用 {single['llm_calls']:>3}  "
          f"误判 {single['misclassified']}")
    print(f"双模式 token：{dual['llm_tokens']:>8}  调用 {dual['llm_calls']:>3}  "
          f"误判 {dual['misclassified']}  快判承接 {dual['triaged_by_fast_path']}/{len(cases)}")
    print(f"节省：{report['token_saved']} token（{report['token_saved_ratio']:.1%}）")
    kpi = report["kpi"]
    print(f"KPI  快判承接 ≥60%：{'✅' if kpi['triage_rate_ge_60pct'] else '❌'}"
          f"   误判率 <5%：{'✅' if kpi['misjudge_rate_lt_5pct'] else '❌'}")

    archive = _archive_path(args.out)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已归档：{archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
