# -*- coding: utf-8 -*-
"""failure_context：修复环页面快照裁窗。"""
from __future__ import annotations

from pathlib import Path

from app.utils.failure_context import (
    build_repair_issue,
    collect_failure_snapshots,
    extract_page_snapshot_window,
)

_SAMPLE = """# Error details

```
Error: locator.click: Test timeout of 60000ms exceeded.
Call log:
  - waiting for getByRole('button', { name: /Rename/i })
```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - heading "Workbooks" [level=1] [ref=e2]
  - generic [ref=e3]:
    - article [ref=e4]:
      - link "C1" [ref=e6] [cursor=pointer]
      - generic [ref=e12]:
        - text: Rename workbook
        - textbox [ref=e13]: C1
        - button "Rename" [ref=e14]
""" + ("\n      - filler line keep going\n" * 200) + """
    - article [ref=e99]:
      - button "Far Away" [ref=e100]
```
"""


def test_window_centers_on_failed_control_ref():
    # 错误里没有 ref，但有 Rename 按钮文案 → 应落在 e14 附近，含 ref=e13
    win = extract_page_snapshot_window(_SAMPLE, window=800)
    assert "Page snapshot" in win or "ref=e13" in win or "Rename" in win
    assert "ref=e13" in win or 'button "Rename"' in win
    # 不应只剩段首却丢光失败控件（窗口够大时应含 Rename）
    assert "Rename" in win


def test_window_prefers_ref_from_error_details():
    text = _SAMPLE.replace(
        "waiting for getByRole('button', { name: /Rename/i })",
        "waiting for getByRole('textbox')\n    - locator resolved to ref=e13",
    )
    win = extract_page_snapshot_window(text, window=600)
    assert "ref=e13" in win
    assert "Far Away" not in win or "ref=e13" in win


def test_collect_and_build_issue_keeps_snapshot_label(tmp_path: Path):
    case = tmp_path / "case-1"
    case.mkdir()
    (case / "error-context.md").write_text(_SAMPLE, encoding="utf-8")
    snaps = collect_failure_snapshots(tmp_path, limit=2, window=4000)
    assert snaps and "Page snapshot" in snaps[0]
    assert "ref=e13" in snaps[0]
    issue = build_repair_issue(
        headline="验收仍有失败：",
        failures=["REQ-1 Rename"],
        tail="timeout",
        snapshots=snaps,
        guidance="最小化修改。",
    )
    assert "Page snapshot" in issue
    assert "ref=e13" in issue
    assert "REQ-1 Rename" in issue
