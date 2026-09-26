# -*- coding: utf-8 -*-
"""收敛后 spec ↔ 题面 REQ 零 LLM 对账（v45 三刀②）。

讨论层只看 FOLDER 摘要拍架构，spec 可能漏点名 ATOMIC。
本闸只统计「spec 正文是否出现每条 REQ id」，缺的落盘并追加进 spec
尾注，让拆分/写码层看得见——不 raise、不拦交付。
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

_REQ_TOKEN = re.compile(r"\bREQ-[\w.-]+\b", re.I)


@dataclass
class SpecReqReport:
    required: list[str] = field(default_factory=list)
    mentioned: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing

    @property
    def ratio(self) -> str:
        n, m = len(self.mentioned), len(self.required)
        return f"{n}/{m}"


def _atomic_ids(requirement: str) -> list[str]:
    try:
        from app.utils.atomic_coverage import _atomic_ids as _ids
        return _ids(requirement)
    except Exception:
        found = []
        for m in re.finditer(r"^###\s+(\S+)", requirement or "", re.M):
            found.append(m.group(1))
        return list(dict.fromkeys(found))


def _ids_in_text(text: str) -> set[str]:
    return {m.group(0) for m in _REQ_TOKEN.finditer(text or "")}


def audit_spec_req_coverage(requirement: str, spec_md: str) -> SpecReqReport:
    required = _atomic_ids(requirement)
    hit = _ids_in_text(spec_md)
    mentioned = [r for r in required if r in hit]
    missing = [r for r in required if r not in hit]
    return SpecReqReport(
        required=required, mentioned=mentioned, missing=missing,
    )


def annotate_spec_with_missing(spec_md: str, report: SpecReqReport) -> str:
    """缺项追加：未点名 ATOMIC 置顶（拆分先看见）+ 尾注留痕；已有对账段则替换。"""
    body = (spec_md or "").rstrip()
    if "【spec↔REQ 对账" in body or "【必须认领的 ATOMIC" in body:
        body = re.split(
            r"\n## 【(?:spec↔REQ 对账|必须认领的 ATOMIC)",
            body, maxsplit=1)[0].rstrip()
        # 也清掉可能落在文首的旧头
        body = re.sub(
            r"^## 【必须认领的 ATOMIC[\s\S]*?\n(?=## |\Z)",
            "", body).rstrip()
    if report.ok:
        note = (
            f"\n\n## 【spec↔REQ 对账 {report.ratio}】\n"
            "题面 ATOMIC 均已在 spec 中点名。\n"
        )
        return body + note
    lines = "\n".join(f"- {rid}" for rid in report.missing)
    header = (
        f"## 【必须认领的 ATOMIC · 缺 {len(report.missing)}/{len(report.required)}】\n"
        "下列 ATOMIC 在收敛 spec 正文中未被点名（讨论层摘要盲区）。"
        "拆分时每个 id 必须有模块主人；写码不得当不存在：\n"
        f"{lines}\n\n"
    )
    note = (
        f"\n\n## 【spec↔REQ 对账 {report.ratio}·缺 {len(report.missing)}】\n"
        "同上清单已置顶，此处留痕供排障。\n"
    )
    return header + body + note


def persist_spec_req_report(
    report: SpecReqReport, sessions: Path,
) -> Path | None:
    try:
        sessions = Path(sessions)
        sessions.mkdir(parents=True, exist_ok=True)
        path = sessions / "spec_req_coverage.json"
        path.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
    except Exception:
        return None


def spec_req_priority_note(report: SpecReqReport | None) -> str:
    if report is None or not report.missing:
        return ""
    return (
        "【spec↔REQ 对账】收敛 spec 未点名、须优先做成真功能："
        + ", ".join(report.missing[:16])
        + "\n\n"
    )
