# -*- coding: utf-8 -*-
"""Playwright 失败现场提取——给修复环看「实际页面长什么样」。

通用交付质量能力：从 error-context.md（或同类文本）里裁出可访问性
树窗口，优先对准失败定位器 / ref= 附近，而不是永远从快照段首截断。
"""
from __future__ import annotations

import re
from pathlib import Path

_SNAPSHOT_MARK = "# Page snapshot"
_REF_IN_SNAP = re.compile(r"\[ref=(e\d+)\]")
_REF_ANY = re.compile(r"\bref=(e\d+)\b", re.I)
# Playwright call log / error 里常见的角色定位器片段
_LOCATOR_HINT = re.compile(
    r"getBy(?:Role|Text|Label|Placeholder|TestId)\([^)\n]{0,200}\)",
    re.I,
)
_DEFAULT_WINDOW = 4000


def _center_slice(text: str, center: int, window: int) -> str:
    if window <= 0 or len(text) <= window:
        return text
    half = window // 2
    start = max(0, center - half)
    end = min(len(text), start + window)
    start = max(0, end - window)
    chunk = text[start:end]
    prefix = "…\n" if start > 0 else ""
    suffix = "\n…" if end < len(text) else ""
    return prefix + chunk + suffix


def extract_page_snapshot_window(
    error_context: str,
    *,
    window: int = _DEFAULT_WINDOW,
) -> str:
    """从一份 Playwright error-context 文本裁出聚焦的 Page snapshot。

    策略：
    1. 定位 ``# Page snapshot`` 段；
    2. 在错误详情里找 ``ref=eN`` 或 getBy* 定位器；
    3. 在快照 YAML 里命中后，以该处为中心取 ``window`` 字符；
    4. 找不到锚点则从快照段首取窗口。
    """
    if not error_context:
        return ""
    mark = error_context.find(_SNAPSHOT_MARK)
    if mark < 0:
        return ""
    pre = error_context[:mark]
    snap = error_context[mark:]
    # 错误区里的 ref= 优先（与快照内 ref 对齐）
    anchors: list[str] = []
    for m in _REF_ANY.finditer(pre):
        anchors.append(m.group(1))
    for m in _LOCATOR_HINT.finditer(pre):
        anchors.append(m.group(0))
    # 去重保序
    seen: set[str] = set()
    ordered: list[str] = []
    for a in anchors:
        if a not in seen:
            seen.add(a)
            ordered.append(a)

    for anchor in ordered:
        needles: list[str] = []
        if anchor.startswith("e") and anchor[1:].isdigit():
            needles.append(f"[ref={anchor}]")
        else:
            # 可见名：引号串、/正则/、name: 后的词
            needles.extend(re.findall(r"['\"]([^'\"]{2,80})['\"]", anchor))
            needles.extend(re.findall(r"/([^/\n]{2,80})/[gimsuy]*", anchor))
            for m in re.finditer(
                    r"name\s*:\s*(?:/([^/]+)/|['\"]([^'\"]+)['\"])",
                    anchor, re.I):
                needles.append(m.group(1) or m.group(2))
            # 过滤角色名噪点
            needles = [n for n in needles
                       if n.lower() not in {
                           "button", "link", "textbox", "searchbox",
                           "heading", "article", "navigation", "main",
                           "banner", "complementary", "dialog", "alert",
                           "status", "option", "checkbox", "radio",
                       }]
            if not needles:
                needles.append(anchor[:80])
        for needle in needles:
            pos = snap.find(needle)
            if pos >= 0:
                return _center_slice(snap, pos, window)
    return snap[:window] if len(snap) > window else snap


def collect_failure_snapshots(
    results_dir: Path,
    *,
    limit: int = 3,
    window: int = _DEFAULT_WINDOW,
    max_age_seconds: float | None = None,
) -> list[str]:
    """扫描 results_dir/*/error-context.md，返回聚焦快照列表。"""
    results_dir = Path(results_dir)
    if not results_dir.is_dir():
        return []
    import time

    cutoff = (time.time() - max_age_seconds) if max_age_seconds else None
    paths = sorted(
        results_dir.glob("*/error-context.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    out: list[str] = []
    for ctx in paths:
        if len(out) >= limit:
            break
        try:
            if cutoff is not None and ctx.stat().st_mtime < cutoff:
                continue
            text = ctx.read_text(encoding="utf-8", errors="replace")
            win = extract_page_snapshot_window(text, window=window)
            if win:
                out.append(win)
        except Exception:
            continue
    return out


def build_repair_issue(
    *,
    headline: str,
    failures: list[str],
    tail: str,
    snapshots: list[str],
    guidance: str,
    fail_fmt=None,
) -> str:
    """组装带失败清单 + 页面快照的修复指令（各轮复用同一形态）。"""
    fmt = fail_fmt or (lambda xs: xs)
    parts = [
        headline.rstrip() + "\n",
        "\n".join(f"- {f}" for f in fmt(failures)),
    ]
    if tail:
        parts.append("\n\n测试输出尾部：\n" + tail)
    if snapshots:
        parts.append(
            "\n\n页面真实快照（失败用例 Playwright 可访问性树，"
            "已按失败定位器附近裁窗）：\n"
            + "\n---\n".join(snapshots)
        )
    if guidance:
        parts.append("\n\n" + guidance.lstrip())
    return "".join(parts)
