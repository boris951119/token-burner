# -*- coding: utf-8 -*-
"""场景控件清单 → 修环优先级（v44+ P1-B / v45 轮换）。

把 acceptance_compile 的逐字清单压成修环最前的短指令：
缺的是「题面原文控件/种子/无引号行为约束」，不是再发明一套更严断言。
截断按未命中 REQ / 无引号盲区轮换，不再固定文档序前 8。
"""
from __future__ import annotations


def checklist_priority_note(
    requirement: str,
    *,
    max_nodes: int = 8,
    prefer_ids: list[str] | None = None,
) -> str:
    """生成修环优先块；requirement 空或编译失败 → 空串（宁漏不误）。"""
    if not (requirement or "").strip():
        return ""
    try:
        from app.acceptance_compile import (
            compile_checklists_from_text, render_ux_checklist)
        from app.utils.coverage_rotation import prioritize
        checks = compile_checklists_from_text(requirement)
        if not checks:
            return ""
        slim = prioritize(checks, prefer_ids=prefer_ids, limit=max_nodes)
        body = render_ux_checklist(slim, max_nodes=max_nodes,
                                   prefer_ids=prefer_ids)
        if not body.strip():
            lines = [f"- {c.req_id} {c.req_name}" for c in slim]
            body = "【必须落地的原子需求】\n" + "\n".join(lines)
        return (
            "【控件/种子/行为约束清单优先】下列文案与无引号流程约束必须按"
            "原文做成可访问元素或真交互；修环本轮先补清单缺口，禁止整文件"
            "空重写、禁止翻译改写。\n"
            + body.strip()
            + "\n\n"
        )
    except Exception:
        return ""
