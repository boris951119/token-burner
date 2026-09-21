# -*- coding: utf-8 -*-
"""种子声明契约提取与审计（零 LLM，机械抽取）。

9/21 keep 冷启动取证：官方 requirements.yaml 每个需求节点带逐字种子
声明（`Seed data: pinned note "Sprint goals" and regular note
"Groceries".`），生成器无视之、LLM 自编种子（实种出 "Call dentist
existing"/"st" 等脏数据），官方测试按声明名断言 → REQ-2.x 簇 16 项
连环落空。锚点系统（requirement_anchors）只管「页面呈现」，种子必须
先「入库」——本模块补齐前半段：

1. extract_seed_declarations: 需求文本 → [(需求节点, [逐字种子名])]，
   机械抽取禁改写；
2. inject_seed_contract: 命中数据层模块则把种子名单硬契约注入其
   responsibility（同 inject_ui_manifest 打法：决策归 LLM，名单归程序）；
3. audit_seeds: 生成后确定性审计——每个声明名必须在代码中字面出现，
   缺失项即精确修复工单（不依赖 LLM 猜测）。

判据（Qoder 交叉审查 9/21）：把题目换成任何域这条规则仍成立——
「需求声明的夹具数据必须逐字落库」是通用软件工程不变量。
"""
from __future__ import annotations

import re
from pathlib import Path

# 种子行：含 "Seed data:"（大小写不敏感）；名字 = 行内引号串
_SEED_LINE = re.compile(r"seed\s*data\s*:", re.I)
_QUOTED = re.compile(r"[\"']([^\"'\n]{1,120})[\"']")
# 章节标题里的需求 id（## REQ-2.1 ...）
_HEADING = re.compile(r"^#{1,6}\s*(REQ-[\d.]+[^:\n]{0,80})")
# 引用图片不是种子
_NOT_SEED = re.compile(r"\.(png|jpe?g|gif|svg|webp)$", re.I)


def extract_seed_declarations(requirement: str) -> list[tuple[str, list[str]]]:
    """需求文本 → [(需求节点标题, [逐字种子名...])]，顺序保持、去重。

    9/22 首版取证：YAML description 整行被单引号包裹（'...Seed data:
    "X"...'），整行抽引号会把外层 description 抓成一个"名字"——
    必须先定位 Seed data: 之后取子串再抽引号。
    """
    out: list[tuple[str, list[str]]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    section = "__global__"
    for line in (requirement or "").splitlines():
        s = line.strip()
        h = _HEADING.match(s)
        if h:
            section = h.group(1).strip()
            continue
        m = _SEED_LINE.search(s)
        if not m:
            continue
        rest = s[m.end():]          # Seed data: 之后才是种子名
        names: list[str] = []
        for q in _QUOTED.finditer(rest):
            n = q.group(1).strip()
            if not n or _NOT_SEED.search(n) or n in names:
                continue
            if _SEED_LINE.search(n) or len(n.split()) > 12:
                continue            # 外层残渣/描述句，不是名字
            names.append(n)
        if not names:
            continue
        key = (section, tuple(names))
        if key not in seen:
            seen.add(key)
            out.append((section, names))
    return out


def seed_names(requirement: str) -> list[str]:
    """全部种子名的扁平去重清单（保序）。"""
    flat: list[str] = []
    for _, names in extract_seed_declarations(requirement):
        for n in names:
            if n not in flat:
                flat.append(n)
    return flat


_DATA_HINT = re.compile(
    r"data|db|database|store|storage|seed|model|persist|repo|dao", re.I)


def _pick_data_module(plans: list):
    """数据层模块：名字或职责最像数据层的那个；找不到返回 None。"""
    best, best_score = None, 0
    for p in plans:
        score = 2 * len(_DATA_HINT.findall(p.name or ""))
        score += len(_DATA_HINT.findall(getattr(p, "responsibility", "") or ""))
        if score > best_score:
            best, best_score = p, score
    return best if best_score > 0 else None


def render_seed_contract(requirement: str) -> str | None:
    """种子名单 → 硬契约段落（逐字实现，禁改写禁删减）。"""
    decls = extract_seed_declarations(requirement)
    if not decls:
        return None
    lines = [
        "\n\n【种子数据硬契约（机械提取自需求原文，逐字落库——评测按这些",
        "名字断言，改名/漏种 = 对应用例直接落空）】",
    ]
    for section, names in decls:
        lines.append(f"- {section}: {'; '.join(repr(n) for n in names)}")
    lines.append("- 以上名字必须原样出现在种子/初始化数据中（含大小写与")
    lines.append("  空格）；需求未声明的数据可自行补充但不得顶替声明项。")
    return "\n".join(lines)


def inject_seed_contract(plans: list, requirement: str) -> str | None:
    """把种子硬契约注入数据层模块的 responsibility，返回注入目标名。"""
    contract = render_seed_contract(requirement)
    if not contract:
        return None
    target = _pick_data_module(plans)
    if target is None:
        return None
    target.responsibility += contract
    return target.name


def audit_seeds(code_dir: Path, requirement: str) -> list[str]:
    """生成后审计：每个声明名必须在 code_dir 的代码中字面出现。

    返回缺失清单（人类可读，供修复指令直接引用）；空 = 全部落库或
    需求无种子声明。只查字面（种子通常以字符串字面量写入 seed/DDL），
    动态构造的种子不在静态比对射程内。
    """
    names = seed_names(requirement)
    if not names:
        return []
    corpus_parts: list[str] = []
    for py in sorted(Path(code_dir).rglob("*.py")):
        try:
            corpus_parts.append(py.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    corpus = "\n".join(corpus_parts)
    missing = [n for n in names if n not in corpus]
    if not missing:
        return []
    return [
        f"需求声明的种子数据 {n!r} 未在任何代码中落库（Seed data 逐字"
        f"契约：缺失即对应评测用例直接落空，必须补进种子/初始化数据）"
        for n in missing
    ]
