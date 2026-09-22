# -*- coding: utf-8 -*-
"""编译清单 HTTP 判分器：NodeChecklist × 运行中的应用 → 逐 REQ 红绿（零 LLM）。

交付前自评分环的运行时半边（编译半边在 app/acceptance_compile.py）。
不依赖 Playwright/node——urllib 抓入口页 + 一跳可达页，逐字串比对，
秒级完成；起服/停服生命周期由调用方（selftest_gate 已持有活服）负责。

判分口径与 Playwright 编译 spec 同源、同宽严：
- 只判 home_visible 节点的 seed_entities（可见文案通道）与 control_labels
  （文本/placeholder/aria-label/value/alt/title 任一属性通道）；
- 失败串以 REQ id 开头（grade_repair_loop 的 re.match(r"(REQ-[\\d.]+)")
  直接可抓），进修复环即为定向指令；
- 语料近乎为空时不逐条判红（否则一个根因摊成 N 条幻影失败）：入口页含
  JS 挂载点 → skipped 射程外（客户端渲染，静态判分看不见），否则记一条
  「首页无可见文本」根因失败。
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
# 判分语料下限（字符，文本与属性两侧都低于才算空）：低于此值说明入口
# 可达页根本没有渲染出内容，此时逐条事实判红只会把一个根因摊成 N 条修不
# 好的幻影失败。取值刻意保守——真应用首页（导航 + 种子名 + 表单标签）
# 稳定数百字符，只有空壳/5xx/拒连才会掉到几十以下。
_THIN_CORPUS = 40
# 客户端渲染外壳的标志：文案由 JS 注水进挂载点，静态抓取的语料必然为空
# ——那是判分器射程外，不是应用的错（官方评测跑真浏览器，看得见）。
_JS_MOUNT = re.compile(
    r"""<(?:div|main|body|noscript)[^>]*\bid=["']"""
    r"""(?:app|root|next|nuxt|app-root|react-root|vue-root)["']""", re.I)


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip()


def _fetch(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "tb-judge/1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _crawl_pages(base_url: str, max_pages: int,
                 timeout: float) -> tuple[str, str, bool]:
    """入口 BFS 一跳：返回（全页可见文本语料, 属性值语料, 入口页是否
    JS 挂载壳）。"""
    base = base_url.rstrip("/")
    queue: list[str] = ["/"]
    seen: set[str] = set()
    texts: list[str] = []
    attrs: list[str] = []
    shell = False
    while queue and len(seen) <= max_pages:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        try:
            body = _fetch(base + path, timeout)
        except Exception:
            continue
        if path == "/":
            shell = bool(_JS_MOUNT.search(body))
        attrs += _ATTRVAL.findall(body)
        texts.append(_norm(_html.unescape(
            _TAG.sub(" ", _SCRIPT.sub(" ", body)))))
        for href in _HREF.findall(body):
            if (href.startswith("/") and not href.startswith("//")
                    and not _ASSET.search(href) and href not in seen):
                queue.append(href.split("?")[0].split("#")[0])
    return "\n".join(texts), "\n".join(attrs), shell


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
    failures 条目形如 `REQ-2.2 编译清单[控件文案] "某按钮名" ...`。"""
    facts = list(_iter_facts(checklists))
    if not facts:
        return {"passed": 0, "failed": 0, "total": 0, "failures": []}
    text_blob, attr_blob, shell = _crawl_pages(base_url, max_pages, timeout)
    text_norm = _norm(text_blob)
    attr_norm = _norm(attr_blob)
    if len(text_norm) < _THIN_CORPUS and len(attr_norm) < _THIN_CORPUS:
        # 官方交付容器无 node → Playwright 段 SKIP，本判分器是唯一质量闸。
        # 语料近乎为空时"事实全部缺席"是判分器失明的假象，不是 N 个缺陷：
        # 客户端渲染外壳记射程外跳过（幻影失败会让修复环围着修不好的东西
        # 烧掉整轮），静态空壳/入口 5xx 记一条根因（首页落空是真死因）。
        if shell:
            return {"passed": 0, "failed": 0, "total": len(facts),
                    "failures": [],
                    "skipped": f"入口页为 JS 挂载壳（可见文本 {len(text_norm)}"
                               " 字符）：文案由客户端渲染，静态判分射程外"}
        return {"passed": 0, "failed": 1, "total": 1,
                "failures": [
                    f"入口可达页面几乎无可见文本（{len(text_norm)} 字符，"
                    f"判分语料为空）：首页 / 必须 200 且渲染真实内容与可点"
                    f"导航链接——空白页/纯文字壳/入口 5xx 会让全部用例在导航"
                    f"一步连环落空（本轮 {len(facts)} 条逐字事实未判，"
                    f"先修首页）"],
                "note": "判分语料为空：逐条事实判红已归并为一条根因"}
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
