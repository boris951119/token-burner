# -*- coding: utf-8 -*-
"""导出首页入口面：题面控件不在 `/` 上时，runner 按需补可见入口。

官方用例从首页进。只有 health、或首页是 JSON/空壳时，100 条会在第一次
定位一起失败。这里只抽出题面里的入口文案，交给启动器在响应里补
<a>，作者页已经含这些文案时不动。
"""
from __future__ import annotations

import json
from pathlib import Path


def entry_anchors(requirement: str, *, limit: int = 12) -> list[str]:
    """题面入口控件/点击文案；没有引号时退回前几条需求名。"""
    if not (requirement or "").strip():
        return []
    out: list[str] = []
    try:
        from app.acceptance_compile import compile_checklists_from_text
        checks = compile_checklists_from_text(requirement)
    except Exception:
        checks = []
    for ck in checks:
        labels = list(getattr(ck, "click_controls", None) or [])
        labels += list(getattr(ck, "control_labels", None) or [])
        # 首页相关的优先；否则只收前几条，避免把后置文案全铺到首页
        if not getattr(ck, "home_visible", False) and len(out) >= 4:
            continue
        for lab in labels:
            lab = str(lab).strip()
            if lab and lab not in out:
                out.append(lab)
            if len(out) >= limit:
                return out
    if len(out) < 3:
        for ck in checks[:8]:
            name = str(getattr(ck, "req_name", "") or "").strip()
            if name and name not in out and len(name) <= 48:
                out.append(name)
            if len(out) >= limit:
                break
    return out[:limit]


def write_entry_spec(backend: Path, anchors: list[str]) -> None:
    backend = Path(backend)
    if not anchors or not backend.is_dir():
        return
    payload = {"anchors": anchors[:12]}
    (backend / "arcbench_entry.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
