# -*- coding: utf-8 -*-
"""编译清单 HTTP 判分器：NodeChecklist × 运行中的应用 → 逐 REQ 红绿（零 LLM）。

交付前自评分环的运行时半边（编译半边在 app/acceptance_compile.py）。
不依赖 Playwright/node——urllib 抓入口页 + 一跳可达页，逐字串比对，
秒级完成；起服/停服生命周期由调用方（selftest_gate 已持有活服）负责。

判分口径与 Playwright 编译 spec 同源、同宽严：
- 只判 home_visible 节点的 seed_entities（可见文案通道）与 control_labels
  （文本/placeholder/aria-label/value/alt/title 任一属性通道）；
- 两侧语料都只收**渲染得出来**的内容：display:none / hidden / template 等
  不可见子树先剔除（spec 用 isVisible()，判分器不能比它宽，否则隐藏 div
  塞满需求文案即可本地全绿、官方 0 分）；
- 失败串以 REQ id 开头（grade_repair_loop 的 re.match(r"(REQ-[\\d.]+)")
  直接可抓），进修复环即为定向指令；
- 语料近乎为空时不逐条判红（否则一个根因摊成 N 条幻影失败）：入口页含
  JS 挂载点 → skipped 射程外（客户端渲染，静态判分看不见），否则记一条
  「首页无可见文本」根因失败；
- 第三条通道兜客户端渲染（9/23 三组对照取证）：文案虽不在可见文本里、
  但确实出现在页内脚本正文 = 浏览器渲染得出来 → 该条记射程外（不判红不
  判绿，报告里点名条数）。只在页内源码里也不存在才判红，故 keep#2 那类
  「换语言/塞隐藏位」的造假照旧全红。
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
# ---- 不可见内容剔除（9/23 keep 交付实证）--------------------------------
# 模型学会把需求的逐字文案塞进 <div style="display:none">：源码里在、页面上
# 没有。官方评测按可见性断言（Playwright toBeVisible），隐藏文案一律判红；
# 判分器若把隐藏文本也当语料，就会对同一份交付给出「本地全绿 / 官方 0 分」
# 的反向结论，等于把生成端往这个方向惯。剔除口径（正则 HTML 处理，宁窄不宽）：
# display:none / visibility:hidden 内联样式子树、hidden / aria-hidden 属性
# 子树、Tailwind 的 hidden/invisible 类、<input type=hidden>、<template> /
# <noscript>、注释与 CDATA。sr-only 不剔（1px 裁剪，Playwright 仍算可见）。
_COMMENT = re.compile(r"<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>")
_TAG_ANY = re.compile(r"<(/?)([a-zA-Z][\w:-]*)([^>]*)>|<[^>]*>", re.I)
_STYLE_HIDE = re.compile(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", re.I)
_ATTR_PAIR = re.compile(r"""([\w:-]+)\s*=\s*["']([^"']*)["']""")
_HIDE_CLASS = {"hidden", "invisible"}
_HIDE_TAG = {"template", "noscript"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "param", "source", "track", "wbr"}


def _attrs(pairs_src: str) -> dict:
    return {k.lower(): v for k, v in _ATTR_PAIR.findall(pairs_src or "")}


def _is_hidden(name: str, pairs: dict, raw: str = "") -> bool:
    if name in _HIDE_TAG:
        return True
    if _STYLE_HIDE.search(pairs.get("style", "")):
        return True
    for key in ("hidden", "aria-hidden"):
        val = pairs.get(key)
        if val is not None and val.strip().lower() in ("", "true", key):
            return True
        if val is None and re.search(
                rf"(?<![\w:-]){key}(?![\w-])(?!\s*=)", raw or "", re.I):
            return True                        # 裸布尔属性 <div hidden>
    if name == "input" and pairs.get("type", "").strip().lower() == "hidden":
        return True
    cls = pairs.get("class", "").lower().replace("|", " ").split()
    return bool(set(cls) & _HIDE_CLASS)


def _strip_invisible(src: str) -> str:
    """只剔「渲染不出像素」的元素子树，其余原文保留（文本/属性两通道共用）。"""
    src = _COMMENT.sub(" ", src)
    out: list[str] = []
    stack: list[bool] = []
    hide = 0
    pos = 0
    for m in _TAG_ANY.finditer(src):
        if hide == 0:
            out.append(src[pos:m.start()])
        pos = m.end()
        name = (m.group(2) or "").lower()
        if not name:                             # doctype 等
            continue
        if m.group(1) == "/":                    # 闭标签
            if stack and stack.pop():
                hide = max(0, hide - 1)
            continue
        hidden = _is_hidden(name, _attrs(m.group(3)), m.group(3))
        if name in _VOID:                        # 自闭合：无子树，只看自身
            if hide == 0:
                out.append(" " if hidden else m.group(0))
            continue
        stack.append(hidden)
        if hidden:
            hide += 1
        else:
            out.append(m.group(0))
    if hide == 0:
        out.append(src[pos:])
    return " ".join(out)
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
# 逐字事实的第三条通道：页面内联脚本正文。9/23 三组对照实测（服务端渲染 /
# 内联脚本注水 / fetch 拉 JSON 的客户端渲染应用）——_JS_MOUNT 那条整体降级
# 只在语料 <40 字符时触发，而客户端渲染应用只要有一条静态导航栏就能越过该
# 阈值（实测 80 字符），于是需求文案**全部**判红：3/3 幻影、0 真信号。改按
# 单条事实取证：文案确实出现在脚本正文里 = 浏览器渲染得出来、静态判分射程
# 外（不判红也不判绿）；文案在页面源码里根本不存在仍然判红（keep#2 那类
# 「换语言/塞隐藏位」的造假恰好属于这一类，不受本次放宽影响）。
_SCRIPT_BODY = re.compile(r"<script[^>]*>([\s\S]*?)</script>", re.I)


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip()


def _fetch(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "tb-judge/1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _crawl_pages(base_url: str, max_pages: int,
                 timeout: float) -> tuple[str, str, bool, str]:
    """入口 BFS 一跳：返回（全页可见文本语料, 属性值语料, 入口页是否
    JS 挂载壳, 页内脚本正文语料）。"""
    base = base_url.rstrip("/")
    queue: list[str] = ["/"]
    seen: set[str] = set()
    texts: list[str] = []
    attrs: list[str] = []
    scripts: list[str] = []
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
        # 文本与属性两通道都只认「渲染得出来」的内容：编译 Playwright spec
        # 用 isVisible() 断言，本判分器必须同口径，否则隐藏 div 塞文案即可
        # 骗过平台唯一那道闸。
        rendered = _strip_invisible(_SCRIPT.sub(" ", body))
        attrs += _ATTRVAL.findall(rendered)
        texts.append(_norm(_html.unescape(_TAG.sub(" ", rendered))))
        scripts += [_html.unescape(s) for s in _SCRIPT_BODY.findall(body)]
        for href in _HREF.findall(body):
            if (href.startswith("/") and not href.startswith("//")
                    and not _ASSET.search(href) and href not in seen):
                queue.append(href.split("?")[0].split("#")[0])
    return ("\n".join(texts), "\n".join(attrs), shell, "\n".join(scripts))


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
    text_blob, attr_blob, shell, script_blob = _crawl_pages(
        base_url, max_pages, timeout)
    text_norm = _norm(text_blob)
    attr_norm = _norm(attr_blob)
    script_norm = _norm(script_blob)
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
    client_side: list[str] = []
    for req_id, kind, ent in facts:
        e = _norm(ent)
        if (e and (e in text_norm or e in attr_norm)):
            continue
        if e and e in script_norm:
            # 文案只存在于页内脚本正文：客户端渲染，浏览器出得来像素，
            # 静态判分出不来——射程外，不判红也不判绿（判红即幻影失败，
            # 修复环会围着一条修不好的指令烧掉整轮）。
            client_side.append(f'{req_id} 编译清单[{kind}] "{ent}"')
            continue
        failures.append(
            f'{req_id} 编译清单[{kind}] "{ent}" 未出现在入口可达页面')
    total = len(facts)
    out = {"passed": total - len(failures) - len(client_side),
           "failed": len(failures), "total": total, "failures": failures,
           "client_side": len(client_side)}
    if client_side:
        out["note"] = (
            f"{len(client_side)} 条逐字事实仅见于页内脚本正文"
            f"（{'; '.join(client_side[:3])}…）：客户端渲染，静态判分射程外，"
            f"未判红也未判绿")
    return out


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
