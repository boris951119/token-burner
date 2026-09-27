# -*- coding: utf-8 -*-
"""拆分后 ATOMIC 覆盖表（v44+ P1-A）。

目标：像产品经理开工前核对「每条原子需求都有唯一主人」，堵住
「进了 yaml、没写进任何模块职责」的漏项。

风险护栏（铁律）：
- 只改 ModulePlan.responsibility 文案 / 落盘报告，不 raise、不改交付 exit；
- 覆盖判定认「职责文本里出现 req_id」，再辅以零 LLM 机械补挂；
- 不发明比官方更严的验收，不因覆盖不全拒绝写码（只强制补挂后继续）。
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


_REQ_TOKEN = re.compile(r"\bREQ-[\w.-]+\b", re.I)


@dataclass
class CoverageReport:
    required: list[str] = field(default_factory=list)
    owned: dict[str, str] = field(default_factory=dict)   # req_id → module
    uncovered: list[str] = field(default_factory=list)
    duplicates: dict[str, list[str]] = field(default_factory=dict)
    assigned: dict[str, str] = field(default_factory=dict)  # 机械补挂

    @property
    def ok(self) -> bool:
        return not self.uncovered and not self.duplicates


def _atomic_ids(requirement: str) -> list[str]:
    if not (requirement or "").strip():
        return []
    try:
        from app.acceptance_compile import compile_checklists_from_text
        ids = [c.req_id for c in compile_checklists_from_text(requirement)
               if getattr(c, "req_id", None)]
        if ids:
            return list(dict.fromkeys(ids))
    except Exception:
        pass
    # 退化：直接扫 ### REQ-…
    found = []
    for m in re.finditer(r"^###\s+(\S+)", requirement, re.M):
        found.append(m.group(1))
    return list(dict.fromkeys(found))


def _ids_in_text(text: str) -> set[str]:
    return {m.group(0) for m in _REQ_TOKEN.finditer(text or "")}


def audit_atomic_coverage(requirement: str, plans) -> CoverageReport:
    """只读审计：每条 ATOMIC 是否出现在某个模块职责里。"""
    required = _atomic_ids(requirement)
    owned: dict[str, str] = {}
    dup: dict[str, list[str]] = {}
    for plan in plans or []:
        name = getattr(plan, "name", "") or ""
        hits = _ids_in_text(getattr(plan, "responsibility", "") or "")
        # 也扫模块名（少数拆分把 REQ 写进 name）
        hits |= _ids_in_text(name)
        for rid in hits:
            if rid in owned and owned[rid] != name:
                dup.setdefault(rid, [owned[rid]]).append(name)
            else:
                owned[rid] = name
    # 只关心题面要求的 id（忽略职责里多写的无关 token）
    required_set = set(required)
    owned = {k: v for k, v in owned.items() if k in required_set}
    dup = {k: v for k, v in dup.items() if k in required_set}
    uncovered = [r for r in required if r not in owned]
    return CoverageReport(
        required=required, owned=owned, uncovered=uncovered, duplicates=dup,
    )


def _best_plan(plans, req_id: str, requirement: str):
    """零 LLM：按 FOLDER 段 / 关键词把未覆盖 REQ 挂到最像的模块。"""
    if not plans:
        return None
    # 找该 ATOMIC 所在 ## 模块段标题
    folder_hint = ""
    try:
        from app.acceptance_compile import compile_checklists_from_text
        for c in compile_checklists_from_text(requirement):
            if c.req_id == req_id:
                folder_hint = (c.module_id or "") + " " + (c.req_name or "")
                break
    except Exception:
        folder_hint = req_id

    def score(plan) -> int:
        text = f"{plan.name} {plan.responsibility} {folder_hint}".lower()
        s = 0
        # REQ-1-2-3 → 前缀 REQ-1 / REQ-1-2
        parts = req_id.split("-")
        for i in range(2, len(parts) + 1):
            prefix = "-".join(parts[:i])
            if prefix.lower() in text:
                s += i * 3
        for token in re.findall(r"[a-z]{3,}", folder_hint.lower()):
            if token in text:
                s += 1
        return s

    return max(plans, key=score)


MAX_ATOMICS_PER_MODULE = 3

_COVERAGE_BLOCK = re.compile(
    r"\n\n【覆盖补挂·必须实现】REQ-[\w.-]+[\s\S]*?(?=\n\n【|\Z)",
)
_OWNED_BLOCK = re.compile(
    r"\n\n【本模块 ATOMIC（唯一主人[^\n]*）】\n[\s\S]*?(?=\n\n【|\Z)",
)
_UX_CHECKLIST_BLOCK = re.compile(
    r"\n\n【验收节点逐字清单[^\n]*】\n[\s\S]*?(?=\n\n【|\Z)",
)


def strip_req_tokens(text: str) -> str:
    """去掉责任文里的 REQ 记号与旧补挂块，便于重新唯一分配。"""
    out = text or ""
    out = _COVERAGE_BLOCK.sub("", out)
    out = _OWNED_BLOCK.sub("", out)
    out = _UX_CHECKLIST_BLOCK.sub("", out)
    out = _REQ_TOKEN.sub("", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def inject_contracts_by_ownership(
    plans,
    checklists,
    assigned: dict[str, str] | None,
) -> dict[str, int]:
    """v53 刀C：按 req→模块所有权注入逐节点验收清单（废除单目标整表灌）。

    每个 REQ 的控件/点击/动作后/行为约束/种子块只进认领模块的
    responsibility，接在【本模块 ATOMIC】之后。返回 {模块名: 注入条数}。
    """
    if not plans or not checklists or not assigned:
        return {}
    try:
        from app.acceptance_compile import render_ux_checklist
    except Exception:
        return {}

    by_mod: dict[str, list] = {}
    for ck in checklists:
        rid = getattr(ck, "req_id", "") or ""
        mod = assigned.get(rid)
        if not mod:
            continue
        by_mod.setdefault(mod, []).append(ck)

    plan_by = {getattr(p, "name", ""): p for p in plans}
    counts: dict[str, int] = {}
    for mod, cks in by_mod.items():
        plan = plan_by.get(mod)
        if plan is None:
            continue
        body = render_ux_checklist(list(cks), max_nodes=max(48, len(cks)))
        if not body:
            continue
        resp = _UX_CHECKLIST_BLOCK.sub("", plan.responsibility or "")
        plan.responsibility = resp.rstrip() + body
        counts[mod] = len(cks)
    return counts


def req_ids_in_plan(plan) -> list[str]:
    text = f"{getattr(plan, 'name', '')} {getattr(plan, 'responsibility', '')}"
    return list(_ids_in_text(text))


def validate_split_atomics(requirement: str, plans) -> list[str]:
    """拆分后程序校验；返回问题列表（空=通过）。"""
    problems: list[str] = []
    if not plans:
        return ["模块列表为空"]
    report = audit_atomic_coverage(requirement, plans)
    if report.duplicates:
        problems.append(
            f"重复认领 {len(report.duplicates)} 条 ATOMIC"
            f"（样例 {list(report.duplicates)[:5]}）："
            "禁止把整表 REQ 抄进多个模块")
    for plan in plans:
        n = len(req_ids_in_plan(plan))
        if n > MAX_ATOMICS_PER_MODULE:
            problems.append(
                f"模块 {plan.name} 含 {n} 条 ATOMIC（上限 "
                f"{MAX_ATOMICS_PER_MODULE}）")
    required = report.required
    if required and len(plans) * MAX_ATOMICS_PER_MODULE < len(required):
        need = (len(required) + MAX_ATOMICS_PER_MODULE - 1) // MAX_ATOMICS_PER_MODULE
        problems.append(
            f"模块数 {len(plans)} 不够承接 {len(required)} 条 ATOMIC"
            f"（按每模块≤{MAX_ATOMICS_PER_MODULE} 至少需要 {need} 个模块）")
    return problems


def _sanitize_snippet(owner_rid: str, sn: str) -> str:
    """摘要里常含其它 ### REQ- / ## 模块：REQ- 行，会污染归属计数。"""
    if not sn:
        return ""

    def _keep(m: re.Match) -> str:
        return m.group(0) if m.group(0) == owner_rid else ""

    cleaned = _REQ_TOKEN.sub(_keep, sn)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()[:400]


def _owned_block(
    chunk: list[str],
    *,
    max_per_module: int,
    snippets: dict[str, str] | None = None,
) -> str:
    lines = [
        f"\n\n【本模块 ATOMIC（唯一主人，≤{max_per_module}）】",
        "只实现下列条目；禁止把其他 REQ / 整站页面塞进本文件（防超尺寸冻结）。",
    ]
    for rid in chunk:
        lines.append(f"- {rid}")
        sn = _sanitize_snippet(rid, (snippets or {}).get(rid) or "")
        if sn:
            lines.append(sn)
    return "\n".join(lines) + "\n"


def normalize_atomic_ownership(
    requirement: str,
    plans,
    *,
    max_per_module: int = MAX_ATOMICS_PER_MODULE,
    snippets: dict[str, str] | None = None,
) -> CoverageReport:
    """唯一主人 + 每模块上限；原地改写 plans，必要时追加 overflow 模块。

    6d28：annotate 整表泄漏 → 重复=24 + web_shell 847 行冻结。
    本函数在覆盖补挂之后跑，把职责里的 REQ 清掉再按唯一主人写回。
    """
    if not plans:
        return CoverageReport(required=_atomic_ids(requirement))

    from app.agents.module_builder import ModulePlan

    report = audit_atomic_coverage(requirement, plans)
    required = list(report.required)
    if not required:
        return report

    claimants: dict[str, list[str]] = {rid: [] for rid in required}
    for plan in plans:
        for rid in req_ids_in_plan(plan):
            if rid in claimants and plan.name not in claimants[rid]:
                claimants[rid].append(plan.name)

    owner: dict[str, str] = {}
    for rid in required:
        names = claimants.get(rid) or []
        if names:
            owner[rid] = names[0]
        else:
            plan = _best_plan(plans, rid, requirement) or plans[0]
            owner[rid] = plan.name

    by_mod: dict[str, list[str]] = {}
    for rid, mod in owner.items():
        by_mod.setdefault(mod, []).append(rid)

    for plan in plans:
        plan.responsibility = strip_req_tokens(plan.responsibility or "")

    existing = {p.name for p in plans}
    overflow: list = []
    for mod, reqs in list(by_mod.items()):
        base = next((p for p in plans if p.name == mod), None)
        if base is None:
            continue
        chunks = [
            reqs[i:i + max_per_module]
            for i in range(0, len(reqs), max_per_module)
        ]
        for idx, chunk in enumerate(chunks):
            if idx == 0:
                target = base
            else:
                name = f"{mod}_p{idx + 1}"
                n = 2
                while name in existing:
                    name = f"{mod}_p{idx + 1}_{n}"
                    n += 1
                existing.add(name)
                target = ModulePlan(
                    name=name,
                    responsibility=(
                        f"从 {mod} 拆出的 ATOMIC 分册（防超尺寸）："
                        "只承接下列条目对应的页面/控件，禁止整站堆砌。"
                    ),
                    dependencies=[mod],
                    priority=int(getattr(base, "priority", 1) or 1),
                )
                overflow.append(target)
            target.responsibility = (
                (target.responsibility or "").rstrip()
                + _owned_block(
                    chunk, max_per_module=max_per_module, snippets=snippets)
            )

    plans.extend(overflow)
    final = audit_atomic_coverage(requirement, plans)
    for rid in list(final.uncovered):
        counts = {p.name: len(req_ids_in_plan(p)) for p in plans}
        candidates = [p for p in plans
                      if counts.get(p.name, 0) < max_per_module]
        plan = _best_plan(candidates or plans, rid, requirement) or plans[0]
        if rid not in (plan.responsibility or ""):
            plan.responsibility = (
                (plan.responsibility or "").rstrip()
                + _owned_block(
                    [rid], max_per_module=max_per_module, snippets=snippets)
            )
            final.assigned[rid] = plan.name
    return audit_atomic_coverage(requirement, plans)


def enforce_atomic_coverage(requirement: str, plans) -> CoverageReport:
    """审计 + 补挂 + 唯一主人归一（去重 / 每模块≤3 / 必要时拆册）。"""
    report = audit_atomic_coverage(requirement, plans)
    if not plans:
        return report
    snippets: dict[str, str] = {}
    try:
        from app.utils.selftest_gate import _split_atomic_nodes
        nodes, _ = _split_atomic_nodes(requirement)
        for nid, text in nodes:
            head = "\n".join(text.splitlines()[:8])[:600]
            snippets[nid] = head
    except Exception:
        pass

    still = []
    for rid in list(report.uncovered):
        plan = _best_plan(plans, rid, requirement)
        if plan is None:
            still.append(rid)
            continue
        snippet = snippets.get(rid) or rid
        block = (
            f"\n\n【覆盖补挂·必须实现】{rid}\n"
            f"本模块是该原子需求的唯一主人：验收场景与控件文案必须按原文落地，"
            f"禁止只写占位路由。\n{snippet}\n"
        )
        if rid not in (plan.responsibility or ""):
            plan.responsibility = (plan.responsibility or "") + block
        report.assigned[rid] = plan.name
        report.owned[rid] = plan.name
    report.uncovered = [r for r in report.uncovered if r not in report.assigned]
    report.uncovered = still + report.uncovered
    assigned = dict(report.assigned)
    final = normalize_atomic_ownership(
        requirement, plans, snippets=snippets)
    final.assigned = assigned
    return final


def persist_coverage_report(project_root: Path, report: CoverageReport) -> Path | None:
    """落盘 sessions/atomic_coverage.json，供排障与 resume 可见。"""
    try:
        root = Path(project_root)
        sessions = root / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        path = sessions / "atomic_coverage.json"
        path.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
    except Exception:
        return None


def coverage_priority_note(report: CoverageReport | None) -> str:
    """给修环的优先说明（不阻断交付）。"""
    if report is None:
        return ""
    bits = []
    if report.assigned:
        bits.append(
            "下列原子需求由覆盖闸机械补挂，须优先做成真功能："
            + ", ".join(f"{k}→{v}" for k, v in list(report.assigned.items())[:12])
        )
    if report.uncovered:
        bits.append(
            "仍无主人的原子需求（严重漏项风险）："
            + ", ".join(report.uncovered[:12])
        )
    if report.duplicates:
        bits.append(
            "被多个模块认领（易互相覆盖）："
            + ", ".join(list(report.duplicates)[:8])
        )
    if not bits:
        return ""
    return "【ATOMIC 覆盖闸】" + "；".join(bits) + "\n\n"
