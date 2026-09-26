# -*- coding: utf-8 -*-
"""截断帽：按「未命中 / 盲区」动态轮换，替代固定文档序前 N。

消费方：UX 清单 48 帽、修环清单 8 帽、旅程 brief 预算、失败指令前 20。
零 LLM——只重排，不发明事实。
"""
from __future__ import annotations

import re
from typing import Callable, Iterable, Sequence, TypeVar

_REQ_IN_LINE = re.compile(r"\bREQ-[\w.-]+\b", re.I)

T = TypeVar("T")


def _req_id_of(item) -> str:
    rid = getattr(item, "req_id", None)
    if rid:
        return str(rid)
    if isinstance(item, (tuple, list)) and item:
        return str(item[0])
    if isinstance(item, str):
        m = _REQ_IN_LINE.search(item)
        return m.group(0) if m else ""
    return ""


def _is_quote_blind(ck) -> bool:
    """无引号控件/种子、只靠行为约束或空事实——文档序截断时最易失踪。"""
    controls = getattr(ck, "control_labels", None) or []
    seeds = getattr(ck, "seed_entities", None) or []
    if controls or seeds:
        return False
    return True


def prioritize(
    items: Sequence[T],
    *,
    prefer_ids: Iterable[str] | None = None,
    limit: int | None = None,
    score_fn: Callable[[T], int] | None = None,
) -> list[T]:
    """高分优先截取，再按原文档序回排（可读性）。"""
    if not items:
        return []
    prefer = {str(x) for x in (prefer_ids or []) if x}

    def _score(it: T) -> int:
        if score_fn is not None:
            return int(score_fn(it))
        s = 0
        rid = _req_id_of(it)
        if rid and rid in prefer:
            s += 100
        if _is_quote_blind(it):
            s += 50
            cons = getattr(it, "behavior_constraints", None) or []
            if cons:
                s += 20
        return s

    ranked = sorted(enumerate(items), key=lambda iv: (-_score(iv[1]), iv[0]))
    if limit is not None and limit >= 0:
        ranked = ranked[:limit]
    picked = [it for _, it in ranked]
    order = {id(it): i for i, it in enumerate(items)}
    return sorted(picked, key=lambda it: order.get(id(it), 0))


def select_under_budget(
    items: Sequence[T],
    size_fn: Callable[[T], int],
    budget: int,
    *,
    prefer_ids: Iterable[str] | None = None,
    score_fn: Callable[[T], int] | None = None,
    head_size: int = 0,
) -> list[T]:
    """预算截断：高分优先纳入；超预算跳过该项继续看后面（不再静默 break）。"""
    if not items or budget <= 0:
        return []
    prefer = {str(x) for x in (prefer_ids or []) if x}

    def _score(it: T) -> int:
        if score_fn is not None:
            return int(score_fn(it))
        s = 0
        rid = _req_id_of(it)
        if rid and rid in prefer:
            s += 100
        if isinstance(it, tuple) and len(it) >= 2:
            # journey nodes: (nid, text) — GWT 行多的优先
            text = it[1] if isinstance(it[1], str) else ""
            if any(k in text for k in ("THEN", "GIVEN", "WHEN")):
                s += 10
        return s

    ranked = sorted(enumerate(items), key=lambda iv: (-_score(iv[1]), iv[0]))
    selected: list[T] = []
    size = max(0, int(head_size))
    for _, it in ranked:
        chunk = int(size_fn(it))
        if size + chunk > budget:
            if selected:
                continue
            # 第一条就超：硬收一条（否则 brief 全空）
            if chunk > budget:
                continue
        selected.append(it)
        size += chunk
    order = {id(it): i for i, it in enumerate(items)}
    return sorted(selected, key=lambda it: order.get(id(it), 0))


def rotate_lines(
    lines: Sequence[str],
    *,
    prefer_ids: Iterable[str] | None = None,
    limit: int = 20,
) -> list[str]:
    """失败/缺口指令行：未命中 REQ 置顶，再截前 N。"""
    return prioritize(list(lines), prefer_ids=prefer_ids, limit=limit)
