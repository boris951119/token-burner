# -*- coding: utf-8 -*-
"""交互部件库（刀N，UI Components）：标准交互零件的确定性落盘。

依据（09-30 残余失败聚类）：v58 一次生成后浏览器层残余 119 项失败，
~90% 集中在 6-8 类标准交互部件（确认对话框 24、表单校验反馈、操作
反馈提示 64、功能面板族 25、工具栏按钮）。模型每次现场发明这些部件
错 7 成；给标准零件（SSR 优先、内建触发逻辑与渲染位置），装配即正确。

落盘模式与 domain_kernels 同款：确定性写入 code/_shared/ui_components.py，
只增不改；模型经既有 _shared_context 机制（M4-3，写码提示自动携带
code/_shared 全文）看到 API，import 使用。

部件设计原则：
- **SSR 优先**：全部文案在服务端渲染进 HTML 源（官方按响应体可见性
  断言；JS 常量/API 返回必判红——81bc 死因）；
- **零 JS 依赖**：对话框用 <details> 原生开合，进度增强不引第三方；
- **接线自证**：触发器是真 <summary role="button">/表单提交，判分
  点击通道（getByRole button）与接线证据双通道天然命中；
- **行为文案内建**：校验错误 role="alert" 落在字段旁，操作反馈
  role="status" 落在触发处——位置由部件保证，不由模型自觉。
"""
from __future__ import annotations

from pathlib import Path

_COMPONENTS_MODULE = '''\
# -*- coding: utf-8 -*-
"""交互部件库（token-burner ui components，可被业务模块 import）。

__arcbench_ui_components__ = True
标准交互零件：确认对话框 / 表单校验反馈 / 操作反馈 / 功能面板 / 工具栏。
全部服务端渲染（SSR）——验收按"响应体直接包含文案"断言，禁止 JS 常量。
用法：from _shared.ui_components import confirm_dialog, form_field, ...
页面 <head> 里放一次 component_styles()。
"""

from __future__ import annotations

import html as _html

__arcbench_ui_components__ = "interaction"


def _e(text) -> str:
    return _html.escape(str(text if text is not None else ""), quote=True)


def component_styles() -> str:
    """页面 <head> 引入一次的部件样式（作用域 uc- 前缀，零依赖）。"""
    return (
        "<style>"
        ".uc-btn{display:inline-block;padding:6px 14px;border:1px solid #2563eb;"
        "border-radius:6px;background:#fff;color:#2563eb;cursor:pointer;"
        "font:inherit;text-decoration:none}"
        ".uc-btn.danger{border-color:#b91c1c;color:#b91c1c}"
        ".uc-dialog{position:relative}"
        ".uc-dialog>.uc-dialog-body{position:absolute;z-index:10;min-width:280px;"
        "border:1px solid #94a3b8;border-radius:8px;background:#fff;padding:14px;"
        "box-shadow:0 8px 24px rgba(15,23,42,.18)}"
        ".uc-dialog[open]>.uc-dialog-body{display:block}"
        ".uc-field{display:block;margin:8px 0}"
        ".uc-field>.uc-label{display:block;font-weight:600;margin-bottom:4px}"
        ".uc-error{color:#b91c1c;margin:4px 0 0}"
        ".uc-note{padding:8px 12px;border-radius:6px;margin:8px 0}"
        ".uc-note.success{background:#ecfdf5;color:#065f46}"
        ".uc-note.error{background:#fef2f2;color:#b91c1c}"
        ".uc-note.info{background:#eff6ff;color:#1e40af}"
        ".uc-panel{border:1px solid #cbd5e1;border-radius:8px;margin:8px 0}"
        ".uc-panel>summary{cursor:pointer;padding:8px 12px;font-weight:600}"
        ".uc-panel>.uc-panel-body{padding:10px 12px;border-top:1px solid #e2e8f0}"
        "</style>"
    )


def toolbar_button(label, action_url="", name="", danger=False, method="get"):
    """工具栏/页面按钮。action_url 非空时渲染为真链接（GET 表单语义），
    否则为提交类按钮（置于 <form> 内由调用方决定提交目标）。"""
    cls = "uc-btn danger" if danger else "uc-btn"
    label_html = _e(label)
    name_attr = f' name="{_e(name)}"' if name else ""
    if action_url:
        m = "post" if str(method).lower() == "post" else "get"
        return (f'<form action="{_e(action_url)}" method="{m}" '
                f'class="uc-inline-form">'
                f'<button type="submit" class="{cls}"{name_attr}>'
                f"{label_html}</button></form>")
    return f'<button type="button" class="{cls}"{name_attr}>{label_html}</button>'


def confirm_dialog(trigger_label, title, message, confirm_label, action_url,
                   method="post", danger=False, extra_fields=""):
    """确认对话框：<details> 原生开合，零 JS。

    标题/说明/确认按钮文案全部 SSR；确认按钮为真表单提交（接线自证）。
    extra_fields：对话框内附加表单控件 HTML（如重命名的新名输入框）。
    """
    cls = "uc-btn danger" if danger else "uc-btn"
    return (
        f'<details class="uc-dialog">'
        f'<summary role="button" class="{cls}">{_e(trigger_label)}</summary>'
        f'<div class="uc-dialog-body" role="dialog" aria-label="{_e(title)}">'
        f"<h3>{_e(title)}</h3><p>{_e(message)}</p>"
        f'<form action="{_e(action_url)}" method="{_e(method)}">'
        f"{extra_fields}"
        f'<button type="submit" class="{cls}">{_e(confirm_label)}</button>'
        f"</form></div></details>"
    )


def form_field(label, input_html, error="", name=""):
    """表单字段：label + 控件 + 校验错误槽（错误必须落在字段旁）。"""
    name_attr = f' for="f-{_e(name)}"' if name else ""
    err = (f'<p class="uc-error" role="alert">{_e(error)}</p>'
           if error else "")
    return (f'<label class="uc-field"{name_attr}>'
            f'<span class="uc-label">{_e(label)}</span>'
            f"{input_html}{err}</label>")


def text_input(name, value="", placeholder="", required=False):
    req = " required" if required else ""
    val = f' value="{_e(value)}"' if value != "" else ""
    return (f'<input id="f-{_e(name)}" name="{_e(name)}" type="text"'
            f'{val} placeholder="{_e(placeholder)}"{req}>')


def feedback_note(text, kind="info"):
    """操作反馈提示：kind=success|error|info。动作完成后渲染在触发处。"""
    role = "alert" if kind == "error" else "status"
    return (f'<p class="uc-note { _e(kind) }" role="{role}">'
            f"{_e(text)}</p>")


def panel(title, body_html, open_=False):
    """功能面板（排序/筛选/校验规则/透视编辑器等的标准容器）。"""
    open_attr = " open" if open_ else ""
    return (f'<details class="uc-panel"{open_attr}>'
            f"<summary>{_e(title)}</summary>"
            f'<div class="uc-panel-body">{body_html}</div></details>')
'''


def ensure_ui_components(code_dir: Path) -> list[str]:
    """在 code/_shared/ 落下交互部件库；已存在则跳过（只增不改）。

    返回写入的相对路径列表。落盘后 __arcbench_ui_components__ 标记
    与 compile 语法自证由测试与调用方复核。
    """
    code_dir = Path(code_dir)
    shared = code_dir / "_shared"
    shared.mkdir(parents=True, exist_ok=True)
    init = shared / "__init__.py"
    written: list[str] = []
    if not init.is_file():
        init.write_text('"""共享层（含 domain kernel 与 ui components）。"""\n',
                        encoding="utf-8")
        written.append("_shared/__init__.py")
    target = shared / "ui_components.py"
    if not target.is_file():
        target.write_text(_COMPONENTS_MODULE, encoding="utf-8")
        written.append("_shared/ui_components.py")
    compile(target.read_text(encoding="utf-8"), "ui_components", "exec")
    return written
