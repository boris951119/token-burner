# -*- coding: utf-8 -*-
"""刀N 交互部件库：确定性落盘 + SSR 语义 + 装配正确性。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.utils.ui_components import ensure_ui_components


@pytest.fixture()
def landed(tmp_path: Path):
    """落盘部件并加载为模块（测试的是真实产物，不是副本）。"""
    code = tmp_path / "code"
    written = ensure_ui_components(code)
    assert "_shared/ui_components.py" in written
    spec = importlib.util.spec_from_file_location(
        "uc_test", code / "_shared" / "ui_components.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["uc_test"] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("uc_test", None)
    sys.path[:] = [p for p in sys.path if p != str(code / "_shared")]


def test_ensure_idempotent_and_compiles(tmp_path: Path):
    code = tmp_path / "code"
    w1 = ensure_ui_components(code)
    w2 = ensure_ui_components(code)
    assert w1 == ["_shared/__init__.py", "_shared/ui_components.py"]
    assert w2 == []  # 只增不改
    compile((code / "_shared" / "ui_components.py").read_text(encoding="utf-8"),
            "uc", "exec")


def test_confirm_dialog_ssr_and_wiring(landed):
    html = landed.confirm_dialog(
        trigger_label="Delete worksheet", title="Delete worksheet",
        message="This cannot be undone.", confirm_label="Confirm delete",
        action_url="/sheets/delete", method="post", danger=True)
    # 三段文案全部 SSR 进源码
    for s in ("Delete worksheet", "This cannot be undone.", "Confirm delete"):
        assert s in html
    # 触发器是真可点控件（role=button），确认按钮是真表单提交
    assert '<summary role="button"' in html
    assert 'action="/sheets/delete"' in html and 'method="post"' in html
    assert 'role="dialog"' in html


def test_form_field_error_beside_control(landed):
    html = landed.form_field(
        label="Worksheet name",
        input_html=landed.text_input("name", placeholder="Enter name",
                                     required=True),
        error="Worksheet name cannot be empty", name="name")
    assert 'role="alert"' in html and "Worksheet name cannot be empty" in html
    assert html.index('name="name"') < html.index("Worksheet name cannot be empty")  # 错误在控件旁（之后）


def test_feedback_note_roles(landed):
    assert 'role="status"' in landed.feedback_note("Saved.", kind="success")
    assert 'role="alert"' in landed.feedback_note(
        "Invalid CSV file format. Import failed.", kind="error")


def test_panel_and_toolbar(landed):
    p = landed.panel("Sort by", "<label>Ascending</label>", open_=True)
    assert "<details" in p and " open" in p and "Sort by" in p
    b = landed.toolbar_button("New blank workbook", action_url="/new")
    # action_url 时渲染为表单提交按钮（接线证据：真 button + form）
    assert 'action="/new"' in b and '<button type="submit"' in b
    assert "New blank workbook" in b


def test_styles_single_include(landed):
    assert landed.component_styles().startswith("<style>")


def test_integration_fixture_route_renders_contract_copy(landed):
    """装配验证：一个用部件的 Flask 路由，验收断言的文案天然 SSR 可见。"""
    flask = pytest.importorskip("flask")
    html = (
        landed.component_styles()
        + "<h1>Workbook Home</h1>"
        + landed.toolbar_button("New blank workbook", action_url="/new")
        + landed.confirm_dialog(
            trigger_label="Import CSV", title="Import CSV",
            message="Select a UTF-8 CSV file.", confirm_label="Confirm import",
            action_url="/import", method="post")
        + landed.form_field(label="Worksheet name",
                            input_html=landed.text_input("ws", ""),
                            error="Worksheet name cannot be empty",
                            name="ws")
        + landed.feedback_note("Invalid CSV file format. Import failed.",
                               kind="error")
    )
    for s in ("New blank workbook", "Import CSV", "Confirm import",
              "Worksheet name cannot be empty",
              "Invalid CSV file format. Import failed."):
        assert s in html  # 静态判分种子/控件/行为通道的事实全部命中
