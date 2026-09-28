# -*- coding: utf-8 -*-
"""刀 I：node_states 覆盖缺口闸（v55 / INBOX-013）。

交付前零 LLM 对账：compile_checklists 全节点 id 集 vs SDK 已上报
node_states 键集；差集红 → 日志点名 + 缺口 REQ 逐字清单机械追加进
最像模块职责（复用 inject_contracts_by_ownership / _best_plan）+
traceability.requirements 补登记。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_REQ_TOKEN = re.compile(r"\bREQ-[\w.-]+\b", re.I)
_FEATURE_ID = re.compile(r"^REQ-[\w.-]+$", re.I)


@dataclass
class CoverageGapReport:
    required: list[str] = field(default_factory=list)
    reported: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    injected: dict[str, str] = field(default_factory=dict)  # req→module
    registered: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing


def list_sdk_node_state_ids(traceability=None) -> set[str] | None:
    """读 SDK node_states 键集；SDK 不可用返回 None（调用方应跳过闸）。"""
    try:
        if traceability is None:
            from arcbench_agent_runtime import AgentRuntime
            rt = AgentRuntime.from_env()
            traceability = rt.traceability
        rows = traceability.list_node_states() or []
    except Exception:
        return None
    out: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("req_id") or "").strip()
        if rid:
            out.add(rid)
    return out


def audit_node_states_gap(
    requirement: str,
    reported_ids: Iterable[str] | None,
) -> CoverageGapReport:
    """只读对账：清单全节点 vs 已上报键集。"""
    try:
        from app.acceptance_compile import compile_checklists_from_text
        checks = compile_checklists_from_text(requirement or "")
    except Exception:
        checks = []
    required = list(dict.fromkeys(
        str(getattr(c, "req_id", "") or "")
        for c in checks
        if getattr(c, "req_id", None)
    ))
    reported = list(dict.fromkeys(
        str(x).strip() for x in (reported_ids or []) if str(x).strip()
    ))
    rep_set = set(reported)
    missing = [r for r in required if r not in rep_set]
    return CoverageGapReport(
        required=required, reported=reported, missing=missing,
    )


def _assign_gap_owners(
    missing: list[str],
    plans,
    requirement: str,
    owner_hint: dict[str, str] | None = None,
) -> dict[str, str]:
    """缺口 REQ → 最像模块（已有所有权优先，否则 _best_plan）。

    v53.1（批次#82 评审）：与刀G 同口径——UI 流程 REQ（control_labels
    非空）的补挂优先落在 ui/page/web/view 模块，禁止错投 core/data/seed。
    """
    from app.utils.atomic_coverage import (
        _best_plan,
        _ui_flow_req_ids,
        _pick_ui_owner,
    )

    assigned: dict[str, str] = {}
    hint = dict(owner_hint or {})
    ui_reqs = _ui_flow_req_ids(requirement)
    plan_names = {getattr(p, "name", "") for p in (plans or [])}
    for rid in missing:
        if rid in hint and hint[rid] in plan_names:
            assigned[rid] = hint[rid]
            continue
        plan = None
        if rid in ui_reqs:
            plan = _pick_ui_owner(plans, rid, requirement)
        if plan is None and plans:
            plan = _best_plan(plans, rid, requirement)
        if plan is not None:
            assigned[rid] = plan.name
    return assigned


def _persist_plans(project_root: Path | None, plans) -> None:
    if project_root is None or not plans:
        return
    mod_dir = Path(project_root) / "modules"
    try:
        mod_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for plan in plans:
        name = getattr(plan, "name", "") or ""
        if not name:
            continue
        resp = getattr(plan, "responsibility", "") or ""
        deps = getattr(plan, "dependencies", None) or []
        pri = getattr(plan, "priority", 1)
        content = (
            f"# 模块 {name}\n\n"
            f"## 职责\n{resp}\n\n"
            f"## 依赖\n"
            + ("\n".join(f"- {d}" for d in deps) or "无")
            + f"\n\n## 优先级\n{pri}\n"
        )
        try:
            (mod_dir / f"{name}.md").write_text(content, encoding="utf-8")
        except OSError:
            continue


def _register_gap_requirements(
    missing: list[str],
    requirement: str,
    traceability: Any,
) -> list[str]:
    if traceability is None or not missing:
        return []
    try:
        from app.acceptance_compile import compile_checklists_from_text
        by_id = {
            c.req_id: c
            for c in compile_checklists_from_text(requirement or "")
            if getattr(c, "req_id", None)
        }
    except Exception:
        by_id = {}
    done: list[str] = []
    for rid in missing:
        if not _FEATURE_ID.match(rid):
            continue
        ck = by_id.get(rid)
        try:
            traceability.upsert_requirement(
                req_id=rid,
                name=getattr(ck, "req_name", "") or rid if ck else rid,
                description=(
                    f"coverage-gap 补登记（平台树缺口）：{rid}"
                ),
                scenarios=list(getattr(ck, "scenarios", None) or [])
                if ck else None,
            )
            done.append(rid)
        except Exception:
            continue
    return done


def load_plans_from_modules(project_root: Path | None):
    """Phase 0：从 modules/*.md 还原最小 ModulePlan 列表。"""
    if project_root is None:
        return []
    from app.agents.module_builder import ModulePlan

    mod_dir = Path(project_root) / "modules"
    if not mod_dir.is_dir():
        return []
    plans = []
    for path in sorted(mod_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        name = path.stem
        resp = text
        m = re.search(r"##\s*职责\s*\n([\s\S]*?)(?=\n##\s|\Z)", text)
        if m:
            resp = m.group(1).strip()
        plans.append(ModulePlan(
            name=name, responsibility=resp, dependencies=[], priority=1,
        ))
    return plans


def enforce_node_states_gap(
    requirement: str,
    plans=None,
    reported_ids: Iterable[str] | None = None,
    *,
    project_root: Path | str | None = None,
    traceability=None,
    owner_hint: dict[str, str] | None = None,
    skip_if_no_sdk: bool = True,
) -> CoverageGapReport:
    """缺口 >0 → 日志红 + 注入清单 + requirements 补登记。

    reported_ids 为 None 时尝试读 SDK；SDK 不可用且 skip_if_no_sdk
    则返回空报告（本地无 runtime 不误伤）。
    """
    root = Path(project_root) if project_root else None
    if reported_ids is None:
        sdk_ids = list_sdk_node_state_ids(traceability)
        if sdk_ids is None:
            if skip_if_no_sdk:
                return CoverageGapReport()
            reported_ids = []
        else:
            reported_ids = sdk_ids

    report = audit_node_states_gap(requirement, reported_ids)
    if not report.missing:
        return report

    sample = ", ".join(report.missing[:12])
    more = (
        f" …(+{len(report.missing) - 12})"
        if len(report.missing) > 12 else ""
    )
    print(
        f"[coverage-gap] 缺 {len(report.missing)} 个节点上报: "
        f"{sample}{more}",
        flush=True,
    )

    plan_list = list(plans or [])
    if not plan_list and root is not None:
        plan_list = load_plans_from_modules(root)

    assigned = _assign_gap_owners(
        report.missing, plan_list, requirement, owner_hint=owner_hint,
    )
    if plan_list and assigned:
        try:
            from app.acceptance_compile import compile_checklists_from_text
            from app.utils.atomic_coverage import inject_contracts_by_ownership
            checks = [
                c for c in compile_checklists_from_text(requirement or "")
                if getattr(c, "req_id", None) in assigned
            ]
            injected = inject_contracts_by_ownership(
                plan_list, checks, assigned)
            report.injected = {
                rid: mod for rid, mod in assigned.items()
                if injected.get(mod)
            }
            _persist_plans(root, plan_list)
        except Exception as exc:
            print(f"[coverage-gap] 清单注入降级: {exc!r}", flush=True)

    if traceability is None:
        try:
            from arcbench_agent_runtime import AgentRuntime
            traceability = AgentRuntime.from_env().traceability
        except Exception:
            traceability = None
    report.registered = _register_gap_requirements(
        report.missing, requirement, traceability,
    )
    return report
