# -*- coding: utf-8 -*-
"""v45 三刀：无引号行为约束 / spec↔REQ 对账 / 截断轮换。"""
from __future__ import annotations

from app.acceptance_compile import compile_checklists_from_text, render_ux_checklist
from app.utils.coverage_rotation import prioritize, rotate_lines, select_under_budget
from app.utils.spec_req_audit import (
    annotate_spec_with_missing, audit_spec_req_coverage,
)


_SHEETISH = """简介

## 模块：REQ-1 Sheets
### REQ-1-1 Persist After Refresh（验收标准）
Persist rows.
  - 场景：reload
    GIVEN: the workbook editor is open with three rows
    WHEN: the user refreshes the page
    THEN: the three rows still appear in the same order after refresh

### REQ-1-2 Sort Ascending（验收标准）
Sort.
  - 场景：sort
    GIVEN: a sheet with unsorted values
    WHEN: the user applies ascending sort
    THEN: values are sorted in ascending order and remain after save

### REQ-1-3 Quoted Snackbar（验收标准）
Quote path still works.
  - 场景：save
    GIVEN: home page
    WHEN: click "Save"
    THEN: a snackbar shows "Saved"
"""


def test_unquoted_then_becomes_behavior_constraint():
    checks = {c.req_id: c for c in compile_checklists_from_text(_SHEETISH)}
    c1 = checks["REQ-1-1"]
    assert c1.behavior_constraints, "无引号 THEN 必须进行为约束通道"
    assert any("still" in x.lower() or "refresh" in x.lower()
               for x in c1.behavior_constraints)
    assert not c1.behavior_expectations, "无引号不应进引号期望通道"
    c3 = checks["REQ-1-3"]
    assert "Saved" in c3.behavior_expectations
    assert "Save" in c3.control_labels or "Save" in c3.click_controls


def test_render_ux_includes_constraint_channel():
    s = render_ux_checklist(compile_checklists_from_text(_SHEETISH))
    assert "行为约束" in s
    assert "REQ-1-1" in s
    assert "REQ-1-2" in s


def test_spec_req_audit_finds_missing():
    spec = "# Spec\n\nImplement workbook UI and Save snackbar.\nMentions REQ-1-3 only.\n"
    report = audit_spec_req_coverage(_SHEETISH, spec)
    assert "REQ-1-1" in report.missing
    assert "REQ-1-2" in report.missing
    annotated = annotate_spec_with_missing(spec, report)
    assert "spec↔REQ" in annotated
    assert "REQ-1-1" in annotated


def test_spec_req_audit_ok_when_all_named():
    spec = "REQ-1-1 and REQ-1-2 and REQ-1-3 covered."
    report = audit_spec_req_coverage(_SHEETISH, spec)
    assert report.ok
    assert report.ratio == "3/3"


def test_prioritize_puts_blind_nodes_first():
    checks = compile_checklists_from_text(_SHEETISH)
    # 人为只要 1 条：无引号盲区应压过有引号的 REQ-1-3
    slim = prioritize(checks, prefer_ids=[], limit=1)
    assert slim[0].req_id in ("REQ-1-1", "REQ-1-2")


def test_rotate_lines_prefers_unhit_req():
    lines = [f"REQ-{i} miss text" for i in range(1, 30)]
    got = rotate_lines(lines, prefer_ids=["REQ-25", "REQ-28"], limit=5)
    ids = " ".join(got)
    assert "REQ-25" in ids and "REQ-28" in ids


def test_select_under_budget_skips_instead_of_break():
    items = [("A", "x" * 100), ("B", "y" * 100), ("C", "z" * 10)]
    # budget 只能再吃一条小的：旧 break 会在 B 处停、永远不见 C
    picked = select_under_budget(
        items, lambda it: len(it[1]), budget=120,
        prefer_ids=["C"], head_size=0,
    )
    ids = [p[0] for p in picked]
    assert "C" in ids
