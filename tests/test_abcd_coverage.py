# -*- coding: utf-8 -*-
"""ATOMIC 覆盖 / 主旅程 / 领域内核 / 清单优先（v44+ ABCD）。"""
from __future__ import annotations

from pathlib import Path

from app.agents.module_builder import ModulePlan
from app.utils.atomic_coverage import (
    MAX_ATOMICS_PER_MODULE,
    audit_atomic_coverage,
    enforce_atomic_coverage,
    req_ids_in_plan,
    validate_split_atomics,
)
from app.utils.checklist_priority import checklist_priority_note
from app.utils.domain_kernels import (
    detect_domains, ensure_domain_kernels,
)
from app.utils.main_journeys import extract_main_journeys, render_main_journeys


_REQ = """简介

## 模块：REQ-1 Workbook Access
### REQ-1-1-1 View and Open a Workbook（验收标准）
Users view workbooks.
  - 场景：open
    GIVEN: home
    WHEN: click
    THEN: editor

## 模块：REQ-2 Worksheets
### REQ-2-1-1 Add a Worksheet（验收标准）
Add sheet.
  - 场景：add
    GIVEN: editor
    WHEN: add
    THEN: tab

### REQ-2-1-2 Switch Worksheets（验收标准）
Switch.
"""


def test_audit_finds_uncovered():
    plans = [ModulePlan(name="ui_home", responsibility="home page only",
                        dependencies=[], priority=1)]
    report = audit_atomic_coverage(_REQ, plans)
    assert set(report.required) >= {"REQ-1-1-1", "REQ-2-1-1", "REQ-2-1-2"}
    assert "REQ-1-1-1" in report.uncovered


def test_enforce_assigns_uncovered_into_plans():
    plans = [
        ModulePlan(name="workbook_ui", responsibility="workbook list",
                   dependencies=[], priority=1),
        ModulePlan(name="worksheet_ui", responsibility="worksheet tabs",
                   dependencies=[], priority=2),
    ]
    report = enforce_atomic_coverage(_REQ, plans)
    assert not report.uncovered, report
    assert not report.duplicates, report.duplicates
    owned_text = " ".join(p.responsibility for p in plans)
    assert "REQ-1-1-1" in owned_text and "REQ-2-1-1" in owned_text
    for plan in plans:
        assert len(req_ids_in_plan(plan)) <= MAX_ATOMICS_PER_MODULE, plan.name


def test_normalize_dedupes_and_splits_overflow():
    """整表抄进多模块 → 唯一主人 + 超限拆册。"""
    dump = (
        "全站 UI\nREQ-1-1-1 REQ-2-1-1 REQ-2-1-2 "
        "REQ-3-1-1 REQ-3-1-2 REQ-3-1-3 REQ-3-1-4"
    )
    # 扩展题面到 7 条，逼出 overflow
    req = _REQ + """
## 模块：REQ-3 Extra
### REQ-3-1-1 A（验收标准）
a
### REQ-3-1-2 B（验收标准）
b
### REQ-3-1-3 C（验收标准）
c
### REQ-3-1-4 D（验收标准）
d
"""
    plans = [
        ModulePlan(name="web_shell", responsibility=dump,
                   dependencies=[], priority=1),
        ModulePlan(name="web_shell_copy", responsibility=dump,
                   dependencies=[], priority=2),
    ]
    report = enforce_atomic_coverage(req, plans)
    assert not report.uncovered, report
    assert not report.duplicates, report.duplicates
    assert any(p.name.startswith("web_shell_p") for p in plans)
    for plan in plans:
        n = len(req_ids_in_plan(plan))
        assert n <= MAX_ATOMICS_PER_MODULE, (plan.name, n)


def test_validate_split_rejects_dup_and_oversize():
    dump = "REQ-1-1-1 REQ-2-1-1 REQ-2-1-2"
    plans = [
        ModulePlan(name="a", responsibility=dump, dependencies=[], priority=1),
        ModulePlan(name="b", responsibility=dump, dependencies=[], priority=2),
    ]
    problems = validate_split_atomics(_REQ, plans)
    assert problems
    assert any("重复" in p or "上限" in p or "3" in p for p in problems)


def test_annotate_no_full_req_bullet_dump():
    from app.utils.spec_req_audit import (
        annotate_spec_with_missing, SpecReqReport,
    )
    missing = [f"REQ-{i}" for i in range(1, 25)]
    report = SpecReqReport(
        required=missing, mentioned=[], missing=missing,
    )
    out = annotate_spec_with_missing("# Spec\n\nbody only\n", report)
    assert "必须认领的 ATOMIC" in out
    assert "spec_req_coverage.json" in out
    assert out.count("\n- REQ-") == 0
    assert "body only" in out


def test_main_journeys_extracted():
    journeys = extract_main_journeys(_REQ)
    assert journeys
    text = render_main_journeys(_REQ)
    assert "主旅程" in text
    assert "REQ-1-1-1" in text


def test_checklist_priority_note_nonempty():
    note = checklist_priority_note(_REQ)
    assert "控件" in note or "REQ-1-1-1" in note


def test_domain_kernels_formula_only_once(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    req = "Online Spreadsheet workbook worksheet formula pivot CSV"
    w1 = ensure_domain_kernels(code, req)
    assert any("formula_kernel" in x for x in w1)
    w2 = ensure_domain_kernels(code, req)
    assert w2 == [], "第二次不得覆盖"
    src = (code / "_shared" / "formula_kernel.py").read_text(encoding="utf-8")
    assert "__arcbench_domain_kernel__" in src
    # 真能求值
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "fk", code / "_shared" / "formula_kernel.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    grid = {"A1": 2, "B1": 3}
    assert mod.evaluate("=A1+B1", grid.get) == 5.0


def test_domain_detect_session():
    assert "session" in detect_domains(
        "Sign in with password and create a pull request repository")
