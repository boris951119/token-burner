# -*- coding: utf-8 -*-
"""写码门禁：模块契约锚点文案落地检查（v53 刀H；v56 降噪；批次#85 刀J'）。

病灶（github d462 / .tmp/v53-github）：ui_home.md 契约含
"Create an account" 等字面量，生成的 ui_home.py 0 处实现，模型用
幻觉 GitHub chrome 填充——契约在场但无机械拦截。

v55-sheet 尸检补强（INBOX-014）：
- 整表 UI 硬契约 89 锚点灌入 → 催跨域污染串重写，伤实现；
- 全文件子串出现率过「有没有」，过不了「在不在列表卡片」。

批次#85（v55-github 9355c0065d57）：
- 模型把契约抄进 `_GLOBAL_UI_COPY` 死常量（全仓零引用）；
- 实际渲染 /login 的 web_core 无 "Create an account"；
- 源码 grep 被死常量骗绿 → 必须查**路由渲染 HTML**。

刀J' 规则：
- surface=home → 起服后 GET / 可见 HTML 必须含锚点；
- surface=login → GET /login（及回退路径）可见 HTML 必须含锚点；
- 死常量 / display:none|hidden|aria-hidden 隐藏串 / 错页渲染 → 红；
- 源码 grep（check_manifest_landing）降级为辅。
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Mapping

MIN_ANCHORS = 4
HIT_RATIO = 0.5

# 验收清单 / 职责里的引号串
_QUOTED = re.compile(r"[\"“]([^\"”]{2,60})[\"”]")
# 顿号/逗号分隔短语（清单体）——仅用于刀C 逐字清单行，不再扫整表硬契约
_SPLIT = re.compile(r"[、,/|]")

_NOISE = re.compile(
    r"^(?:button|Flask Blueprint|JSON API|__global__|"
    r"account|session)$",
    re.I,
)

# 与 acceptance_compile._PLACEHOLDER / _BOOLISH 同口径（刀H 此前未接）
_PLACEHOLDER = re.compile(r"the\s+requested\s+workflow", re.I)
_BOOLISH = re.compile(r"^(?:true|false|yes|no|none|n/a)$", re.I)
# 截图 OCR 中文噪声：纯 CJK 短串且无拉丁（官方题面英文 UI 时不应进锚点）
_CJK_OCR = re.compile(r"^[\u4e00-\u9fff]{1,12}$")
# 位置指令行（v56-2 / 刀J'）
_HOME_CARD_LINE = re.compile(r"首页卡片须含\s*[:：]")
_LOGIN_PAGE_LINE = re.compile(r"登录页须含\s*[:：]")
_EDITOR_LINE = re.compile(r"编辑页须含\s*[:：]")
# v56-3：同段截断——surface 锚点只取本短语之后、下一段指令
# （｜ 分隔或任意「须含/须可见/须出现」短语）之前的引号串；
# 否则「｜控件须可见: …｜首页卡片须含: …」混排行会把控件侧串
# 全算进 home 锚点，运行时闸必红。
_SURFACE_TAIL_CUT = re.compile(
    r"[｜|]|(?:首页卡片须含|登录页须含|编辑页须含|控件须可见|动作后须出现)"
    r"\s*[:：]")
_CHECKLIST_HDR = "【验收节点逐字清单"
_HARD_MANIFEST_HDR = "【UI 页面与文案清单"

# surface → 候选路由（按序试；首个 200 且非空 HTML 胜出）
SURFACE_ROUTES: dict[str, tuple[str, ...]] = {
    "home": ("/",),
    "login": (
        "/login",
        "/signin",
        "/sign-in",
        "/sign_in",
        "/auth/login",
        "/session/new",
    ),
}

_SURFACE_LINE = {
    "home": _HOME_CARD_LINE,
    "login": _LOGIN_PAGE_LINE,
    "editor": _EDITOR_LINE,
}

_SURFACE_FIX_HINT = {
    "home": "请在 index 卡片模板补字段（外科补丁，禁止整文件重写）",
    "login": "请在登录页模板渲染该链接/控件（接到路由，禁止只写入死常量字典）",
    "editor": "请在编辑页模板补字段（外科补丁，禁止整文件重写）",
}


def _is_blacklisted(s: str) -> bool:
    if not s:
        return True
    if _PLACEHOLDER.search(s):
        return True
    if _BOOLISH.match(s.strip()):
        return True
    if _CJK_OCR.match(s.strip()):
        return True
    return False


def extract_manifest_anchors(responsibility: str) -> list[str]:
    """从模块职责抽锚点文案（v56：仅刀C 逐 REQ 清单，保序去重）。

    不再扫描【UI 页面与文案清单】整表硬契约（防 89 条跨域污染）。
    """
    text = responsibility or ""
    out: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        s = (raw or "").strip().strip("·•- ")
        if len(s) < 2 or len(s) > 60:
            return
        if _NOISE.match(s) or _is_blacklisted(s):
            return
        if s in seen:
            return
        seen.add(s)
        out.append(s)

    # 1) 刀C 逐字清单行（控件须可见 / 首页卡片须含 / 登录页须含 …）
    in_checklist = False
    for line in text.splitlines():
        if _CHECKLIST_HDR in line:
            in_checklist = True
            continue
        if in_checklist and line.startswith("【"):
            in_checklist = False
        if not in_checklist:
            continue
        body = line.strip()
        if not (body.startswith("-") or body.startswith("*")):
            for m in _QUOTED.finditer(body):
                _add(m.group(1))
            continue
        for m in _QUOTED.finditer(body):
            _add(m.group(1))
        if ":" in body or "：" in body:
            tail = re.split(r"[:：]", body, 1)[1]
            for part in _SPLIT.split(tail):
                part = part.strip().strip('"“”')
                _add(part)

    # 2) 若刀C 清单缺失，退回职责里的引号文案——但仍跳过整表硬契约块
    if len(out) < MIN_ANCHORS:
        in_hard = False
        for line in text.splitlines():
            if _HARD_MANIFEST_HDR in line or (
                    "硬契约" in line and "文案" in line
                    and "验收节点" not in line):
                in_hard = True
                continue
            if in_hard and line.startswith("【"):
                in_hard = False
            if in_hard:
                continue
            for m in _QUOTED.finditer(line):
                _add(m.group(1))

    return out


def _extract_surface_line_anchors(
    responsibility: str, surface: str,
) -> list[str]:
    """抽出指定 surface 位置指令行内的引号锚点。"""
    pat = _SURFACE_LINE.get(surface)
    if pat is None:
        return []
    text = responsibility or ""
    out: list[str] = []
    seen: set[str] = set()
    in_checklist = False
    for line in text.splitlines():
        if _CHECKLIST_HDR in line:
            in_checklist = True
            continue
        if in_checklist and line.startswith("【"):
            in_checklist = False
        if not in_checklist:
            continue
        for m in pat.finditer(line):
            tail = line[m.end():]
            cut = _SURFACE_TAIL_CUT.search(tail)
            if cut:
                tail = tail[:cut.start()]
            for q in _QUOTED.finditer(tail):
                s = q.group(1).strip()
                if _is_blacklisted(s) or len(s) < 2:
                    continue
                if s not in seen:
                    seen.add(s)
                    out.append(s)
    return out


def extract_home_surface_anchors(responsibility: str) -> list[str]:
    """抽出 surface=home 的锚点（『首页卡片须含』行内引号串）。"""
    return _extract_surface_line_anchors(responsibility, "home")


def extract_login_surface_anchors(responsibility: str) -> list[str]:
    """抽出 surface=login 的锚点（『登录页须含』行内引号串）。"""
    return _extract_surface_line_anchors(responsibility, "login")


def extract_surface_anchors(
    responsibility: str,
) -> dict[str, list[str]]:
    """按 surface 分桶抽出位置锚点（home/login/editor）。"""
    return {
        "home": extract_home_surface_anchors(responsibility),
        "login": extract_login_surface_anchors(responsibility),
        "editor": _extract_surface_line_anchors(responsibility, "editor"),
    }


class _VisibleHTML(HTMLParser):
    """重建可见 DOM 子树（含可见标签属性）；跳过 hidden/aria-hidden/
    display:none/visibility:hidden 以及 script/style/template。"""

    _SKIP_TAGS = frozenset({"script", "style", "template", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._stack: list[bool] = []

    @staticmethod
    def _is_hidden(tag: str, attrs: list) -> bool:
        if tag.lower() in _VisibleHTML._SKIP_TAGS:
            return True
        a = {str(k).lower(): ("" if v is None else str(v)) for k, v in attrs}
        if "hidden" in a:
            return True
        if a.get("aria-hidden", "").strip().lower() in ("true", "1"):
            return True
        style = a.get("style", "").lower().replace(" ", "")
        if "display:none" in style or "visibility:hidden" in style:
            return True
        return False

    def handle_starttag(self, tag, attrs):
        hide = self._is_hidden(tag, attrs)
        self._stack.append(hide)
        if hide or self._skip:
            self._skip += 1
            return
        # 保留可见标签属性（placeholder / aria-label / title 等亦为契约通道）
        bits = [f"<{tag}"]
        for k, v in attrs:
            if v is None:
                bits.append(f" {k}")
            else:
                bits.append(f' {k}="{v}"')
        bits.append(">")
        self.parts.append("".join(bits))

    def handle_startendtag(self, tag, attrs):
        if self._skip or self._is_hidden(tag, attrs):
            return
        bits = [f"<{tag}"]
        for k, v in attrs:
            if v is None:
                bits.append(f" {k}")
            else:
                bits.append(f' {k}="{v}"')
        bits.append(" />")
        self.parts.append("".join(bits))

    def handle_endtag(self, tag):
        if self._stack:
            was = self._stack.pop()
            if was or self._skip:
                self._skip = max(0, self._skip - 1)
                return
        if not self._skip:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if not self._skip and data:
            self.parts.append(data)


def visible_html(html: str) -> str:
    """去掉隐藏子树后的 HTML（供运行时闸匹配；失败时回落原文）。"""
    if not html:
        return ""
    p = _VisibleHTML()
    try:
        p.feed(html)
        p.close()
    except Exception:
        return html
    return "".join(p.parts)


def check_manifest_landing(
    code: str,
    *,
    responsibility: str = "",
    module: str = "",
    min_anchors: int = MIN_ANCHORS,
    hit_ratio: float = HIT_RATIO,
) -> list[str]:
    """源码 grep 辅闸（v56 降级）：返回问题列表（空=通过）。

    锚点 < min_anchors 时跳过（非 UI 模块 / 契约未注入）。
    主闸见 check_route_html / check_home_route_html。
    """
    anchors = extract_manifest_anchors(responsibility)
    if len(anchors) < min_anchors:
        return []
    src = code or ""
    missing = [a for a in anchors if a not in src]
    hit = len(anchors) - len(missing)
    ratio = hit / len(anchors) if anchors else 1.0
    if ratio >= hit_ratio:
        return []
    where = f"模块 {module}" if module else "本模块"
    by_surf = extract_surface_anchors(responsibility)
    home_anchors = set(by_surf.get("home") or [])
    login_anchors = set(by_surf.get("login") or [])
    home_miss = [m for m in missing if m in home_anchors]
    login_miss = [m for m in missing if m in login_anchors]
    other_miss = [
        m for m in missing
        if m not in home_anchors and m not in login_anchors
    ]
    msgs: list[str] = []
    if home_miss:
        fields = "、".join(f'「{m}」' for m in home_miss[:8])
        msgs.append(
            f"文案落地辅闸（{where}）：首页卡片缺 {fields}——"
            f"{_SURFACE_FIX_HINT['home']}"
        )
    if login_miss:
        fields = "、".join(f'「{m}」' for m in login_miss[:8])
        msgs.append(
            f"文案落地辅闸（{where}）：登录页缺 {fields}——"
            f"{_SURFACE_FIX_HINT['login']}"
        )
    if other_miss and (not home_miss and not login_miss
                       or ratio < hit_ratio * 0.5):
        miss_list = "、".join(f'「{m}」' for m in other_miss[:12])
        if len(other_miss) > 12:
            miss_list += f" 等共 {len(other_miss)} 条"
        msgs.append(
            f"文案落地辅闸（{where}）：契约锚点 {len(anchors)} 条，"
            f"源码命中 {hit}（{ratio:.0%} < {hit_ratio:.0%}）。"
            f"请外科补齐缺失文案：{miss_list}（禁止整文件重写风暴）"
        )
    return msgs


def check_route_html(
    html: str,
    *,
    surface: str = "home",
    responsibility: str = "",
    anchors: Iterable[str] | None = None,
    require_article: bool = False,
    module: str = "",
    route: str = "",
) -> list[str]:
    """刀J' 运行时路由 HTML 闸：surface 锚点必须出现在对应路由的可见 HTML。

    - 隐藏元素（hidden / aria-hidden / display:none）内的串不算命中；
    - require_article=True（仅 home）时进一步要求落在 <article> 内；
    - 缺时给外科指令（禁止整文件重写 / 禁止死常量字典）。
    """
    if anchors is not None:
        surf_anchors = [a for a in anchors if a]
    else:
        surf_anchors = _extract_surface_line_anchors(responsibility, surface)
    if not surf_anchors:
        return []
    routes = SURFACE_ROUTES.get(surface) or ("/",)
    route_label = route or routes[0]
    body = visible_html(html or "")
    scope = body
    if require_article and surface == "home":
        m = re.search(r"<article\b[^>]*>([\s\S]*?)</article>", body, re.I)
        if not m:
            where = f"模块 {module}" if module else "本模块"
            return [
                f"路由 HTML 闸（{where}，surface={surface}）："
                f"GET {route_label} 可见 HTML 无 <article>——"
                f"请在 index 卡片模板用 <article> 包裹列表卡片并补字段"
                f"（外科补丁，禁止整文件重写）"
            ]
        scope = " ".join(
            mm.group(1) for mm in re.finditer(
                r"<article\b[^>]*>([\s\S]*?)</article>", body, re.I)
        )
    missing = [a for a in surf_anchors if a not in scope]
    if not missing:
        return []
    where = f"模块 {module}" if module else "本模块"
    fields = "、".join(f'「{m}」' for m in missing[:8])
    where_hint = "（须落在 <article> 卡片内）" if (
        require_article and surface == "home") else ""
    hint = _SURFACE_FIX_HINT.get(surface, "请在对应路由模板补字段")
    return [
        f"路由 HTML 闸（{where}，surface={surface}）："
        f"GET {route_label} 可见 HTML 缺 {fields}{where_hint}——{hint}"
    ]


def check_home_route_html(
    html: str,
    *,
    responsibility: str = "",
    anchors: Iterable[str] | None = None,
    require_article: bool = False,
    module: str = "",
) -> list[str]:
    """兼容旧名：surface=home 的 check_route_html。"""
    return check_route_html(
        html,
        surface="home",
        responsibility=responsibility,
        anchors=anchors,
        require_article=require_article,
        module=module,
        route="/",
    )


def check_login_route_html(
    html: str,
    *,
    responsibility: str = "",
    anchors: Iterable[str] | None = None,
    module: str = "",
    route: str = "/login",
) -> list[str]:
    """surface=login：登录页可见 HTML 必须含锚点（治 #85 死常量/_GLOBAL_UI_COPY）。"""
    return check_route_html(
        html,
        surface="login",
        responsibility=responsibility,
        anchors=anchors,
        module=module,
        route=route,
    )


HOME_ANCHORS_SIDECAR = ".home_surface_anchors.json"
SURFACE_ANCHORS_SIDECAR = ".surface_route_anchors.json"


def collect_home_anchors_from_texts(texts: Iterable[str]) -> list[str]:
    """合并多段职责文本中的首页卡片锚点（保序去重）。"""
    out: list[str] = []
    seen: set[str] = set()
    for t in texts:
        for a in extract_home_surface_anchors(t or ""):
            if a not in seen:
                seen.add(a)
                out.append(a)
    return out


def collect_surface_anchors_from_texts(
    texts: Iterable[str],
) -> dict[str, list[str]]:
    """合并多段职责 → {surface: [anchors…]}（保序去重）。"""
    out: dict[str, list[str]] = {"home": [], "login": [], "editor": []}
    seen: dict[str, set[str]] = {k: set() for k in out}
    for t in texts:
        for surf, anchors in extract_surface_anchors(t or "").items():
            bucket = out.setdefault(surf, [])
            sset = seen.setdefault(surf, set())
            for a in anchors:
                if a not in sset:
                    sset.add(a)
                    bucket.append(a)
    return {k: v for k, v in out.items() if v}


def write_home_anchors_sidecar(code_dir, texts: Iterable[str]) -> list[str]:
    """兼容旧接口：写 home 列表 sidecar；同时写多 surface sidecar。"""
    by_surf = write_surface_anchors_sidecar(code_dir, texts)
    return list(by_surf.get("home") or [])


def write_surface_anchors_sidecar(
    code_dir, texts: Iterable[str],
) -> dict[str, list[str]]:
    """把 surface→锚点写入交付树 sidecar，供冒烟起服后 GET 对应路由验证。"""
    by_surf = collect_surface_anchors_from_texts(texts)
    root = Path(code_dir)
    try:
        (root / SURFACE_ANCHORS_SIDECAR).write_text(
            json.dumps(by_surf, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        # 旧冒烟只认 home 列表——双写保兼容
        home = list(by_surf.get("home") or [])
        (root / HOME_ANCHORS_SIDECAR).write_text(
            json.dumps(home, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    except Exception:
        return {}
    return by_surf


def load_surface_anchors_sidecar(code_dir) -> dict[str, list[str]]:
    """读 sidecar；优先多 surface，回落旧 home 列表。"""
    root = Path(code_dir)
    multi = root / SURFACE_ANCHORS_SIDECAR
    if multi.is_file():
        try:
            data = json.loads(multi.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        if isinstance(data, dict):
            out: dict[str, list[str]] = {}
            for k, v in data.items():
                if isinstance(v, list):
                    out[str(k)] = [a for a in v if isinstance(a, str) and a]
            return out
    legacy = root / HOME_ANCHORS_SIDECAR
    if legacy.is_file():
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
        except Exception:
            data = []
        if isinstance(data, list) and data:
            return {"home": [a for a in data if isinstance(a, str) and a]}
    return {}


def pick_route_html(
    route_bodies: Mapping[str, str],
    surface: str,
) -> tuple[str, str]:
    """从 {path: html} 里按 SURFACE_ROUTES 选一条；返回 (route, html)。"""
    candidates = SURFACE_ROUTES.get(surface) or ()
    for path in candidates:
        if path in route_bodies:
            return path, route_bodies[path] or ""
    # 大小写/尾斜杠宽松
    lower = {k.lower().rstrip("/") or "/": (k, v)
             for k, v in route_bodies.items()}
    for path in candidates:
        key = path.lower().rstrip("/") or "/"
        if key in lower:
            return lower[key]
    return (candidates[0] if candidates else "/", "")
