"""M11-3 模式智能推荐（规格 v0.5.md：历史项目统计 → 模式/预算建议）。

确定性统计（总则 D.1：程序不做 LLM 决策，推荐仅引用历史数据、
用户可覆盖）：
- 数据源：projects_root 下各历史项目的
  sessions/requirements.md（需求文本，相似度）、
  sessions/pipeline_state.json（执行模式）、
  logs/cost_report.json（token 成本，存在 = 完成交付）、
  sessions/interruption.md（存在 = 中断未完成）；
- 相似度：需求词袋（英文词 ≥2 字符 + 中文字符 unigram）与历史需求
  的重叠占比 ≥ 0.25 视为相似（确定性阈值，无分词依赖）；
- 决策：相似项目中成功率最高者优先，平手取平均消耗更低者，
  再平手取 safe（保守缺省）；预算 = 该模式成功样本平均 token × 1.2
  （向上取整到千位）；无相似历史 → 缺省 safe + 配置档位预算。
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

_TERM = re.compile(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]")
_SIMILAR_THRESHOLD = 0.25
_BUDGET_MARGIN = 1.2


def _terms(text: str) -> set[str]:
    """词袋：英文/数字词（≥2 字符）+ 中文字符 unigram。"""
    return set(_TERM.findall(text or ""))


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _scan_history(requirement: str, projects_root: Path) -> list[dict]:
    """扫描历史项目，返回相似样本 [{mode, completed, tokens}]。"""
    terms = _terms(requirement)
    if not terms or not projects_root.is_dir():
        return []
    samples: list[dict] = []
    for sessions in projects_root.glob("*/sessions"):
        req_file = sessions / "requirements.md"
        if not req_file.is_file():
            continue
        try:
            text = req_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        common = _terms(text) & terms
        if len(common) / len(terms) < _SIMILAR_THRESHOLD:
            continue
        state = _read_json(sessions / "pipeline_state.json")
        cost = _read_json(sessions.parent / "logs" / "cost_report.json")
        completed = (
            (sessions.parent / "logs" / "cost_report.json").is_file()
            and not (sessions / "interruption.md").is_file()
        )
        samples.append({
            "mode": str(state.get("mode", "safe")),
            "completed": completed,
            "tokens": int(cost.get("total_tokens", 0) or 0),
        })
    return samples


def recommend(requirement: str, projects_root: Path | str, settings) -> dict:
    """按历史项目统计推荐执行模式与预算（确定性，无 LLM）。"""
    root = Path(projects_root)
    samples = _scan_history(requirement, root)

    if not samples:
        budget = settings.task_token_budget("safe")
        return {
            "mode": "safe",
            "budget_tokens": budget,
            "reason": "无相似历史项目，按缺省安全模式（safe）与配置预算推荐",
            "history_size": 0,
        }

    by_mode: dict[str, dict] = {}
    for s in samples:
        agg = by_mode.setdefault(s["mode"], {"total": 0, "ok": 0, "tokens": []})
        agg["total"] += 1
        if s["completed"]:
            agg["ok"] += 1
            agg["tokens"].append(s["tokens"])

    def rank(item: tuple[str, dict]) -> tuple:
        mode, agg = item
        rate = agg["ok"] / agg["total"]
        avg = (sum(agg["tokens"]) / len(agg["tokens"])) if agg["tokens"] else float("inf")
        return (rate, -avg, mode == "safe")

    mode, agg = max(by_mode.items(), key=rank)
    avg_tokens = int(sum(agg["tokens"]) / len(agg["tokens"])) if agg["tokens"] else 0
    budget = max(1000, math.ceil(avg_tokens * _BUDGET_MARGIN / 1000) * 1000)
    if not agg["tokens"]:
        budget = settings.task_token_budget(mode)

    return {
        "mode": mode,
        "budget_tokens": budget,
        "reason": (
            f"基于 {len(samples)} 个相似历史项目：{mode} 模式成功 "
            f"{agg['ok']}/{agg['total']}，平均消耗 {avg_tokens} token"
            f"（数据源：历史项目 sessions/ 与 logs/）"
        ),
        "history_size": len(samples),
    }
