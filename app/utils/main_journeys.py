# -*- coding: utf-8 -*-
"""主旅程摘要（v44+ P1-C）。

从需求树抽出 3–5 条跨模块主旅程，置顶注入旅程验收 brief——
逼「串起来用」，而不是只堆独立页面。

风险护栏：
- 纯确定性（FOLDER/ATOMIC 标题），零 LLM；
- 只作摘要优先级，不另立比官方更严的断言；
- 旅程 FAIL 仍走既有「照常交付」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class MainJourney:
    title: str
    steps: list[str]  # ATOMIC id + name


def extract_main_journeys(requirement: str, *, max_journeys: int = 5,
                          max_steps: int = 4) -> list[MainJourney]:
    """FOLDER 一级下各取若干 ATOMIC，组成主旅程。"""
    if not (requirement or "").strip():
        return []
    journeys: list[MainJourney] = []
    current_folder: str | None = None
    steps: list[str] = []

    def flush() -> None:
        nonlocal steps, current_folder
        if current_folder and steps:
            journeys.append(MainJourney(
                title=current_folder, steps=steps[:max_steps]))
        steps = []

    for line in requirement.splitlines():
        m_folder = re.match(r"^##\s+模块：\s*(\S+)\s+(.*)$", line)
        if m_folder:
            # 只把顶层 REQ-N（无更深连字符）当主旅程容器；更深 FOLDER 并进当前
            fid = m_folder.group(1)
            fname = m_folder.group(2).strip()
            depth = fid.count("-")
            if depth <= 1:  # ROOT 下的 REQ-1 / REQ-1-1 都可；优先 depth==1 新开
                if depth == 1 or current_folder is None:
                    flush()
                    current_folder = f"{fid} {fname}".strip()
            continue
        m_atomic = re.match(r"^###\s+(\S+)\s+(.*?)（验收标准）\s*$", line)
        if not m_atomic:
            m_atomic = re.match(r"^###\s+(\S+)\s+(.*)$", line)
        if m_atomic and current_folder:
            rid, name = m_atomic.group(1), m_atomic.group(2).strip()
            if name.endswith("（验收标准）"):
                name = name[: -len("（验收标准）")].strip()
            steps.append(f"{rid} {name}")
            if len(steps) >= max_steps:
                flush()
                current_folder = None
    flush()
    return journeys[:max_journeys]


def render_main_journeys(requirement: str) -> str:
    journeys = extract_main_journeys(requirement)
    if not journeys:
        return ""
    lines = [
        "【主旅程（跨模块必须串起来，优先于单页点缀）】",
        "评测从首页进入；下列每条旅程要有可达入口与真实状态变化，"
        "禁止只做互不连通的孤立页面。",
    ]
    for i, j in enumerate(journeys, 1):
        lines.append(f"{i}. {j.title}")
        for s in j.steps:
            lines.append(f"   - {s}")
    return "\n".join(lines) + "\n\n"
