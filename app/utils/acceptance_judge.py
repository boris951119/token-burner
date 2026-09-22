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
- 第四条通道「可点击控件」（9/23 退役产物快照取证）：需求写「点击 X」时，
  X 光在页面上可见还不算，必须落在可点控件里（<button>/<a>/显式交互 role/
  勾选框的 label/button 类 input 的 value）——评测点控件走 getByRole
  ('button'|'link', {name})，这类断言没有文本兜底；认不出控件语义的一律
  不判红（宁漏不幻），同因超出 8 条时归并成一条计数；
- 同通道的接线证据（9/23 判分红叶取证）：按钮类控件还须拿得出「点了会有
  反应」的静态证据（**该控件所在页**带 <script> / 落在 <form> 内 / 自带处理
  器属性），三者皆无即按占位按钮判红——那份交付首页整站零脚本、把十条需求
  文案铺成 <button type="button">，本地全绿而官方 29/31 例卡在点击超时。
  脚本证据按页算（9/23 复盘）：跨页合并会让子页一段无关脚本替入口页的哑
  按钮担保，而评测是在找到控件的那一页点下去——同一条文案只要在任一页真
  接线即判绿，故不会因此多判红。占位按钮与「文案当控件」两种红的修法不同
  （前者补抄文案只会再造一个诱饵），故分开点名。summary/option/勾选框不受
  此约束：它们的反应是浏览器原生行为。
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
from dataclasses import dataclass, field
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
# 「整墙缺席」归并（9/23 run6 Linux 真形取证）：那份交付后端 0 个
# render_template、29 条路由全是 /api/*，首页只是个 784 字节的静态壳——
# 判分器据此对 70 条事实判红 69 条。每条都"真"，但它们同因（页面路由不
# 存在），而修复环只吃前 20 条：模型拿到 20 个互不相干的文案串，最经济的
# 满足方式就是把它们抄进首页某处——keep#2 那次 display:none 造假正是这条
# 路径走出来的。整墙缺席时改判一条结构性根因，指令才指向能修的地方。
# 门槛按比例+绝对量双重收：只漏几条标签的正常应用仍走逐条精确指令。
_WALL_RATIO = 0.7
_WALL_MIN = 10
# 可点击通道的逐条指令上限：同类缺陷一条就够说清修法，超出部分归并成
# 一条计数（修复环只吃前 20 条指令，不能让同一形状刷屏）。
_CLICK_FAIL_MAX = 8


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip()


def _fetch(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "tb-judge/1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _is_html(src: str) -> bool:
    head = src[:2048].lstrip().lower()
    return head.startswith(("<!doctype html", "<html")) or "<body" in head


# ---- 可点击控件通道（9/23 取证）----------------------------------------
# 「文案在页面上」并不等于「控件存在」：评测点控件走的是
# getByRole('button'/'link'/'menuitem', {name})，这类断言没有文本兜底，
# 把需求的点击对象渲染成正文文字/标题，该节点全部用例照样落空。
# 官方 helpers 里 clickNamed 一路兜到 getByText，但同文件的 openComposer
# 是硬 getByRole('button') —— 兜底只属于个别 helper，不属于判分口径。
_ATTR_LOOSE = re.compile(
    r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'<>]+))""")


def _attrs_loose(pairs_src: str) -> dict:
    """控件属性宽松版：也收无引号值（value=Go / type=checkbox 均为合法
    HTML，生成端偶有出现）。隐藏判定用的 _ATTR_PAIR 保持原口径不动。"""
    out: dict[str, str] = {}
    for k, a, b, c in _ATTR_LOOSE.findall(pairs_src or ""):
        out[k.lower()] = a or b or c
    return out


_CTRL_TAGS = {"button", "a", "summary", "option", "legend"}
_CTRL_ROLES = {"button", "link", "menuitem", "menuitemradio", "menuitemcheckbox",
               "tab", "option", "checkbox", "radio", "combobox", "switch"}
_BTN_INPUT = {"submit", "button", "image", "reset"}
_CHOICE_INPUT = {"checkbox", "radio"}
# 开标签后取多长当元素正文：模板里闭标签常缺，不设上限会吞掉整页
_WIN = 600
# ---- 接线证据（9/23 keep 判分红叶现场取证）------------------------------
# 那份交付首页 2724 字节、整站零 <script>，把需求的十条动作文案铺成一片
# <button type="button">（连 "Click Archived" 这种题面句子片段都被做成按钮
# 名）。可点通道按标签名把它们全判绿，官方评测 29/31 例却卡死在 click/hover
# 超时——点了不会动的按钮，在评测眼里与正文文字同一价值。故「顶着按钮标签」
# 不等于「是可点控件」：按钮必须拿得出接线证据。证据三条宽口径（宁漏不幻，
# 幻红会让修复环围着一条修不好的指令烧掉整轮）：① 页面带任何 <script>
# （内联或 src，监听 statically 无从证伪）；② 落在 <form> 内（button 的
# 隐式 type=submit，服务端渲染表单是最常见正常形）；③ 自带处理器属性。
# summary/option/勾选框不在此列——它们的反应是浏览器原生行为，本就不需接线。
_JS_TAG = re.compile(r"<script[\s>]", re.I)
_HANDLER_ATTR = re.compile(
    r"^(?:on[\w:-]+|x-on:[\w:-]+|v-on:[\w:-]+|@[\w:-]+|ng-[\w:-]*click"
    r"|ng-submit|wire:[\w:-]+|hx-(?:get|post|put|patch|delete|target|swap)"
    r"|formaction|formmethod)$", re.I)
# 点击必须「有下文」的角色：没有接线证据时，评测点下去就是 60 秒超时
_NEEDS_WIRING_ROLES = {"button", "menuitem", "menuitemradio",
                       "menuitemcheckbox", "tab", "switch"}


def _wired(pairs: dict, has_js: bool, in_form: bool) -> bool:
    """按钮类控件能否对点击作出反应（静态可判的那部分）。"""
    if has_js or in_form or pairs.get("form"):
        return True
    return any(_HANDLER_ATTR.match(k) for k in pairs)


def _interactive_corpus(html, require_wiring: bool = True) -> str:
    """页面上所有可点/可选控件的正文文字与可访问名，归一成待匹配语料。

    html 可以是多页原文的序列：接线证据逐页各算一次再取并集——同一条文案只
    要有一页真接了线即判绿（不会因此多判红），但别的页面那段脚本替不了这一
    页的哑按钮（评测就在找到控件的那一页点下去）。

    只认确定的语义（button/a/summary/option/legend、显式交互 role、
    button 类 input 的 value/aria-label、勾选类控件的 label），认不出的
    一律不算控件：宁可漏判这条红，也不造幻影红——幻红会让修复环围着一
    条修不好的指令烧掉整轮。label 单独处理，因为 <label>文字</label>
    只有包住（或 for 指向）勾选框时才是可点通道，纯装饰性 label 不是。
    按钮类还要过 _wired 的接线证据：无脚本页面上的裸 <button> 点了不会
    有任何反应，算它作控件就是给判分红叶开假绿通道。
    require_wiring=False 退回「只认标签名」的旧口径，只用来分两种红：
    顶过按钮标签但没过接线证据 = 占位按钮（抄文案修不好，必须点名真接线），
    压根不是按钮 = 文案当控件（照旧口径）。
    """
    if isinstance(html, (list, tuple)):
        return _norm(" ".join(
            c for c in (_interactive_corpus(p, require_wiring) for p in html)
            if c))
    # require_wiring=False 时把整页当「带脚本」：_wired 退化成只认标签名，
    # 用来把「占位按钮」与「文案当控件」两种红分开（修法不同，指令不能混）。
    has_js = bool(_JS_TAG.search(html)) or not require_wiring
    src = _SCRIPT.sub(" ", html)
    tags: list[tuple[str, dict, str, str, bool]] = []
    form_depth = 0
    for m in _TAG_ANY.finditer(src):
        if m.group(1):
            if (m.group(2) or "").lower() == "form" and form_depth:
                form_depth -= 1
            continue                          # 其余闭标签
        tag = (m.group(2) or "").lower()
        if tag == "form":
            form_depth += 1
        raw_inner = src[m.end():m.end() + _WIN]
        stop = re.search(rf"</{re.escape(tag)}[\s>]", raw_inner, re.I)
        if stop:
            raw_inner = raw_inner[:stop.start()]
        tags.append((tag, _attrs_loose(m.group(3)),
                     _norm(_TAG.sub(" ", raw_inner)), raw_inner,
                     form_depth > 0))
    choice_ids = {p.get("id", "").strip() for t, p, _, _, _ in tags
                  if t == "input"
                  and p.get("type", "").strip().lower() in _CHOICE_INPUT}
    out: list[str] = []
    for tag, pairs, inner, raw_inner, in_form in tags:
        role = pairs.get("role", "").strip().lower()
        if tag == "input":
            itype = pairs.get("type", "").strip().lower()
            if itype in _BTN_INPUT and not _wired(pairs, has_js, in_form):
                continue                     # 表单外的 input[type=submit] 同样点不动
            if itype in _BTN_INPUT or itype in _CHOICE_INPUT:
                out += [pairs.get("value", ""), pairs.get("aria-label", ""),
                        pairs.get("title", "")]
            continue
        if tag == "label":
            for_id = pairs.get("for", "").strip()
            wrapped = re.search(
                r"<input\b[^>]*type\s*=\s*['\"]?(checkbox|radio)",
                raw_inner, re.I)
            if (for_id and for_id in choice_ids) or wrapped:
                out.append(inner)              # 该 label 即勾选框的可点名
            continue
        if tag in _CTRL_TAGS or role in _CTRL_ROLES:
            is_btn = (tag == "button" or role in _NEEDS_WIRING_ROLES)
            if not is_btn and tag == "a" and not pairs.get("href"):
                is_btn = True      # 没有 href 的 <a> 不是 link，点了不导航
            if is_btn and not _wired(pairs, has_js, in_form):
                continue
            out += [inner, pairs.get("aria-label", ""), pairs.get("title", "")]
    return _norm(" ".join(c for c in out if c))



@dataclass
class _Crawl:
    """一次入口 BFS 的全部观察量（判分口径与报告都从这里取）。"""
    text: str = ""
    attrs: str = ""
    scripts: str = ""
    # 原始源码通道（隐藏块与注释都在里面）。只用来分两种「没判绿」：
    # 文案在源码里却不可见 = 造假，逐条判红（keep#2）；源码里根本没有
    # = 结构缺失，可归并成一条根因（run6）。
    raw: str = ""
    # 逐页原文（与 raw 同一份内容，只是不合并）：接线证据按页算用
    pages: list[str] = field(default_factory=list)
    shell: bool = False                      # 入口页是否 JS 挂载壳
    html_pages: int = 0                      # 真正返回 HTML 文档的页面数
    links: int = 0                           # 站内链接总数（去重后）
    dead_links: list[str] = field(default_factory=list)  # 打不开/不是页面


def _crawl_pages(base_url: str, max_pages: int,
                 timeout: float) -> _Crawl:
    """入口 BFS 一跳：抓首页与首页链出的站内页面，累计三条语料通道，
    并把「导航是否真的通向页面」作为独立观测量带出来。"""
    base = base_url.rstrip("/")
    c = _Crawl()
    queue: list[str] = ["/"]
    seen: set[str] = set()
    texts: list[str] = []
    attrs: list[str] = []
    scripts: list[str] = []
    raws: list[str] = []
    while queue and len(seen) <= max_pages:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        try:
            body = _fetch(base + path, timeout)
        except Exception:
            if path != "/":
                c.dead_links.append(path)
            continue
        if not _is_html(body):
            # 链过去是 JSON/下载件：对按可见文案断言的评测等于没有这个页面
            if path != "/":
                c.dead_links.append(path)
            continue
        c.html_pages += 1
        raws.append(_html.unescape(body))
        if path == "/":
            c.shell = bool(_JS_MOUNT.search(body))
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
                c.links += 1
                queue.append(href.split("?")[0].split("#")[0])
    c.text = "\n".join(texts)
    c.attrs = "\n".join(attrs)
    c.scripts = "\n".join(scripts)
    c.raw = "\n".join(raws)
    c.pages = raws
    return c


def _iter_facts(checklists: Iterable[NodeChecklist]):
    for ck in checklists:
        if not ck.home_visible:
            continue
        for ent in ck.seed_entities:
            yield ck.req_id, "种子文案", ent
        for lab in ck.control_labels:
            yield ck.req_id, "控件文案", lab


def _iter_click_facts(checklists: Iterable[NodeChecklist]):
    """需求以「点击 X」形式承诺、因而必须是可点控件的那部分文案。"""
    for ck in checklists:
        if not ck.home_visible:
            continue
        for lab in ck.click_controls:
            yield ck.req_id, lab


def judge_checklists(checklists: list[NodeChecklist], base_url: str,
                     max_pages: int = 17,
                     timeout: float = 6.0) -> dict:
    """判分运行中的应用。返回 {passed, failed, total, failures}，
    failures 条目形如 `REQ-2.2 编译清单[控件文案] "某按钮名" ...`。"""
    facts = list(_iter_facts(checklists))
    if not facts:
        return {"passed": 0, "failed": 0, "total": 0, "failures": []}
    crawl = _crawl_pages(base_url, max_pages, timeout)
    text_norm = _norm(crawl.text)
    attr_norm = _norm(crawl.attrs)
    script_norm = _norm(crawl.scripts)
    if len(text_norm) < _THIN_CORPUS and len(attr_norm) < _THIN_CORPUS:
        # 官方交付容器无 node → Playwright 段 SKIP，本判分器是唯一质量闸。
        # 语料近乎为空时"事实全部缺席"是判分器失明的假象，不是 N 个缺陷：
        # 客户端渲染外壳记射程外跳过（幻影失败会让修复环围着修不好的东西
        # 烧掉整轮），静态空壳/入口 5xx 记一条根因（首页落空是真死因）。
        if crawl.shell:
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
    found = 0                                     # 真实命中数（不得由减法倒推）
    absent: list[tuple[str, str, str]] = []   # 源码里查无此文 = 结构缺失候选
    raw_norm = _norm(crawl.raw)
    for req_id, kind, ent in facts:
        e = _norm(ent)
        if not e:
            continue
        if e in text_norm or e in attr_norm:
            found += 1
            continue
        if e in script_norm:
            # 文案只存在于页内脚本正文：客户端渲染，浏览器出得来像素，
            # 静态判分出不来——射程外，不判红也不判绿（判红即幻影失败，
            # 修复环会围着一条修不好的指令烧掉整轮）。
            client_side.append(f'{req_id} 编译清单[{kind}] "{ent}"')
        elif e in raw_norm:
            # 源码里有、页面上没有 = 塞在隐藏块/注释里（keep#2 的造假口径）。
            # 这类绝不进归并：把它折成一条结构性根因等于给造假开脱。
            failures.append(
                f'{req_id} 编译清单[{kind}] "{ent}" 只存在于页面的不可见位置'
                f'（隐藏元素/HTML 注释/属性）：评测按渲染后的可见性断言，'
                f'必须让它就出现在对应控件上，删掉这种隐藏副本')
        else:
            absent.append((req_id, kind, ent))
    total = len(facts)
    walled = (len(absent) >= _WALL_MIN and len(absent) >= _WALL_RATIO * total
              and crawl.html_pages <= 1)
    if walled:
        # 整墙查无此文 + 入口之外没有第二个页面 = 界面根本没实现，
        # 一条结构性根因胜过 20 条互不相干的抄写指令（修复环只吃前 20 条）
        where = (f"首页站内链接 {crawl.links} 条，打不开或不是页面的 "
                 f"{len(crawl.dead_links)} 条（{', '.join(crawl.dead_links[:5])}）"
                 if crawl.links else
                 "首页没有任何指向内部页面的链接")
        examples = "、".join(f'"{e}"' for _, _, e in absent[:3])
        failures.insert(0, (
            f"{len(absent)}/{total} 条逐字需求文案在页面源码里根本不存在，且"
            f"入口之外渲染不出第二个页面（HTML 页面 {crawl.html_pages} 个，"
            f"{where}）：这是**界面未实现**（只有 /api/* 的 JSON 不算），不是"
            f"文案拼错。每个模块都要有一条返回 HTML 文档的路由（含真实控件与"
            f"种子数据），首页用链接指过去——评测先导航再断言可见文案，路由不"
            f"在则全部用例第一步即落空。缺口的样例：{examples} …"))
    else:
        failures += [f'{r} 编译清单[{k}] "{e}" 未出现在入口可达页面'
                     for r, k, e in absent]
    # ---- 可点击通道（append 在最尾：不得挤掉上面任何一条指令）----------
    # 两种「不像控件」的红分开判：文案只是正文/标题，或顶着按钮标签却点了
    # 不会动（9/23 判分红叶取证）。需求承诺的是「点击 X」，评测按
    # getByRole('button'/'link', {name}) 硬定位、点完断言变化，两类都拿分。
    ctrl_corpus = ""
    bare_corpus = ""                            # 只认标签名的旧口径（分两种红用）
    click_seen = click_bad = 0
    for req_id, lab in _iter_click_facts(checklists):
        e = _norm(lab)
        if not e or (e not in text_norm and e not in attr_norm):
            continue     # 缺席/塞隐藏位已由主通道各自判过
        if e in script_norm:
            continue            # 客户端渲染：静态判分射程外
        if not ctrl_corpus:
            ctrl_corpus = _interactive_corpus(crawl.pages)
            bare_corpus = _interactive_corpus(crawl.pages,
                                              require_wiring=False)
        click_seen += 1
        if e in ctrl_corpus:
            continue
        click_bad += 1
        if click_bad <= _CLICK_FAIL_MAX:
            if e in bare_corpus:
                # 顶着按钮标签、却点了不会动：这条红必须点名「真接线」，
                # 否则修复环收到「做成 <button>」的指令，最省事的满足方式
                # 就是再往首页抄一批哑按钮（keep r1 的诱饵页正是这条路径）。
                failures.append(
                    f'{req_id} 编译清单[占位控件] "{lab}" 顶着 <button>/<a> '
                    f'标签但点了不会动：它既不在 <form> 内、也没有 onclick/'
                    f'hx-post/x-on:click 这类处理器（<a> 则连 href 都没有），'
                    f'所在页面更没有一段 <script>。评测点击后断言的是变化，'
                    f'这种控件与正文文字等价（本轮判分红叶即此类：一律 60 秒'
                    f'点击超时）——要么真接线（表单提交，或页内 JS 监听并真的'
                    f'改变可见状态），要么删掉占位、把控件放到真正处理它的页面'
                    f'上；再往首页抄一遍文案不算修好')
            else:
                failures.append(
                    f'{req_id} 编译清单[可点击控件] "{lab}" 在页面上只是文本，'
                    f'不是可点击元素：需求写的是点击它，评测按 getByRole'
                    f'("button"/"link", {{name}}) 定位且这类断言没有文本兜底'
                    f'——把它做成 <button> 或 <a href>，文案逐字放进元素内部，'
                    f'并保证点下去真的有反应')
    if click_bad > _CLICK_FAIL_MAX:
        failures.append(
            f'另有 {click_bad - _CLICK_FAIL_MAX} 条「点击 X」类控件同样只是'
            f'文本或点了不会动（同类缺陷，逐条指令已达上限）：按上一条的'
            f'口径一次改完')
    out = {"passed": found,
           "failed": len(failures), "total": total, "failures": failures,
           "client_side": len(client_side)}
    notes: list[str] = []
    if walled:
        notes.append(f"{len(absent)} 条「源码里查无此文」的同因事实已归并为一条"
                     f"结构性根因（HTML 页面 {crawl.html_pages} 个）；塞在不可见"
                     f"位置的文案不受此归并影响")
    if client_side:
        notes.append(f"{len(client_side)} 条逐字事实仅见于页内脚本正文"
                     f"（{'; '.join(client_side[:3])}…）：客户端渲染，静态判分"
                     f"射程外，未判红也未判绿")
    if click_seen:
        notes.append(f"{click_seen - click_bad}/{click_seen} 条「点击 X」类控件"
                     f"确为可点元素"
                     + (f"，{click_bad} 条只是文本已判红" if click_bad else ""))
    if notes:
        out["note"] = "；".join(notes)
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
