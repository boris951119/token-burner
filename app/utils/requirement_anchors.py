# -*- coding: utf-8 -*-
"""需求锚点提取：把需求文本承诺的 UI 事实转成机械可校验的锚点集。

大局观原则（用户指令 09-16）：比赛是过程不是终点——所有机制必须
通用于任意需求，禁止针对见过的题目写特例。本模块只做「需求 → 断言」
的机械转换：需求里承诺什么，就锚定什么。

锚点来源（按置信排序）：
1. 夹具契约字符串（helpers.ts 导出的实体名/值——评测断言的直接来源）；
2. 需求描述中引号内的文案（中英文皆可）；
3. ATOMIC/FOLDER 名称中的英文短语（大写词组，如 "Quick Guide"）。

消费方：旅程闸门的确定性锚点探针（页面 × 锚点覆盖矩阵）与修复
上下文构造器。零 LLM。
"""

from __future__ import annotations

import re
from pathlib import Path

# 引号内文案（英文双/单引号、中文引号）
_QUOTED_RE = re.compile(r"[\"'“”‘’]([^\"'“”‘’]{2,60})[\"'“”‘’]")
# ATOMIC/FOLDER 名称中的连续英文词组（≥2 词或含大写开头专有名词）
_EN_PHRASE_RE = re.compile(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+)\b")
# 夹具文件中导出的字符串字面量（const X = "..." / '...'）
_FIXTURE_STR_RE = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+\w+[^=]*=\s*[^;\n]*?['\"]([^'\"\n]{2,60})['\"]",
    re.IGNORECASE)
# 排除：纯数字、单字符、代码样杂质
_NOISE = re.compile(r"^[0-9+\-*/%<>!=.,;:(){}\[\]]+$")


def _clean(s: str) -> str | None:
    s = s.strip()
    if len(s) < 2 or len(s) > 60 or _NOISE.match(s):
        return None
    return s


def collect_fixture_strings(fixture_hint: str) -> list[str]:
    """夹具契约文本（helpers.ts 原文）→ 精确字符串集。"""
    out: list[str] = []
    for m in _QUOTED_RE.finditer(fixture_hint or ""):
        s = _clean(m.group(1))
        if s:
            out.append(s)
    return out


def collect_anchors_grouped(tree: dict, fixture_hint: str = "") -> dict[str, list[str]]:
    """按顶层 FOLDER 分桶的锚点集（供页面级覆盖探针）。"""
    buckets: dict[str, list[str]] = {"__global__": collect_fixture_strings(fixture_hint)}
    for folder in tree.get("children") or []:
        if folder.get("type") != "FOLDER":
            continue
        fname = folder.get("name") or ""
        bucket = buckets.setdefault(fname, [])
        for m in _QUOTED_RE.finditer(folder.get("description") or ""):
            s = _clean(m.group(1))
            if s and s not in bucket:
                bucket.append(s)
        for atomic in (folder.get("children") or []):
            for m in _QUOTED_RE.finditer(atomic.get("description") or ""):
                s = _clean(m.group(1))
                if s and s not in bucket:
                    bucket.append(s)
            nm = atomic.get("name") or ""
            for m in _EN_PHRASE_RE.finditer(nm):
                s = _clean(m.group(1))
                if s and s not in bucket:
                    bucket.append(s)
    return buckets


def collect_anchors_from_text(requirement: str) -> dict[str, list[str]]:
    """管线需求文本（含夹具契约段）→ {来源段: [锚点]}。

    文本版锚点提取：无需需求树，讨论/拆分/开发任一阶段产出的文本
    都可直接校验。分桶键取自文本中的章节标题（## 后文字）。

    平台 v6 取证（Keep 实跑 112 锚点修不动 → 交付被闸死）：场景描述句
    （"Bug appears when user session expires mid-request"）不是 UI 文案，
    收进来就是不可满足锚点——普通引号串只收 ≤6 词的 UI 形态；
    "Seed data:" 行是评测夹具的逐字断言源，无条件全收。
    """
    buckets: dict[str, list[str]] = {}
    section = "__global__"
    for line in (requirement or "").splitlines():
        s = line.strip()
        if s.startswith("## "):
            section = _clean(s[3:]) or section
            continue
        is_seed = "seed data" in s.lower()
        for m in _QUOTED_RE.finditer(line):
            a = _clean(m.group(1))
            if not a:
                continue
            if not is_seed and len(a.split()) > 6:
                continue  # 场景/条件描述句，非页面可满足文案
            buckets.setdefault(section, [])
            if a not in buckets[section]:
                buckets[section].append(a)
        for m in _EN_PHRASE_RE.finditer(line):
            a = _clean(m.group(1))
            if a and a.lower() not in {"the", "and"}:
                if not is_seed and len(a.split()) > 6:
                    continue
                buckets.setdefault(section, [])
                if a not in buckets[section]:
                    buckets[section].append(a)
    return buckets


def render_anchor_section(buckets: dict[str, list[str]], cap: int = 60) -> str:
    """锚点集 → 注入验收/修复指令的 markdown 段落。"""
    if not buckets:
        return ""
    lines = ["", "## 需求锚点（机械提取自需求树，页面必须原文包含）"]
    for bucket, anchors in buckets.items():
        if not anchors:
            continue
        shown = anchors[:cap]
        lines.append(f"- [{bucket}] {', '.join(repr(a) for a in shown)}")
    return "\n".join(lines) + "\n"


def compute_coverage(pages: dict[str, str],
                     anchors: list[str]) -> dict[str, object]:
    """页面响应 × 锚点覆盖矩阵（纯函数，零 I/O）。

    pages: {页面路径: 响应文本}；anchors: 需求承诺的锚点。
    返回 {"missing": [任何页面都没出现的锚点],
          "where": {锚点: [出现的页面]}}。
    匹配为大小写不敏感的子串包含（评测断言口径近似）。
    """
    where: dict[str, list[str]] = {}
    for a in anchors:
        needle = a.lower()
        hits = [page for page, body in pages.items()
                if needle in (body or "").lower()]
        if hits:
            where[a] = hits
    missing = [a for a in anchors if a not in where]
    return {"missing": missing, "where": where}
