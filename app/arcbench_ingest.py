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

from pathlib import Path

import yaml

_REQUIREMENT_NAMES = ("requirements.yaml", "requirements.yml")


def load_requirement_tree(requirement_dir: str | Path) -> tuple[dict, Path]:
    """从目录解析需求树，返回 (tree, yaml_path)；找不到时抛 FileNotFoundError。"""
    base = Path(requirement_dir)
    for name in _REQUIREMENT_NAMES:
        path = base / name
        if path.is_file():
            with open(path, encoding="utf-8") as fh:
                return yaml.safe_load(fh), path
    raise FileNotFoundError(f"{base} 下找不到 requirements.yaml(.yml)")


def _atomic_nodes(node: dict) -> list[dict]:
    out: list[dict] = []
    for child in node.get("children") or []:
        if child.get("type") == "ATOMIC":
            out.append(child)
        else:
            out.extend(_atomic_nodes(child))
    return out


def _render_scenario(atomic: dict) -> str:
    lines: list[str] = []
    for scenario in atomic.get("scenarios") or []:
        lines.append(f"  - 场景：{scenario.get('name', '')}")
        for step in scenario.get("steps") or []:
            lines.append(f"    {step.get('keyword', '')}: {step.get('content', '')}")
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
        "种子数据的精确字符串以下文「种子数据与测试夹具契约」为准；",
        "7. 应用组装职责并入最后一个功能模块（不单设组装模块）：该模块内 import "
        "其余模块的路由/处理函数，注册到同一个 Flask/FastAPI app，并提供 "
        "create_app() 与「python -m <该模块名>」可直接启动的入口；"
        "该模块的契约 exports 必须声明 create_app（评测方依赖此约定启动应用）；"
        "组装时必须把【每一个】功能模块的能力都暴露为真实 HTTP 路由"
        "（命名 /api/<能力名>，如注册 /api/auth/register、搜索 /api/search），"
        "并注册 GET /api/health——只组装最后一个模块、漏掉其他模块的路由"
        "属于集成失败；",
        "8. 各模块契约的 exports 必须把对外 HTTP 处理函数（路由处理函数）声明为公开导出，"
        "避免实现后再改私有化导致与测试互相矛盾。",
        "9. 含引号的正则表达式必须用双引号原始字符串书写（r\"...\"），"
        "禁止在单引号原始字符串内出现未转义的单引号——写完必须能通过语法编译；",
        "10. 第三方库只用其当前版本仍然存在的公开 API——禁止使用已在新版移除的符号"
        "（如 werkzeug.urls.url_quote）；不确定时改用 Python 标准库等价实现；",
        "11. 必须有一个模块认领「Web 界面」职责：生成完整的静态站点文件"
        "（index.html + 注册/登录/搜索/订票页面 + 原生 JS），放在该模块目录的 "
        "static/ 子目录；组装模块必须把各模块的 static/ 内容托管在站点根路径——"
        "评测从首页开始走完整用户旅程（首页可见 Register/Login 链接 → "
        "注册 → 登录 → 搜索 → 选车次 → 提交订单），缺任何页面或链接即失败；",
        "12. 页面表单用 fetch 调上述 /api/* 路由完成真实交互："
        "注册/登录后页面显示用户名与 Sign out 链接，搜索后展示车次结果列表，"
        "可选车次进入订票页提交乘客信息；",
        "13. 搜索/列表类接口必须真实查询数据库（应用启动时写入的种子数据），"
        "严禁返回硬编码静态列表、内置降级 mock 或任何内存假数据——"
        "模块各自的内置数据必须与 data 模块的种子同源，否则判定集成失败；",
        "",
        "功能与验收要求（模块划分必须与下列功能模块一一对应，不要合并、不要增删）：",
    ]

    folders = [
        child
        for child in tree.get("children") or []
        if child.get("type") == "FOLDER"
    ]
    atomic_total = 0
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
            "按下列顺序开发，最后一个模块同时承担应用组装（见技术栈要求第 7 条）。",
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


def load_fixture_hint(requirement_dir: str | Path) -> str:
    """读取 tests/helpers.ts 原文作为种子数据契约；不存在返回空串。"""
    located = locate_fixture(requirement_dir)
    if located is None:
        return ""
    return located.read_text(encoding="utf-8", errors="replace")[:8000]
