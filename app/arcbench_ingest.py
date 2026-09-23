"""ArcBench 需求树摄取（factory26 参赛适配）。

平台的输入单元是 requirements.yaml 需求树（FOLDER/ATOMIC 两级，
ATOMIC 节点与 Playwright 用例一一对应，见 ARC 仓库 README），而
token-burner 的输入是一句需求文本。本模块负责两者的翻译：

- load_requirement_tree: 定位并解析 requirements.yaml；
- render_requirement_text: 把树渲染成管线需求文本——以 FOLDER 为
  模块划分指令（对齐平台 REQ 节点，traceability 可一一映射），
  ATOMIC 场景作为验收标准原文注入，并声明平台的硬性运行契约
  （PORT 环境变量、/api/health、启动时种子数据初始化）。

测试 fixture 数据（helpers.ts 中的精确字符串）不在 yaml 里——按
ARC 官方流程，生成侧应把同目录 tests/helpers.ts 一并作为上下文，
见 render_requirement_text 的 fixture_hint 参数。
"""

from __future__ import annotations

import re
from pathlib import Path

_REQUIREMENT_NAMES = ("requirements.yaml", "requirements.yml")


def load_requirement_tree(requirement_dir: str | Path) -> tuple[dict, Path]:
    """从目录解析需求树，返回 (tree, yaml_path)；找不到时抛 FileNotFoundError。"""
    base = Path(requirement_dir)
    from app.acceptance_compile import load_yaml_robust
    for name in _REQUIREMENT_NAMES:
        path = base / name
        if path.is_file():
            return load_yaml_robust(path), path
    raise FileNotFoundError(f"{base} 下找不到 requirements.yaml(.yml)")


def _atomic_nodes(node: dict) -> list[dict]:
    out: list[dict] = []
    for child in node.get("children") or []:
        if child.get("type") == "ATOMIC":
            out.append(child)
        else:
            out.extend(_atomic_nodes(child))
    return out


def _root_atomics(tree: dict) -> list[dict]:
    """树根挂的顶层 ATOMIC——官方题面（stackoverflow/prestashop/ctrip）
    把 REQ-0「打开首页」类入口验收放在根级而非 FOLDER 下；旧渲染只走
    FOLDER 分支，这类需求在需求文本/摘要/节点重试/UX 清单四通道全体失踪。"""
    return [c for c in tree.get("children") or [] if c.get("type") == "ATOMIC"]


def count_requirements(tree: dict) -> int:
    """题面原子需求条数（含根级 ATOMIC）——11.0 预算按题面体量折算用这个口径。"""
    return len(_atomic_nodes(tree))


def _render_scenario(atomic: dict) -> str:
    lines: list[str] = []
    for scenario in atomic.get("scenarios") or []:
        lines.append(f"  - 场景：{scenario.get('name', '')}")
        for step in scenario.get("steps") or []:
            lines.append(f"    {step.get('keyword', '')}: {step.get('content', '')}")
    return "\n".join(lines)


def render_folder_summary(tree: dict, *, web_port: int = 3301) -> str:
    """FOLDER 级需求摘要——规模工程（keep1 取证：32 需求全量文本令
    glm-5.3 讨论超墙钟）。讨论阶段吃摘要（架构/职责/模块地图），
    ATOMIC 明细与场景步骤不进入讨论，由拆分与模块开发阶段消费全文。

    实现：渲染全文后截取「简介 + 技术规则 1-16」头部（与全文共用
    同一份规则，永不漂移），再重建 FOLDER 摘要段（职责 + 原子标题
    清单，无场景步骤）；夹具契约原文不进摘要，仅提示其存在。
    """
    full = render_requirement_text(tree, web_port=web_port)
    marker = "功能与验收要求（模块划分必须与下列功能模块一一对应，不要合并、不要增删）："
    head = full.split(marker, 1)[0]

    lines: list[str] = [head, marker]
    folders = [
        child
        for child in tree.get("children") or []
        if child.get("type") == "FOLDER"
    ]
    atomic_total = 0
    root_atomics = _root_atomics(tree)
    if root_atomics:
        atomic_total += len(root_atomics)
        lines.append("")
        lines.append(
            f"## 全局入口验收（根级需求，{len(root_atomics)} 条，不单设模块）"
        )
        for atomic in root_atomics:
            lines.append(f"- {atomic.get('id', '')} {atomic.get('name', '')}")
    for folder in folders:
        atomics = _atomic_nodes(folder)
        atomic_total += len(atomics)
        deps = ", ".join(folder.get("dependencies") or []) or "无"
        desc = (folder.get("description") or "").strip()
        if len(desc) > 400:
            desc = desc[:400] + "…"
        lines.append("")
        lines.append(
            f"## 模块：{folder.get('id', '')} {folder.get('name', '')}"
            f"（{len(atomics)} 条原子需求）"
        )
        lines.append(f"依赖：{deps}")
        lines.append(desc)
        for atomic in atomics:
            lines.append(f"- {atomic.get('id', '')} {atomic.get('name', '')}")
    if atomic_total:
        lines.append("")
        lines.append(
            f"共 {len(folders)} 个功能模块、{atomic_total} 条原子验收需求。"
            "以上为模块地图级摘要；每条原子需求的验收标准原文、场景步骤与"
            "种子夹具契约将在拆分与模块开发阶段提供全文。讨论阶段只做"
            "架构/职责/风险评估，不要展开单条需求的实现细节。"
        )
    return "\n".join(lines)


def render_requirement_text(
    tree: dict,
    *,
    fixture_hint: str = "",
    web_port: int = 3301,
) -> str:
    """需求树 → 管线需求文本（模块划分对齐 FOLDER，验收对齐 ATOMIC）。"""
    lines: list[str] = [
        f"开发一个完整可运行的 Web 应用：{tree.get('name', '')}。",
        (tree.get("description") or "").strip(),
        "",
        "技术栈硬性要求（优先级最高，覆盖任何「避免第三方依赖」的默认倾向）：",
        f"1. 后端必须创建真实 HTTP 服务器（推荐 Flask，或 FastAPI+uvicorn），"
        f"真实监听环境变量 PORT（缺省 {web_port}）——评测从真实浏览器发起访问；",
        "2. 严禁任何形式的 HTTP 模拟：不要写 FakeRequest / 内存请求对象 / "
        "「Server would listen」之类的打印占位——凡是没有真实 socket 监听的实现一律判失败；",
        "3. 暴露 GET /api/health，启动即可访问并返回 200；",
        "4. 前端无需 Node 构建链：由后端托管静态 HTML/CSS/JS（服务端渲染或单页均可），"
        "页面交互用原生 JS 或 CDN 引入的库完成；",
        "5. 允许并建议的第三方导入：flask、fastapi、uvicorn；密码哈希用 werkzeug 或 hashlib；"
        "数据库用 sqlite3（标准库）；",
        "6. 应用启动时初始化数据库并写入种子数据（见下文各模块描述中列明的记录），"
        "种子数据的精确字符串以下文「种子数据与测试夹具契约」为准；"
        "评测起服时是空库：仓库里自带的 .db/.sqlite 文件不算数据源，导出时"
        "会被剥除，一切记录都必须来自启动播种；",
        "7. 每个功能模块必须自带 Flask Blueprint：在模块内定义 "
        "bp = Blueprint('<模块名>', __name__)，把该模块的全部 HTTP 端点"
        "（路由函数）注册在 bp 上——HTTP 接线写在本模块内（此时你对本模块"
        "端点的上下文最完整），严禁把业务模块写成纯服务函数再指望组装模块"
        "凭空推断接线；",
        "8. 应用组装职责并入最后一个功能模块（不单设组装模块）：import "
        "其余模块，逐个 app.register_blueprint(<模块>.bp)——组装因此是"
        "机械动作；同时托管各模块 static/、注册 GET /api/health、提供 "
        "create_app() 与「python -m <该模块名>」启动入口；"
        "该模块的契约 exports 必须声明 create_app（评测方依赖此约定启动）；"
        "组装必须挂载【每一个】业务 Blueprint，漏挂任何模块属于集成失败；",
        "9. 各模块契约的 exports 必须把 bp 与对外路由处理函数声明为公开导出，"
        "避免实现后再改私有化导致与测试互相矛盾；含引号的正则表达式必须用"
        "双引号原始字符串书写（r\"...\"），禁止在单引号原始字符串内出现"
        "未转义的单引号——写完必须能通过语法编译；",
        "10. 运行环境是 Python 3.11（容器里唯一的解释器）：禁止 3.12 才有的语法与"
        "标准库新增符号（如 def f[T](...)、type X = ...、itertools.batched、"
        "datetime.UTC、Path.walk）——这类代码导入即崩，整个交付不评分；"
        "第三方库只用其当前版本仍然存在的公开 API"
        "（如 werkzeug.urls.url_quote）；不确定时改用 Python 标准库等价实现；",
        "11. 必须有一个模块认领「Web 界面」职责：需求点名的每个页面/视图都要"
        "有真实文件承载（入口 index.html，其余页面各一枚，配原生 JS 交互），"
        "放在该模块目录的 static/ 子目录；组装模块必须把各模块的 static/ "
        "内容托管在站点根路径——评测从首页开始沿需求描述的旅程逐页点击，"
        "首页缺少通往任一需求页面的可见入口即失败；",
        "12. 每个页面表单背后必须有对应的 JSON API 端点，且页面 fetch 真实"
        "调用它们（r9 实证：只有页面而无提交端点，评测填完表单即失败）——"
        "需求里每个「创建/更新/删除/查询」动作都要有匹配的端点与状态码语义"
        "（成功 2xx、冲突或校验失败 4xx），成功后页面必须出现可观察的变化"
        "（新行、提示文案、数值变化），严禁只弹提示不落库；",
        "13. 搜索/列表类接口必须真实查询数据库（应用启动时写入的种子数据），"
        "严禁返回硬编码静态列表、内置降级 mock 或任何内存假数据——"
        "模块各自的内置数据必须与 data 模块的种子同源，否则判定集成失败；",
        "14. 全应用必须共用唯一数据库：数据库文件路径必须用 Path(__file__) "
        "锚定（如各模块共同引用 _shared 中的单一路径），严禁 CWD 相对路径"
        "（评测方从任意目录启动服务，相对路径会产生新的空库导致种子丢失）；"
        "禁止任何模块自建独立的 sqlite 文件——多库并存判定集成失败；",
        "15. Flask 应用级钩子（teardown_appcontext/before_request 等）必须"
        "在 create_app() 组装期间、首个请求之前一次性注册（r12 实证：在"
        "请求处理路径里惰性注册 teardown_appcontext，Flask 3 抛 "
        "AssertionError 使该接口 500）——标准模式：_shared 提供 "
        "init_app(app)，create_app() 显式调用；get_db() 只允许使用已注册"
        "的回调，严禁在请求路径上首次注册任何应用级钩子；",
        "16. 任何模块访问数据库只允许通过 _shared 的 get_db()；严禁借用"
        "其他模块的 DB 封装类或连接工具（r12 实证：跨模块借用连接封装，"
        "报错定位错乱）；表结构的唯一权威是种子数据模块的 "
        "DDL——任何模块不得另建同名表、不得假设 DDL 之外的列；"
        "跨模块表结构漂移判定集成失败；",
        "17. 界面元素必须由语义标签承载：评测以可访问性角色+名字定位元素"
        "（getByRole / getByLabel / getByPlaceholder），非语义实现等于不存在"
        "——按钮=<button>（禁 div/span+onclick）、链接=<a href>、单行输入"
        "=<input>（同时给 placeholder 与 <label for>）、多行=<textarea>、"
        "勾选=<input type=checkbox>、下拉=<select>、条目=<article>（条目级"
        "操作按钮必须写在该 <article> 内部：评测先按 article 解析卡片再往"
        "卡内找按钮，用 <li>/div 承载卡片时可见性尚有文本兜底、卡内按钮却"
        "一律找不到，整族交互用例判红）、表格=<table><tr><td>、弹窗=<dialog>"
        "（编辑/详情弹窗须带可访问名：aria-label 或与需求标题一致的 <h*>，"
        "卡内每个输入框各有 label/placeholder）、互斥视图切换按钮带 "
        "aria-pressed=true/false（评测以该属性判定当前态，无属性即红）、"
        "标题=<h1>~<h6>；",
        "18. 需求点名的点击对象还必须是「点下去会有反应」的控件：要么在 "
        "<form> 内提交（<button> 默认即 submit），要么由页内 JS 监听并真实"
        "改变可见状态——评测点击之后断言的是变化，不是元素存在。严禁把需求"
        "里的动作名词抄成一批无行为 <button type='button'> 摆在入口页充数："
        "既不在表单内、又无处理器、整页也没有脚本的按钮等于正文文字，验收"
        "按「缺接线证据」逐条判红，评测则一律 60 秒点击超时（判分红叶实证："
        "此类首页让 29/31 条用例卡死在点击上）；",
        "",
        "功能与验收要求（模块划分必须与下列功能模块一一对应，不要合并、不要增删）：",
    ]

    folders = [
        child
        for child in tree.get("children") or []
        if child.get("type") == "FOLDER"
    ]
    atomic_total = 0
    root_atomics = _root_atomics(tree)
    if root_atomics:
        atomic_total += len(root_atomics)
        lines.append("")
        lines.append(
            "## 全局入口验收（根级需求，不单设模块——"
            "由承担 Web 界面与组装职责的模块认领对应页面与端点）"
        )
        for atomic in root_atomics:
            lines.append("")
            lines.append(
                f"### {atomic.get('id', '')} {atomic.get('name', '')}（验收标准）"
            )
            desc = (atomic.get("description") or "").strip()
            if desc:
                lines.append(desc)
            rendered = _render_scenario(atomic)
            if rendered:
                lines.append(rendered)
    for folder in folders:
        atomics = _atomic_nodes(folder)
        atomic_total += len(atomics)
        deps = ", ".join(folder.get("dependencies") or []) or "无"
        lines.append("")
        lines.append(f"## 模块：{folder.get('id', '')} {folder.get('name', '')}")
        lines.append(f"依赖：{deps}")
        lines.append((folder.get("description") or "").strip())
        for atomic in atomics:
            lines.append("")
            lines.append(
                f"### {atomic.get('id', '')} {atomic.get('name', '')}（验收标准）"
            )
            desc = (atomic.get("description") or "").strip()
            if desc:
                lines.append(desc)
            rendered = _render_scenario(atomic)
            if rendered:
                lines.append(rendered)

    if fixture_hint:
        lines.extend(
            [
                "",
                "## 种子数据与测试夹具契约",
                "端到端测试会以精确字符串断言下列夹具数据：种子数据必须与之吻合，",
                "测试自身创建的记录也使用这些字符串。以下为夹具定义原文：",
                fixture_hint,
            ]
        )

    lines.extend(
        [
            "",
            f"共 {len(folders)} 个功能模块、{atomic_total} 条原子验收需求。"
            "按下列顺序开发，最后一个模块同时承担应用组装（见技术栈要求第 8 条：逐个 register_blueprint）。",
        ]
    )
    return "\n".join(lines)


def locate_fixture(requirement_dir: str | Path) -> Path | None:
    """多布局探测 tests/helpers.ts；返回首个命中路径。

    r4 取证：平台布局是 requirements/ 与 tests/ 兄弟目录，但任务包
    变体可能把 tests/ 放在 requirement_dir 内或与之平铺——放错层级
    时静默返回空会让种子契约整体丢失（搜索/种子数据漂移的根因）。
    """
    base = Path(requirement_dir)
    candidates = (
        base / "tests" / "helpers.ts",
        base.parent / "tests" / "helpers.ts",
        base / "helpers.ts",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


_FIXTURE_HEAD_BUDGET = 8000
_FIXTURE_TAIL_CAP = 4000
_FIXTURE_QUOTED_RE = re.compile(r"[\"'`]([^\"'`\n]{3,80})[\"'`]")


def _fixture_tail_facts(head: str, tail: str) -> str:
    """截断尾段的逐字事实串 → 契约续块（不含则整体丢弃）。

    保留判据＝可见文案形态：含大写 / 含空格 / 含 @（邮箱类种子）/
    含 CJK（中文题面的标签与提示语）；
    剔除 ARIA role、CSS/路径、模板插值、箭头函数等测试机制代码串。"""
    head_strings = set(_FIXTURE_QUOTED_RE.findall(head))
    kept: list[str] = []
    seen: set[str] = set()
    for m in _FIXTURE_QUOTED_RE.finditer(tail):
        s = m.group(1)
        if s in head_strings or s in seen:
            continue
        has_cjk = any("\u4e00" <= c <= "\u9fff" for c in s)
        if (not any(c.isupper() for c in s) and " " not in s
                and "@" not in s and not has_cjk):
            continue
        if "${" in s or "=>" in s or s.startswith(("http", "./", "../", "#", "/")):
            continue
        seen.add(s)
        kept.append(s)
    if not kept:
        return ""
    body = "\n".join(f'- "{k}"' for k in kept)
    if len(body) > _FIXTURE_TAIL_CAP:
        body = body[:_FIXTURE_TAIL_CAP] + "\n- …"
    return (
        "\n\n【夹具截断尾部关键串（承接上文，同为精确断言）】\n" + body
    )


def load_fixture_hint(requirement_dir: str | Path) -> str:
    """读取 tests/helpers.ts 原文作为种子数据契约；不存在返回空串。

    12306 压测取证：原文 10-27KB，旧版整段 [:8000] 令截断点之后的
    逐字 UI 标签（67 条：Passport number / Arrival Time…）从需求文本
    与锚点清单双通道失踪——正是 keep#2「控件级缺口」死因的输入侧形态。
    改法：head 预算不变，尾部逐字串提炼为续块（role/代码噪声过滤）。"""
    located = locate_fixture(requirement_dir)
    if located is None:
        return ""
    raw = located.read_text(encoding="utf-8", errors="replace")
    if len(raw) <= _FIXTURE_HEAD_BUDGET:
        return raw
    head = raw[:_FIXTURE_HEAD_BUDGET]
    return head + _fixture_tail_facts(head, raw[_FIXTURE_HEAD_BUDGET:])
