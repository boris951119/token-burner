# -*- coding: utf-8 -*-
"""编译清单 HTTP 判分器：NodeChecklist × 运行中的应用 → 逐 REQ 红绿（零 LLM）。

交付前自评分环的运行时半边（编译半边在 app/acceptance_compile.py）。
不依赖 Playwright/node——urllib 抓入口页 + 一跳可达页，逐字串比对，
秒级完成；起服/停服生命周期由调用方（selftest_gate 已持有活服）负责。

判分口径与 Playwright 编译 spec 同源、同宽严：
- 只判 home_visible 节点的 seed_entities（可见文案通道）与 control_labels
  （文本/placeholder/aria-label/value/alt/title 任一属性通道）；
- 失败串以 REQ id 开头（grade_repair_loop 的 re.match(r"(REQ-[\\d.]+)")
  直接可抓），进修复环即为定向指令。

通用性（9/22 判据）：规则不含任何题目词——任何 web 应用 × 任何
GWT 需求树都同样可判。
"""
from __future__ import annotations

import html as _html
import re
import urllib.request
from typing import Iterable

from app.acceptance_compile import NodeChecklist

_ASSET = re.compile(
    r"\.(png|jpe?g|gif|svg|webp|ico|css|js|mjs|map|woff2?|ttf|mp4|txt)$",
    re.I)
_HREF = re.compile(r"""href=["']([^"'?#]+)""", re.I)
_ATTRVAL = re.compile(
    r"""(?:placeholder|aria-label|value|alt|title)=["']([^"']+)["']""", re.I)
_SCRIPT = re.compile(r"<(script|style)[\s\S]*?</\1>", re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip()


def _fetch(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "tb-judge/1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _crawl_pages(base_url: str, max_pages: int,
                 timeout: float) -> tuple[str, str]:
    """入口 BFS 一跳：返回（全页可见文本语料, 属性值语料）。"""
    base = base_url.rstrip("/")
    queue: list[str] = ["/"]
    seen: set[str] = set()
    texts: list[str] = []
    attrs: list[str] = []
    while queue and len(seen) <= max_pages:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        try:
            body = _fetch(base + path, timeout)
        except Exception:
            continue
        attrs += _ATTRVAL.findall(body)
        texts.append(_norm(_html.unescape(
            _TAG.sub(" ", _SCRIPT.sub(" ", body)))))
        for href in _HREF.findall(body):
            if (href.startswith("/") and not href.startswith("//")
                    and not _ASSET.search(href) and href not in seen):
                queue.append(href.split("?")[0].split("#")[0])
    return "\n".join(texts), "\n".join(attrs)


def _iter_facts(checklists: Iterable[NodeChecklist]):
    for ck in checklists:
        if not ck.home_visible:
            continue
        for ent in ck.seed_entities:
            yield ck.req_id, "种子文案", ent
        for lab in ck.control_labels:
            yield ck.req_id, "控件文案", lab


def judge_checklists(checklists: list[NodeChecklist], base_url: str,
                     max_pages: int = 17,
                     timeout: float = 6.0) -> dict:
    """判分运行中的应用。返回 {passed, failed, total, failures}，
    failures 条目形如 `REQ-2.2 编译清单[控件文案] "Take a note" ...`。"""
    facts = list(_iter_facts(checklists))
    if not facts:
        return {"passed": 0, "failed": 0, "total": 0, "failures": []}
    text_blob, attr_blob = _crawl_pages(base_url, max_pages, timeout)
    text_norm = _norm(text_blob)
    attr_norm = _norm(attr_blob)
    failures: list[str] = []
    for req_id, kind, ent in facts:
        e = _norm(ent)
        if (e and (e in text_norm or e in attr_norm)):
            continue
        failures.append(
            f'{req_id} 编译清单[{kind}] "{ent}" 未出现在入口可达页面')
    total = len(facts)
    return {"passed": total - len(failures), "failed": len(failures),
            "total": total, "failures": failures}


def judge_requirements(requirements_dir, base_url: str,
                       max_pages: int = 17,
                       timeout: float = 6.0) -> dict:
    """requirements.yaml 目录 → 编译 + 判分一步到位（调用方兜异常）。"""
    from pathlib import Path

    from app.acceptance_compile import compile_checklists

    checklists = compile_checklists(
        Path(requirements_dir) / "requirements.yaml")
    out = judge_checklists(checklists, base_url, max_pages, timeout)
    out["nodes"] = len(checklists)
    return out
