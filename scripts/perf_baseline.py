# -*- coding: utf-8 -*-
"""M7-2 性能基线（标准任务集 × 固定剧本：token / 时间 / 成功率）。

标准任务集 3 档（简单直答 / 简单编程节流 / 复杂团队流程），LLM 为固定
剧本桩（确定性）——同集跨版本重跑即可对比 Token 消耗与耗时趋势；
真实质量对比须以真实任务集（用户验收清单）为准。

用法：
    python scripts/perf_baseline.py --out logs/perf_baseline.json
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.execution.executor import ExecutionResult, ExecutionStatus  # noqa: E402
from app.pipeline import Pipeline  # noqa: E402
from app.tools.file_manager import FileManager  # noqa: E402

# ---------------------------------------------------------------------------
# 标准任务集（3 档）与固定剧本
# ---------------------------------------------------------------------------

CASES: list[dict] = [
    {"name": "简单直答", "requirement": "什么是 REST API？",
     "expect_kind": "direct_answer"},
    {"name": "简单编程", "requirement": "写一个判断回文字符串的 Python 函数",
     "expect_kind": "direct_simple_coding"},
    {"name": "复杂编程", "requirement": "开发一个用户管理系统，支持注册登录与数据持久化",
     "expect_kind": "team_flow"},
]

_MODELS = ("gpt-4o", "deepseek-chat", "claude-3-5-sonnet")


def _resp(content: str):
    """与 ModelClient 返回结构同形的轻量对象（duck typing，Pipeline 需 .content）。"""
    class _R:
        pass
    r = _R()
    r.content = content
    return r


def _assessment(score: int, task_type: str = "编程"):
    return json.dumps({"task_type": task_type, "difficulty_score": score,
                       "reason": "baseline", "estimated_files": 7 if score >= 5 else 2},
                      ensure_ascii=False)


def _review():
    return json.dumps({"scores": {"feasibility": 9, "security": 9, "maintainability": 9},
                       "strengths": [], "weaknesses": [], "risks": []},
                      ensure_ascii=False)


def _split():
    return json.dumps({"modules": [
        {"name": "user", "responsibility": "用户", "dependencies": [], "priority": 1},
    ]}, ensure_ascii=False)


def _iface():
    return json.dumps({"imports": [], "exports": ["core_fn"],
                       "public_api": ["core_fn"], "dependencies": []},
                      ensure_ascii=False)


class FixedScriptLLM:
    """确定性剧本桩：按需求文本分流三档剧本；token 计量固定可复现。"""

    _team_idx = 0

    def __init__(self):
        self.total_tokens_used = 0
        self.calls = 0

    def chat(self, model, messages, json_mode=False, **kw):
        self.calls += 1
        user = messages[-1]["content"] if messages else ""
        if "REST API" in user:                      # 简单直答：1 次
            content, tokens = "REST 是表征状态转移…", 15
        elif "回文" in user:                        # 简单编程：评估 1 次 + 直出 1 次
            if json_mode:
                content, tokens = _assessment(3), 300
            else:
                content, tokens = "def is_pal(s):\n    return s == s[::-1]\n", 80
        else:                                       # 复杂编程：完整团队流程剧本
            content = self._next_team_payload()
            tokens = 300
        self.total_tokens_used += tokens
        return _resp(content)

    @classmethod
    def _next_team_payload(cls) -> str:
        """团队流程剧本按调用序依次出牌（评估→方案→评审→收敛→拆分→契约→码→测）。"""
        payloads = [
            _assessment(7),                     # 评估
            "初始方案文本",                      # 初始方案
            _review(), _review(),               # 双评审
            "最终 spec 文本",                    # 收敛
            _split(),                           # 拆分
            _iface(),                           # 接口契约
            "def core_fn():\n    return 1\n",   # 写码
            "def test_core_fn():\n    assert core_fn() == 1\n",  # 写测试
        ]
        payload = payloads[min(cls._team_idx, len(payloads) - 1)]
        cls._team_idx += 1
        return payload


class _SkippedExecutor:
    def run(self, code, tests, timeout, expected_output="", module=""):
        return ExecutionResult(status=ExecutionStatus.SKIPPED)


def _fresh_llm() -> FixedScriptLLM:
    FixedScriptLLM._team_idx = 0
    return FixedScriptLLM()


def run_case(case: dict, projects_root: Path) -> dict:
    """跑单条任务：构造独立管线（M8-1 任务级隔离），记录指标。"""
    llm = _fresh_llm()
    pipeline = Pipeline(
        llm=llm,
        settings=Settings(),
        file_manager=FileManager(projects_root=projects_root),
        executor=_SkippedExecutor(),
    )
    started = time.monotonic()
    try:
        result = pipeline.run(
            case["requirement"], confirmed_as_coding=True,
            models=list(_MODELS), mode="safe", spec_confirm="确认",
        )
        status = "succeeded" if result.kind == case["expect_kind"] else "failed"
        error = "" if status == "succeeded" else f"kind={result.kind}"
    except Exception as exc:  # noqa: BLE001 —— 基线脚本记录失败而非中断
        status, error = "failed", f"{type(exc).__name__}: {exc}"
        result = None
    return {
        "name": case["name"],
        "status": status,
        "error": error,
        "tokens": llm.total_tokens_used,
        "calls": llm.calls,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def run_baseline(out_path: Path | str | None = None) -> dict:
    """跑全部标准任务集，返回报告（可选落盘）。"""
    report = {
        "version": "v0.4-alpha",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cases": [],
    }
    with tempfile.TemporaryDirectory(prefix="tb-perf-") as tmp:
        root = Path(tmp) / "projects"
        for case in CASES:
            report["cases"].append(run_case(case, root))

    total = sum(c["tokens"] for c in report["cases"])
    ok = sum(1 for c in report["cases"] if c["status"] == "succeeded")
    report["totals"] = {
        "tokens": total,
        "success_rate": round(ok / len(CASES), 4),
        "elapsed_ms": sum(c["elapsed_ms"] for c in report["cases"]),
    }
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M7-2 性能基线")
    parser.add_argument("--out", default="logs/perf_baseline.json")
    args = parser.parse_args(argv)
    report = run_baseline(args.out)
    print("=" * 56)
    print(f"M7-2 性能基线（{report['version']}）")
    print("=" * 56)
    for c in report["cases"]:
        mark = "✅" if c["status"] == "succeeded" else "❌"
        print(f"{mark} {c['name']:<8}  token {c['tokens']:>6}  "
              f"调用 {c['calls']:>2}  {c['elapsed_ms']} ms")
    t = report["totals"]
    print(f"合计 token {t['tokens']} · 成功率 {t['success_rate']:.0%} · "
          f"{t['elapsed_ms']} ms")
    print(f"报告已写入：{args.out}")
    return 0 if t["success_rate"] == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
