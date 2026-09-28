# -*- coding: utf-8 -*-
"""验收清单编译器：requirements.yaml → 逐节点可断言事实清单（零 LLM）。

交付前自评分环的地基：官方评测按需求文本的逐字文案/种子实体/入口控件
做精确断言（lite 双题 helpers 实证），这些事实全部可以从 YAML 机械
抽取——不需要 LLM"理解"，也不需要等官方评分才发现问题。

产出的 NodeChecklist 供三个消费方使用：
1. render_checklist_spec()：编译成 Playwright 静态断言 spec（首页可见
   类事实），本地判分逐 REQ 红绿；
2. 修复环：behavior_expectations（动作后断言）作为定向修复指令输入；
3. 生成期注入：种子/文案事实与 D 线契约模块（seed_contract /
   requirement_anchors）共享同一份抽取结果。

判定口径（通用规则，不含任何题目词汇）：
- 节点 GIVEN/WHEN 文案含 "home page"（或中文"首页"）→ 该节点事实
  在入口页静态可见，可编译成断言；否则标记导航后置，只入清单不判分
  （静态断言不可见实体=误红，会把修复环引向编造）。
- 引号串四通道（"…" / '…' / “…” / `…`，反引号只收像界面文案的串）：
  Seed data: 子句→种子实体；WHEN 引号→可操作控件；THEN 引号→期望文案。
  图片路径/代码围栏/文件名残渣一律剔除。
- 无引号 THEN/GIVEN 行为约束（刷新后仍在、排序、持久化等）：进入
  behavior_constraints，供 UX 清单与修环点名——静态判分不按整句扫页面
  （整句不在 DOM 里，扫了只会幻影红）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

_QUOTED_D = re.compile(r'"([^"\n]{1,80})"')
_QUOTED_S = re.compile(r"'([^'\n]{1,80})'")
# 中文题面的引号通道（9/23 取证）：官方题面存在整份中文需求，界面文案一律用
# “” 标注（单题实测 149 个唯一串）。只认 ASCII 引号时该题只编译出 2 条控件
# 事实——UI 保真契约与平台侧唯一判分闸双双空转。requirement_anchors 早已按
# “”‘’ 取值，这里是同一口径补齐。
_QUOTED_CJK = re.compile(r"[“「『]([^”」』\n]{1,80})[”」』]")
# Markdown 反引号通道（9/23 取证）：官方 bookstack 题面的界面文案全部写成
# `Shelves` / `Save Book` 式内联代码，前三条引号通道一条不认 → 34 节点编译
# 出 0 条事实：UX 契约与平台判分闸双双零输入。反引号同时被用来标代码符号，
# 故只收"像人话"的串（见 _ui_like）。
_QUOTED_BT = re.compile(r"`([^`\n]{1,80})`")
_MD_FENCE = re.compile(r"```[\s\S]*?```")
# 代码特征字符：带这些的多是端点/模板/表达式（/api/books、{note_id}、a==b），
# 不会作为界面文案出现在页面上
_BT_CODE = re.compile(r"""[(){}<>=|\\/%#$\[\]]|::|->""")
# 全小写单词/蛇形/路径：标识符与字段名（created_at、remember），非界面文案
_BT_IDENT = re.compile(r"^[a-z][A-Za-z0-9_.\-/]*$")
# 全大写的技术缩写：形似按钮文案（ADD TO CART）但不会出现在页面上
_BT_STOP = {
    "JSON", "HTML", "CSS", "YAML", "SQL", "XML", "NULL", "TRUE", "FALSE",
    "GET", "POST", "PUT", "PATCH", "API", "URL", "URI", "HTTP", "HTTPS",
    "CSV", "PDF", "PNG", "JPG", "SVG", "JWT", "ORM", "SPA", "SDK", "TODO",
}
# 官方 sheet 题面（9/24 重写版）场景步被出题器模板槽位污染（"the requested
# workflow" 实测 504 处）——这是占位残渣，不会出现在任何界面上。批次#71 判决：
# 对着它抽清单 = 清单垃圾化（动作后须出现大半是乱串）。全通道拉黑。
_PLACEHOLDER = re.compile(r"the\s+requested\s+workflow", re.I)
# description 引号里的布尔槽位（"true"/"false"），非界面文案
_BOOLISH = re.compile(r"^(?:true|false|yes|no|none|n/a)$", re.I)


def _ui_like(s: str) -> bool:
    """反引号串是否像界面文案（宁缺不滥：判错的代价是一条修不好的幻影失败）。"""
    if _BT_CODE.search(s) or _BT_IDENT.match(s):
        return False
    if s.strip() in _BT_STOP or s.strip().upper() in _BT_STOP:
        return False
    # 有大写字母或中文字符才像文案；纯小写单词一律视为标识符
    return bool(re.search(r"[A-Z\u4e00-\u9fff]", s))
# 中文没有空格，_clean_quote 的 12 词上限对 CJK 恒不生效；含句读的多半是
# 提示语/校验文案（"密码需包含字母和数字，且长度不小于8位"），不是控件标签
# ——按控件判分即幻影失败。行为断言通道（THEN）不受此限。
_CJK_MSG = re.compile(r"[，。；！？,;!?]")
_MD_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_SEED_LINE = re.compile(r"seed\s*data\s*:", re.I)
_FILE_RESIDUE = re.compile(
    r"\.(png|jpe?g|gif|svg|webp|ts|js|py|md|json|ya?ml|css|html)$", re.I)
# 路由/URL 整串（9/23 判分器幻影取证）：GWT 首步惯用 WHEN the user opens "/"，
# 引号通道把 "/" 当控件文案收进来——于是**一份服务端渲染、文案齐全的正确应用**
# 在平台唯一那道闸上仍稳定判红 1 条（实测 3/4 通过，红的就是这条）。路由是
# 跳转目标，浏览器把它显示在地址栏而非 DOM 里，任何逐字可见性断言都永不成立。
_ROUTE_TOKEN = re.compile(r"^(?:https?://\S*|\.{0,2}/\S*|#\S*/\S*)$")
_HOME_HINT = re.compile(r"home\s*page|homepage|首页", re.I)
# 凭据类种子（邮箱/密码/token）是登录输入值，不承诺页面可见——通用判据。
_CREDENTIAL_HINT = re.compile(r"@|password|passwd|token|secret", re.I)
_ENTRY_HINT = re.compile(
    r"entry\s*url|open\s+the\s+(application|app)|打开(应用|网站)", re.I)

# v56 / 刀J'：宿主页短语 → surface 标签（同一句内最近页短语；叙事句未知则 unknown）
_SURFACE_HOME = re.compile(
    r"workbook\s+home\s+page|home\s*page|homepage|列表页|首页", re.I)
_SURFACE_LOGIN = re.compile(
    r"sign[\s-]*in\s+page|login\s+page|sign[\s-]*in\s+screen|"
    r"\blog\s*in\s+page\b|登录页|登陆页|登录界面",
    re.I,
)
_SURFACE_EDITOR = re.compile(
    r"\beditors?\b|编辑页|编辑器", re.I)
_SURFACE_DIALOG = re.compile(
    r"\bdialogs?\b|\bmodals?\b|对话框|弹窗", re.I)
_SENT_BOUND = re.compile(r"[.!?。！？；;\n]+")

# ---- 官方题面的种子方言：存在句（9/23 官方 6 套 webapp 题面实测）-------------
# 上面 `Seed data:` 标记是我们【自己生成题面】的写法。官方不这么写：6/6 套题面
# 的 seed 事实实测为 0，它把"系统里已经有一条 X"写进各节点 description 的存在句
# （The system contains a note titled "…"），而官方用例 getByText 等的那一行恰是
# 它。判分环看不见 ⇒ 一份官方 0/32 的交付本地只凑出 6 条事实，连
# 「界面未实现」归并通道（_WALL_MIN=10）都永远够不到，修复环收到的是抄文案指令。
_EXIST_CLAUSE = re.compile(
    r"(?:"
    r"\b(?:system|app|application|database|backend|store|site|platform|page)s?\b"
    r"[\s\w,.-]{0,40}?\bcontain(?:s|ed)?\b"                 # The system contains …
    r"|\bthere\s+(?:is|are|was|were)\b"                      # There is a note …
    r"|\b(?:pre-?existing|existing|seeded)\b"                # an existing note …
    r"|\b(?:titled|named|called|labeled|labelled)\b"         # … titled "X"
    r"|\b(?:title|name|content|body|label|text)\s+(?:is|:|of)\b"
    r"|(?:包含|已有|预置|预设|内置|存在)"                       # 中文存在句
    r"|(?:标题|名称|题目)\s*(?:为|是|叫|[:：])"
    r")[\s\w,.:;'’\-()]{0,48}$", re.I)
# 账号/凭据语境（A verified account named "x" with password "y"）里的引号串是
# 评测登录时敲进输入框的值，界面不承诺预先显示——判红会教模型把用户名抄上首页
# （12306/ctrip/prestashop 题面几乎每个实体都挂在这种账号下：整族必须不判）。
_ACCOUNT_CTX = re.compile(
    r"\baccounts?\b|\buser(?:name)?s?\b|\blog\s*ins?\b|\bsign\s*ins?\b"
    r"|\bcredentials?\b|\bpasswords?\b|\bemails?\b|\bauthenticated\b|\bsessions?\b"
    r"|账号|帐号|用户名|登录|登陆|凭据", re.I)
# 否定存在句（watched tags do not include "python"）：题面承诺的是【不含】，
# 判"页面必须出现它"方向正好相反。
_NEG_CLAUSE = re.compile(
    r"\bdoes\s+not\b|\bdo\s+not\b|\bdon['’]t\b|\bnever\b|\bwithout\b"
    r"|\bnot\s+(?:be\s+)?(?:include|contain|present|shown|available)"
    r"|\bno\s+longer\b|不包含|没有|不存在|未包含", re.I)

# 无引号行为/流程约束：正式赛 sheet 题面（刷新后仍在、排序、过滤）的主失分面。
_CONSTRAINT_HINT = re.compile(
    r"\b(?:still|remain(?:s|ing)?|persist(?:s|ed|ing)?|retain(?:s|ed)?|"
    r"preserv(?:e|es|ed)|unchanged|same\s+order|after\s+(?:a\s+)?"
    r"(?:refresh|reload|reload(?:ing)?|save|submit)|"
    r"sort(?:ed|ing)?|order(?:ed|ing)?|ascend(?:ing)?|descend(?:ing)?|"
    r"filter(?:ed|ing)?|visible|hidden|disabled|enabled|must|should|"
    r"keep(?:s|ing)?|reappear|survive)\b|"
    r"刷新|重载|仍(?:然|旧)?|保持|持久|排序|升序|降序|过滤|可见|隐藏|"
    r"禁用|启用|保存后|提交后|必须|不得|不能消失|还在",
    re.I,
)


@dataclass
class NodeChecklist:
    """一个 ATOMIC 节点的全部可断言事实。"""
    req_id: str
    req_name: str
    module_id: str
    language: str                      # en | zh | mixed（需求文字系别）
    home_visible: bool                 # 事实是否可在入口页静态断言
    seed_entities: list[str] = field(default_factory=list)
    control_labels: list[str] = field(default_factory=list)
    # 动作后期望文案（WHEN 操作产生的 snackbar/跳转等）；v56 起亦进
    # render_checklist_spec 静态断言（按 fact_surfaces 路由宿主页）。
    behavior_expectations: list[str] = field(default_factory=list)
    # control_labels 里由「点击/按下/选择」类动词引出的子集：这类文案必须
    # 落在可点控件里（<button>/<a>/role=menuitem…），只做成正文文字在评测
    # 眼里等于不存在——该通道的硬判分在 acceptance_judge。
    click_controls: list[str] = field(default_factory=list)
    # 无引号 THEN/GIVEN 行为约束原文（截断）：不进静态扫页，只进 UX/修环。
    behavior_constraints: list[str] = field(default_factory=list)
    scenarios: list[dict] = field(default_factory=list)   # 原 GWT steps
    # v56 / 刀J'：引号事实 → 宿主页标签列表（home|login|editor|dialog|unknown）；
    # 双句双标签（同一串可同时挂 home+editor）。
    fact_surfaces: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def surfaces_of(self, fact: str) -> list[str]:
        """事实的宿主页标签；无标注时按 home_visible 启发式回落。"""
        tagged = self.fact_surfaces.get(fact) or []
        if tagged:
            return list(tagged)
        if self.home_visible:
            return ["home"]
        return ["unknown"]


def _constraint_text(content: str) -> str | None:
    s = " ".join((content or "").split())
    if len(s) < 8:
        return None
    return s[:240]


def _tag_surface(bucket: dict[str, list[str]], fact: str, surface: str) -> None:
    """保序去重地给事实追加 surface 标签。"""
    if not fact:
        return
    surf = surface or "unknown"
    lst = bucket.setdefault(fact, [])
    if surf not in lst:
        lst.append(surf)


def _sentence_containing(text: str, pos: int) -> tuple[str, int]:
    """返回含 pos 的句子及其在整段中的起点。"""
    if not text or pos < 0:
        return text or "", 0
    starts = [0]
    for m in _SENT_BOUND.finditer(text):
        starts.append(m.end())
    starts.append(len(text) + 1)
    for i in range(len(starts) - 1):
        a, b = starts[i], starts[i + 1]
        if a <= pos < b:
            return text[a:b], a
    return text, 0


def _surface_in_sentence(sentence: str, local_pos: int) -> str:
    """同一句内最近页短语 → home|login|editor|dialog|unknown。

    优先取引号**左侧**最近短语（宿主声明在契约前）；左侧无则取右侧最近。
    login 优先于笼统 home（「从登录页回首页」叙事里 sign-in page 更近契约）。
    """
    hits: list[tuple[int, str]] = []
    for pat, label in (
        (_SURFACE_LOGIN, "login"),
        (_SURFACE_HOME, "home"),
        (_SURFACE_EDITOR, "editor"),
        (_SURFACE_DIALOG, "dialog"),
    ):
        for m in pat.finditer(sentence or ""):
            hits.append((m.start(), label))
    if not hits:
        return "unknown"
    left = [(p, lab) for p, lab in hits if p <= local_pos]
    if left:
        return max(left, key=lambda t: t[0])[1]
    return min(hits, key=lambda t: abs(t[0] - local_pos))[1]


def _surface_at(text: str, abs_pos: int) -> str:
    sent, sent_start = _sentence_containing(text or "", abs_pos)
    return _surface_in_sentence(sent, abs_pos - sent_start)


def _quotes_with_surface(text: str, *, for_control: bool = False
                         ) -> list[tuple[str, str]]:
    """抽引号文案并按同一句最近页短语打 surface 标签。"""
    if not text:
        return []
    body = _MD_FENCE.sub(" ", _MD_IMG.sub("", text))
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pat, bt in ((_QUOTED_D, False), (_QUOTED_CJK, False), (_QUOTED_BT, True)):
        for m in pat.finditer(body):
            q = _clean_quote(m.group(1))
            if not q or (bt and not _ui_like(q)):
                continue
            if for_control and _CJK_MSG.search(q):
                continue
            surf = _surface_at(body, m.start())
            key = (q, surf)
            if key in seen:
                continue
            seen.add(key)
            out.append((q, surf))
    for m in _QUOTED_S.finditer(body):
        q = _clean_quote(m.group(1))
        if not q or (for_control and _CJK_MSG.search(q)):
            continue
        surf = _surface_at(body, m.start())
        key = (q, surf)
        if key in seen:
            continue
        seen.add(key)
        out.append((q, surf))
    return out


def _clean_quote(s: str) -> str | None:
    s = s.strip()
    if not s or _FILE_RESIDUE.search(s):
        return None
    if _ROUTE_TOKEN.match(s):
        return None                     # 路由/URL 是跳转目标，不是界面文案
    if _SEED_LINE.search(s) or len(s.split()) > 12:
        return None                     # 描述残渣/整句，不是 UI 文案
    if _PLACEHOLDER.search(s):
        return None                     # 官方模板槽位残渣，永不作为界面文案
    return s


def _quotes_in(text: str, *, skip_seed_clause: bool = False,
               for_control: bool = False) -> list[str]:
    """抽一段文本里的引号文案（双/单/中文/反引号），剔图片、代码围栏与文件名。
    for_control：控件标签通道额外剔掉含句读的中文串（多半是提示语，
    按"必须出现在页面上"判分即幻影失败）；行为断言通道保留原文。"""
    if not text:
        return []
    body = _MD_FENCE.sub(" ", _MD_IMG.sub("", text))
    out: list[str] = []
    for pat, bt in ((_QUOTED_D, False), (_QUOTED_CJK, False), (_QUOTED_BT, True)):
        for m in pat.finditer(body):
            q = _clean_quote(m.group(1))
            if not q or (bt and not _ui_like(q)):
                continue
            if for_control and _CJK_MSG.search(q):
                continue
            if q not in out:
                out.append(q)
    # 单引号通道：仅在无跳过需求时补（WHEN/THEN 主体），seed 通道自行去重
    if not skip_seed_clause:
        for m in _QUOTED_S.finditer(body):
            q = _clean_quote(m.group(1))
            if q and not (for_control and _CJK_MSG.search(q)) and q not in out:
                out.append(q)
    return out


# 需求里的「点击 "X"」是一条硬通道：评测按 getByRole('button'/'link', {name})
# 定位 X，这类断言没有文本兜底——X 只做成正文文字，该节点全部用例即落空
# （官方题两连败的死因）。动词按引号前最近窗口逐条判定，不能按整步含不含
# click 归类：一步里常混着输入动词（type "Search" and click "Go"），整步
# 判定会把搜索框误升成「必须是按钮」。
_CLICK_VERB = re.compile(
    r"(?:click|press|tap|hit|select|choose|toggle|open|submit"
    r"|点击|按下|轻点|选择|切换|打开|提交)[\s\w'’()/…-]{0,16}$", re.I)


def _click_quotes_in(text: str) -> list[str]:
    """WHEN 步骤里由点击类动词引出的引号文案（须落在可点控件的子集）。"""
    out: list[str] = []
    if not text:
        return out
    body = _MD_FENCE.sub(" ", _MD_IMG.sub("", text))
    # 反引号通道不能漏：题面有两种界面文案写法（引号 / Markdown 反引号），
    # 只认引号的那一类任务整条通道静默失效——6 套题面实测比是 0 : 30+。
    for pat, bt in ((_QUOTED_D, False), (_QUOTED_CJK, False),
                    (_QUOTED_S, False), (_QUOTED_BT, True)):
        for m in pat.finditer(body):
            q = _clean_quote(m.group(1))
            if not q or _CJK_MSG.search(q) or (bt and not _ui_like(q)):
                continue
            if not _CLICK_VERB.search(body[:m.start()]):
                continue
            if q not in out:
                out.append(q)
    return out


# WHEN 里「输入类」动词引出的引号文案是**评测自己敲进控件的值**（type "kw"
# into the box / 填写标题 "X"），界面并不预先显示它：按控件文案判「未出现在
# 页面上」是假红，而模型最省事的"修法"恰是把它塞成 placeholder 或藏进隐藏块
# ——9/23 mini 彩排实测：3 条事实里 1 条即此类，交付真把它塞进了 hidden 表单。
# 与点击通道同法按引号左侧最近窗口判定；点击动词同样近身时让位（「点击 X」的
# X 必须是真控件，不能因为同句里还有个 fill 就被放弃这条硬通道）。
_TYPE_VERB = re.compile(
    r"(?:\b(?:type|types|typing|enter|enters|entered|fill|fills|filled"
    r"|write|writes|writing|paste|pastes)\b|输入|填写|键入|填入)"
    r"[\s\w'’()/…\-]{0,40}$", re.I)
# 勾选类动词短窗口（只用于「别剔除」这一侧，见 _typed_quotes_in 内的注释）。
_TICK_VERB = re.compile(
    r"(?:\b(?:check|checks|checked|tick|ticks|ticked|mark|marks)\b"
    r"|勾选|勾上|选中)[\s\w'’()/…\-]{0,12}$", re.I)
# 但引号紧跟「命名类名词」时它是**名字而不是值**，两类都要留在控件通道：
# 字段类（fill in the "Title" field——评测按 getByLabel/getByPlaceholder 定位的
# 就是它）与去处类（Enter the "Settings" tab / Enter the "Checkout" step——那是
# 必须存在且可点的页签/步骤名，官方题面实测有这一形）。窗口只允许夹一个词，
# 否则 type "X" into the search box 会被误留。
_NAME_NOUN_AFTER = re.compile(
    r"^\s{0,2}(?:[\w一-鿿]{1,12}\s+)?\s*"
    r"(?:fields?|boxes|box|inputs?|text\s*fields?|textboxes?|areas?|columns?"
    r"|tabs?|steps?|pages?|screens?|views?|sections?|flows?|menus?|routes?"
    r"|URLs?|links?|下拉|字段|输入框|文本框|框|栏|步骤|标签页?|页|面板)"
    # 名词后面紧跟另一个引号串时它属于**下一条**（with title "A" and URL "B"），
    # 不是本条引号的名字——不这样判，一句里连着填两个字段就被误当字段名留下。
    r"""\b(?!\s*["'`“‘])""", re.I)


def _typed_quotes_in(text: str) -> set[str]:
    """WHEN 步骤里由输入类动词引出的引号文案（评测打进去的值，不判界面）。"""
    out: set[str] = set()
    if not text:
        return out
    body = _MD_FENCE.sub(" ", _MD_IMG.sub("", text))
    for pat in (_QUOTED_D, _QUOTED_CJK, _QUOTED_S, _QUOTED_BT):
        for m in pat.finditer(body):
            left = body[:m.start()]
            # 让位给「更近身的动作动词」：勾选类不进 _CLICK_VERB（那里加词会
            # 把 "check whether the page shows X" 的提示语误升成必须可点），
            # 但在这条剔除通道里 check/tick 紧邻的引号是复选框名，不是值。
            if (not _TYPE_VERB.search(left) or _CLICK_VERB.search(left)
                    or _TICK_VERB.search(left)):
                continue
            if _NAME_NOUN_AFTER.match(body[m.end():]):
                continue          # 引号里是字段名/去处名，不是要打的值
            q = _clean_quote(m.group(1))
            if q:
                out.add(q)
    return out


def _existence_seeds(text: str) -> list[str]:
    """description 存在句里声明「系统里已经存在」的实体名（官方题面的种子写法）。

    按引号左侧窗口逐条判定（与点击/输入通道同一手法），三条守卫缺一即假红：
    账号语境（那是登录输入值）、否定语境（承诺的是不含）、非存在句引号
    （WHEN 里的控件由控件通道承诺，这里不重复挂一条）。
    """
    out: list[str] = []
    if not text:
        return out
    body = _MD_IMG.sub("", text)
    for pat, bt in ((_QUOTED_D, False), (_QUOTED_CJK, False),
                    (_QUOTED_S, False), (_QUOTED_BT, True)):
        for m in pat.finditer(body):
            q = _clean_quote(m.group(1))
            if not q or (bt and not _ui_like(q)) or _CREDENTIAL_HINT.search(q):
                continue
            left = body[max(0, m.start() - 160):m.start()]
            if _NEG_CLAUSE.search(left) or _ACCOUNT_CTX.search(left):
                continue
            if not _EXIST_CLAUSE.search(left):
                continue
            if q not in out:
                out.append(q)
    return out


def _seed_entities_of(description: str) -> list[str]:
    """description 里的种子实体：`Seed data:` 子句 + 官方题面的存在句两种方言。"""
    out: list[str] = []
    for m in _SEED_LINE.finditer(description or ""):
        rest = description[m.end():]
        cut = rest.find("\n")
        if cut >= 0:
            rest = rest[:cut]
        for pat, bt in ((_QUOTED_D, False), (_QUOTED_CJK, False),
                        (_QUOTED_BT, True)):
            for q in pat.finditer(_MD_IMG.sub("", rest)):
                n = _clean_quote(q.group(1))
                if n and not (bt and not _ui_like(n)) and n not in out:
                    out.append(n)
    for n in _existence_seeds(description or ""):
        if n not in out:
            out.append(n)
    return out


def load_yaml_robust(path: Path) -> dict:
    """官方题面 YAML 是外部输入，实测存在多缩进硬伤（9/22 webapp 副本：
    description 比同级 type 多 4 空格、steps content 比同组多 4 空格 →
    ScannerError）。策略：让 PyYAML 报错定位坏行，逐行把该行缩进回退到
    同块兄弟基准（前一行是 '- ' 序列项则 +2，否则取前一行缩进），循环
    直至解析成功或无可进展（上限 400 次）。永不猜改正常行。"""
    import yaml

    text = path.read_text(encoding="utf-8")
    seen: set[tuple[int, int]] = set()
    for _ in range(400):
        try:
            data = yaml.safe_load(text)
            return data if isinstance(data, dict) else {}
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            if mark is None:
                return {}
            lines = text.split("\n")
            i = int(mark.line)
            if i >= len(lines):
                return {}
            cur = lines[i]
            cur_ind = len(cur) - len(cur.lstrip())
            j = i - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            if j < 0:
                return {}
            prev = lines[j]
            prev_ind = len(prev) - len(prev.lstrip())
            if cur_ind <= prev_ind:
                return {}          # 损伤不在缩进层级，交空降级
            new_ind = (prev_ind + 2 if prev.lstrip().startswith("-")
                       else prev_ind)
            if (i, cur_ind) in seen or cur_ind == new_ind:
                return {}          # 无进展，防死循环
            seen.add((i, cur_ind))
            lines[i] = " " * new_ind + cur.lstrip()
            text = "\n".join(lines)
    return {}


def compile_checklists(yaml_path: Path) -> list[NodeChecklist]:
    """requirements.yaml → 逐 ATOMIC 节点验收清单（文档序）。"""
    data = load_yaml_robust(Path(yaml_path))
    if not data:
        return []
    return _walk_tree(data)


def _walk_tree(root: dict) -> list[NodeChecklist]:
    out: list[NodeChecklist] = []

    def walk(node: dict, module_id: str) -> None:
        for child in node.get("children") or []:
            cid = str(child.get("id") or "")
            if child.get("type") == "FOLDER":
                walk(child, cid or module_id)
                continue
            out.append(_build_node(child, module_id))
            walk(child, module_id)   # ATOMIC 下挂子节点的题目形态也兼容

    walk(root, str(root.get("id") or "ROOT"))
    return out


def _build_node(child: dict, module_id: str) -> NodeChecklist:
    return _facts(
        req_id=str(child.get("id") or ""),
        name=str(child.get("name") or ""),
        desc=str(child.get("description") or ""),
        scenarios=child.get("scenarios") or [],
        module_id=module_id,
    )


def _facts(req_id: str, name: str, desc: str, scenarios: list[dict],
           module_id: str) -> NodeChecklist:
    """节点四要素 → NodeChecklist（YAML 与文本两通道共用的事实口径）。"""
    from app.utils.ui_language import requirement_language

    steps_text_all = [desc, name]
    home_visible = bool(_HOME_HINT.search(desc) or _ENTRY_HINT.search(desc))
    behavior: list[str] = []
    constraints: list[str] = []
    controls: list[str] = []
    clicks: list[str] = []
    fact_surfaces: dict[str, list[str]] = {}

    def _push_constraint(content: str) -> None:
        c = _constraint_text(content)
        if c and c not in constraints:
            constraints.append(c)

    for sc in scenarios:
        for s in sc.get("steps") or []:
            kw = str(s.get("keyword") or "").upper()
            content = str(s.get("content") or "")
            steps_text_all.append(content)
            if kw in ("GIVEN", "WHEN"):
                if _HOME_HINT.search(content) or _ENTRY_HINT.search(content):
                    home_visible = True
                if kw == "GIVEN" and _CONSTRAINT_HINT.search(content):
                    # GIVEN 无引号持久化/前置状态：引号通道看不见
                    if not _quotes_in(content):
                        _push_constraint(content)
                if kw == "WHEN":
                    typed = _typed_quotes_in(content)
                    for q, surf in _quotes_with_surface(content, for_control=True):
                        if q in typed:
                            continue   # 输入值由评测自己敲，不承诺界面预先显示
                        if q not in controls:
                            controls.append(q)
                        _tag_surface(fact_surfaces, q, surf)
                    for q in _click_quotes_in(content):
                        if q not in clicks:
                            clicks.append(q)
            elif kw == "THEN":
                for q, surf in _quotes_with_surface(content):
                    if q not in behavior:
                        behavior.append(q)
                    _tag_surface(fact_surfaces, q, surf)
                qs = [q for q, _ in _quotes_with_surface(content)]
                # 无引号整句，或带引号但仍含持久化/排序等约束词
                if not qs or _CONSTRAINT_HINT.search(content):
                    _push_constraint(content)
    seeds = [s for s in _seed_entities_of(desc)
             if not _CREDENTIAL_HINT.search(s)
             # 同一节点里既是种子名又是控件名的串只挂一条（官方题面实测 4/47）：
             # 两处各判一次会凭空多一条红，还会把修复环 20 条指令的额度占掉。
             and s not in controls]
    for s in seeds:
        _tag_surface(fact_surfaces, s, "home" if home_visible else "unknown")
    # desc 句内对种子的 surface 覆盖/追加（双宿主）
    for q, surf in _quotes_with_surface(desc):
        if q in seeds and surf != "unknown":
            _tag_surface(fact_surfaces, q, surf)
    # THEN 里复述的种子名不算行为断言（它们由 seed 通道静态覆盖）
    behavior = [b for b in behavior if b not in seeds and b not in controls]
    # description 逐字契约通道（批次#71 判决：sheet 题面 ~110 条双引号 UI 事实
    # 全在 desc——"Last updated: <last updated value>" 等，官方隐藏测试按这些
    # 断言；场景步被占位符污染后 desc 是唯一可靠来源）。模板字面量的 <...> 是
    # 变量位，判分锚取 '<' 前固定前缀，否则按字面判红永远修不好。
    for q, surf in _quotes_with_surface(desc):
        if _BOOLISH.match(q):
            continue
        stem = q.split("<", 1)[0].strip().rstrip(":：,，;；")
        fact = stem if len(stem) >= 4 else q
        if fact in seeds:
            continue
        if fact in controls:
            # 控件已由 WHEN 句打标（无页短语句 → unknown）；desc 句内
            # 更强的页短语定位（sign-in page → login）仍须叠加，否则
            # 「desc 说在登录页、WHEN 只说点击」的串永远落 unknown。
            if surf != "unknown":
                _tag_surface(fact_surfaces, fact, surf)
            continue
        if fact not in behavior:
            behavior.append(fact)
        # unknown 且节点 home_visible → 回落 home（与自测同构启发式一致）
        use = surf if surf != "unknown" else (
            "home" if home_visible else "unknown")
        _tag_surface(fact_surfaces, fact, use)
    # 可点击子集必须是控件全集的子集：控件通道另有剔除口径（整句中文提示、
    # 路由串等），此处独走一套正则会判红一条主通道已经放弃的事实。
    clicks = [c for c in clicks if c in controls]
    full_text = "\n".join(steps_text_all)
    return NodeChecklist(
        req_id=req_id,
        req_name=name,
        module_id=module_id,
        language=requirement_language(full_text),
        home_visible=home_visible,
        seed_entities=seeds,
        control_labels=controls,
        behavior_expectations=behavior,
        click_controls=clicks,
        behavior_constraints=constraints,
        scenarios=[dict(s) for s in scenarios],
        fact_surfaces=fact_surfaces,
    )


_NODE_TEXT_RE = re.compile(r"^###\s+(\S+)(.*)$")
_SCEN_TEXT_RE = re.compile(r"^\s*[-*]\s*场景\s*[:：]\s*(.*)$")
_STEP_TEXT_RE = re.compile(
    r"^\s*(GIVEN|WHEN|THEN|AND|BUT)\s*[:：]\s*(.*)$", re.I)


def compile_checklists_from_text(requirement: str) -> list[NodeChecklist]:
    """管线需求文本（arcbench_ingest 渲染版）→ 逐节点验收清单（零 LLM）。

    拆分期注入用：那时只有渲染文本没有 YAML 文件。与 compile_checklists
    同一事实通道（_facts），无 ### 节点段/无场景步骤的题面返回空表。"""
    out: list[NodeChecklist] = []
    cur: dict | None = None

    def flush() -> None:
        if cur is None:
            return
        out.append(_facts(
            req_id=cur["id"], name=cur["name"], desc="\n".join(cur["desc"]),
            scenarios=cur["scenarios"], module_id=cur["module"]))

    module = "ROOT"
    for ln in (requirement or "").splitlines():
        if ln.startswith("## "):
            flush()
            cur = None
            if ln[3:].strip().startswith("模块"):
                mm = re.match(r"模块[:：]\s*(\S+)", ln[3:].strip())
                if mm:
                    module = mm.group(1)
            continue
        m = _NODE_TEXT_RE.match(ln)
        if m:
            flush()
            cur = {"id": m.group(1),
                   "name": m.group(2).replace("（验收标准）", "").strip(),
                   "desc": [], "scenarios": [], "module": module}
            continue
        if cur is None:
            continue
        sm = _SCEN_TEXT_RE.match(ln)
        if sm:
            cur["scenarios"].append({"name": sm.group(1), "steps": []})
            continue
        tm = _STEP_TEXT_RE.match(ln)
        if tm:
            step = {"keyword": tm.group(1).upper(), "content": tm.group(2)}
            if not cur["scenarios"]:
                cur["scenarios"].append({"name": "", "steps": []})
            # AND/BUT 归属前一关键词（与官方 GWT 语义一致）
            kw = tm.group(1).upper()
            if kw in ("AND", "BUT") and cur["scenarios"][-1]["steps"]:
                prev = cur["scenarios"][-1]["steps"][-1]["keyword"]
                step = {"keyword": prev, "content": tm.group(2)}
                cur["scenarios"][-1]["steps"].append(step)
            else:
                cur["scenarios"][-1]["steps"].append(step)
            continue
        cur["desc"].append(ln)
    flush()
    return out


# ---------------------------------------------------------------- 渲染器

def _ts_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


_SPEC_HELPERS = """\
import { test, expect } from '@playwright/test';

// token-burner 编译期验收清单（acceptance_compile 生成，零 LLM）。
// v56：按宿主页断言——home 只查 GET /；editor 先点种子链接再查；
// 废除「一跳任意页命中即绿」的 visibleOnReachable 假绿口径。
// CHK-SEED / CHK-CTRL / CHK-BEH：种子 / 控件 / behavior_expectations。

async function visibleOnHome(page: import('@playwright/test').Page,
                             text: string): Promise<boolean> {
  try { await page.goto('/', { timeout: 8000 }); } catch { return false; }
  return await page.getByText(text).first().isVisible().catch(() => false);
}

async function visibleControlOnHome(page: import('@playwright/test').Page,
                                    lab: string): Promise<boolean> {
  try { await page.goto('/', { timeout: 8000 }); } catch { return false; }
  const loc = page.getByText(lab)
    .or(page.getByPlaceholder(lab))
    .or(page.getByLabel(lab))
    .or(page.getByRole('button', { name: lab }));
  return await loc.first().isVisible().catch(() => false);
}

async function visibleAfterSeedClick(
    page: import('@playwright/test').Page,
    text: string,
    seedName: string): Promise<boolean> {
  try { await page.goto('/', { timeout: 8000 }); } catch { return false; }
  if (seedName) {
    const link = page.getByRole('link', { name: seedName }).first();
    const ok = await link.isVisible().catch(() => false);
    if (ok) {
      try { await link.click({ timeout: 5000 }); } catch { /* stay */ }
    }
  }
  return await page.getByText(text).first().isVisible().catch(() => false);
}
"""


def _seed_for_editor(ck: NodeChecklist) -> str:
    """编辑页断言前要点的种子链接名（取首个种子实体）。"""
    return (ck.seed_entities[0] if ck.seed_entities else "")


def _should_emit_spec(ck: NodeChecklist) -> bool:
    """home_visible 节点，或带 home/editor/dialog 宿主事实的节点进自测。"""
    if ck.home_visible:
        return True
    for fact, surfs in (ck.fact_surfaces or {}).items():
        if any(s in ("home", "editor", "dialog") for s in surfs):
            if (fact in ck.seed_entities or fact in ck.control_labels
                    or fact in ck.behavior_expectations):
                return True
    return False


def render_checklist_spec(checklists: list[NodeChecklist]) -> str:
    """节点事实 → 自包含 Playwright 静态断言 spec（无 helpers 依赖）。

    v56-1 自测同构：
    - behavior_expectations（含 desc 模板前缀如 Last updated）纳入断言；
    - surface=home / home_visible：只在 GET / 断言，废除 visibleOnReachable；
    - surface=editor：先点种子链接再断言。
    """
    blocks: list[str] = []
    for ck in checklists:
        if not _should_emit_spec(ck):
            continue
        seed_name = _seed_for_editor(ck)

        def _emit_text(kind: str, fact: str, surfaces: list[str]) -> None:
            surfs = surfaces or (["home"] if ck.home_visible else ["unknown"])
            # unknown + home_visible → 按 home；纯 unknown 且非 home_visible 跳过
            effective: list[str] = []
            for s in surfs:
                if s == "unknown":
                    if ck.home_visible:
                        effective.append("home")
                else:
                    effective.append(s)
            # 去重保序
            seen: set[str] = set()
            ordered = []
            for s in effective:
                if s not in seen:
                    seen.add(s)
                    ordered.append(s)
            if not ordered and ck.home_visible:
                ordered = ["home"]
            for surf in ordered:
                if surf == "home":
                    blocks.append(
                        f"  test('{ck.req_id} {kind}@home: {_ts_str(fact)}', "
                        "async ({ page }) => {\n"
                        f"    const found = await visibleOnHome(page, "
                        f"{_ts_str(fact)});\n"
                        f"    expect(found, {_ts_str('首页未见: ' + fact)}"
                        ").toBe(true);\n"
                        "  });")
                elif surf == "login":
                    blocks.append(
                        f"  test('{ck.req_id} {kind}@login: {_ts_str(fact)}', "
                        "async ({ page }) => {\n"
                        "    await page.goto('/login').catch(async () => "
                        "page.goto('/signin'));\n"
                        f"    const found = await page.getByText("
                        f"{_ts_str(fact)}, {{ exact: false }})"
                        ".first().isVisible().catch(() => false);\n"
                        f"    expect(found, {_ts_str('登录页未见: ' + fact)}"
                        ").toBe(true);\n"
                        "  });")
                elif surf == "editor":
                    blocks.append(
                        f"  test('{ck.req_id} {kind}@editor: {_ts_str(fact)}', "
                        "async ({ page }) => {\n"
                        f"    const found = await visibleAfterSeedClick(page, "
                        f"{_ts_str(fact)}, {_ts_str(seed_name)});\n"
                        f"    expect(found, "
                        f"{_ts_str('编辑页未见: ' + fact)}"
                        ").toBe(true);\n"
                        "  });")
                elif surf == "dialog":
                    # 对话框：先到首页再断言（无独立路由时退化为首页可见）
                    blocks.append(
                        f"  test('{ck.req_id} {kind}@dialog: {_ts_str(fact)}', "
                        "async ({ page }) => {\n"
                        f"    const found = await visibleOnHome(page, "
                        f"{_ts_str(fact)});\n"
                        f"    expect(found, {_ts_str('对话框文案未见: ' + fact)}"
                        ").toBe(true);\n"
                        "  });")

        for ent in ck.seed_entities:
            _emit_text("CHK-SEED", ent, ck.surfaces_of(ent))
        for lab in ck.control_labels:
            surfs = ck.surfaces_of(lab)
            # 控件在 home 用专用 locator（含 placeholder/label/button）
            eff = []
            for s in (surfs or ["home"]):
                if s == "unknown" and ck.home_visible:
                    eff.append("home")
                elif s != "unknown":
                    eff.append(s)
            if not eff and ck.home_visible:
                eff = ["home"]
            seen_s: set[str] = set()
            for surf in eff:
                if surf in seen_s:
                    continue
                seen_s.add(surf)
                if surf == "home":
                    blocks.append(
                        f"  test('{ck.req_id} CHK-CTRL@home: {_ts_str(lab)}', "
                        "async ({ page }) => {\n"
                        "    const found = await visibleControlOnHome(page, "
                        + _ts_str(lab) + ");\n"
                        f"    expect(found, {_ts_str('首页未见控件: ' + lab)}"
                        ").toBe(true);\n"
                        "  });")
                elif surf == "login":
                    blocks.append(
                        f"  test('{ck.req_id} CHK-CTRL@login: {_ts_str(lab)}', "
                        "async ({ page }) => {\n"
                        "    await page.goto('/login').catch(async () => "
                        "page.goto('/signin'));\n"
                        f"    const found = await page.getByText("
                        f"{_ts_str(lab)}, {{ exact: false }})"
                        ".first().isVisible().catch(() => false);\n"
                        f"    expect(found, {_ts_str('登录页未见控件: ' + lab)}"
                        ").toBe(true);\n"
                        "  });")
                elif surf == "editor":
                    blocks.append(
                        f"  test('{ck.req_id} CHK-CTRL@editor: {_ts_str(lab)}', "
                        "async ({ page }) => {\n"
                        f"    const found = await visibleAfterSeedClick(page, "
                        f"{_ts_str(lab)}, {_ts_str(seed_name)});\n"
                        f"    expect(found, {_ts_str('编辑页未见控件: ' + lab)}"
                        ").toBe(true);\n"
                        "  });")
        for beh in ck.behavior_expectations:
            _emit_text("CHK-BEH", beh, ck.surfaces_of(beh))

    body = "\n".join(blocks)
    return (
        _SPEC_HELPERS
        + "\ntest.describe('compiled acceptance checklist', () => {\n"
        + body + "\n});\n"
    )


def render_ux_checklist(checklists: list[NodeChecklist],
                        max_nodes: int = 48,
                        prefer_ids: list[str] | None = None) -> str:
    """逐节点验收清单 → 开发契约注入段（规格保真度：UX 结构逐字入契约）。

    keep#2 取证死因：锚点清单是摊平的文案集合，模型分不清「哪个词是
    按钮、哪个词是动作后提示、哪个词是种子」——逐节点行保留 GWT 通道
    归属，写码首轮即可按语义对准控件。空事实节点仍出 REQ 行（无引号
    行为约束时代不能再静默丢节点）。截断按未命中/盲区轮换，非文档序前 N。

    v56-2：按 fact_surfaces 写成『首页卡片须含』/『编辑页须含』等位置指令。
    """
    try:
        from app.utils.coverage_rotation import prioritize
        ordered = prioritize(checklists, prefer_ids=prefer_ids,
                             limit=max_nodes)
    except Exception:
        ordered = list(checklists)[:max_nodes]
    lines: list[str] = []

    def _bucket_by_surface(facts: list[str], ck: NodeChecklist
                           ) -> dict[str, list[str]]:
        buckets: dict[str, list[str]] = {}
        for f in facts:
            for surf in ck.surfaces_of(f):
                s = surf if surf != "unknown" else (
                    "home" if ck.home_visible else "unknown")
                buckets.setdefault(s, []).append(f)
        # 去重保序
        for s, lst in list(buckets.items()):
            seen: set[str] = set()
            out: list[str] = []
            for x in lst:
                if x not in seen:
                    seen.add(x)
                    out.append(x)
            buckets[s] = out
        return buckets

    _SURF_LABEL = {
        "home": "首页卡片须含",
        "login": "登录页须含",
        "editor": "编辑页须含",
        "dialog": "对话框须含",
    }

    for ck in ordered:
        parts: list[str] = []
        if ck.control_labels:
            # 刀J'：login 宿主控件进『登录页须含』；其余仍『控件须可见』
            login_ctrls: list[str] = []
            other_ctrls: list[str] = []
            for lab in ck.control_labels[:8]:
                if "login" in (ck.surfaces_of(lab) or []):
                    login_ctrls.append(lab)
                else:
                    other_ctrls.append(lab)
            if other_ctrls:
                parts.append("控件须可见: " + "、".join(
                    f'"{c}"' for c in other_ctrls))
            if login_ctrls:
                parts.append(
                    "登录页须含: " + "、".join(
                        f'"{c}"' for c in login_ctrls[:6]))
        if ck.click_controls:
            parts.append("其中需求要求点击（必须是 <button>/<a href>/勾选框，"
                         "且点下去真有反应——在 <form> 内提交或由页内 JS 监听"
                         "并改变可见状态；正文文字与无行为的占位按钮都不算控件）: "
                         + "、".join(f'"{c}"' for c in ck.click_controls[:6]))
        # v56-2 / 刀J'：behavior 按 surface 分桶写位置指令
        if ck.behavior_expectations:
            by_s = _bucket_by_surface(ck.behavior_expectations[:8], ck)
            positioned = False
            for surf in ("home", "login", "editor", "dialog"):
                items = by_s.get(surf) or []
                if not items:
                    continue
                positioned = True
                already: set[str] = set()
                for p in parts:
                    if p.startswith(_SURF_LABEL.get(surf, "\0")):
                        for m in re.finditer(r'"([^"]+)"', p):
                            already.add(m.group(1))
                items = [x for x in items if x not in already]
                if not items:
                    continue
                parts.append(
                    f"{_SURF_LABEL[surf]}: " + "、".join(
                        f'"{b}"' for b in items[:6]))
            # unknown 桶保留旧口径「动作后须出现」
            unk = by_s.get("unknown") or []
            if unk and not positioned:
                parts.append("动作后须出现: " + "、".join(
                    f'"{b}"' for b in unk[:6]))
            elif unk:
                parts.append("动作后须出现: " + "、".join(
                    f'"{b}"' for b in unk[:4]))
        if ck.behavior_constraints:
            parts.append("行为约束(无引号须实现): " + "；".join(
                ck.behavior_constraints[:4]))
        if ck.seed_entities:
            parts.append("种子可见: " + "、".join(
                f'"{s}"' for s in ck.seed_entities[:8]))
        if not parts:
            parts.append("须实现本条 ATOMIC（场景无引号事实，勿漏行为/流程）")
        lines.append(f"- {ck.req_id} {ck.req_name}｜" + "｜".join(parts))
    if not lines:
        return ""
    return (
        "\n\n【验收节点逐字清单（机械抽取自需求 GWT 结构，逐条满足）】\n"
        "控件/提示/种子文案必须逐字作为对应语义的**可见**元素实现"
        "（按钮=<button>、输入提示=placeholder、动作后反馈=真实渲染的"
        "提示区文本），禁止同义改写；也禁止把文案塞进隐藏位置——"
        "display:none / hidden 元素、HTML 注释、<template> 都算未实现"
        "（评测按渲染后的可见性断言，藏在页面源码里的文案一分不得）。\n"
        "把需求文案铺成一批「既不在 <form> 内、也没有任何脚本/处理器」的"
        "<button> 摆在入口页充数，同样一分不得：评测点下去断言的是变化，"
        "点了不会动的按钮与正文文字等价（验收按「缺接线证据」逐条判红）。\n"
        "「控件须可见」只要求**控件本身**在入口可达页出现；"
        "「首页卡片须含 / 编辑页须含」必须落在对应宿主页（首页列表卡片 /"
        "编辑页），禁止只在错误页面出现一次冒充落地；"
        "「动作后须出现」必须由点击/提交真的触发后才渲染——"
        "把动作后的提示、编辑框、确认项静态铺在页面上凑数，等于交互链"
        "没实现"
        "= 评测按需求顺序操作时依旧落空。\n"
        "「行为约束(无引号须实现)」来自 THEN/GIVEN 整句（刷新后仍在、排序"
        "等），不是引号串——必须做成真交互/持久化，禁止当装饰文案忽略。\n"
        + "\n".join(lines))


def to_json(checklists: list[NodeChecklist]) -> str:
    return json.dumps([c.to_dict() for c in checklists],
                      ensure_ascii=False, indent=1)
