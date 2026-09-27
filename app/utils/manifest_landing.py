# -*- coding: utf-8 -*-
"""写码门禁：模块契约锚点文案落地检查（v53 刀H）。

病灶（github d462 / .tmp/v53-github）：ui_home.md 契约含
"Create an account" 等字面量，生成的 ui_home.py 0 处实现，模型用
幻觉 GitHub chrome 填充——契约在场但无机械拦截。

规则：从模块职责/契约提取锚点文案；条数 ≥ MIN_ANCHORS 时，
源码出现率 < HIT_RATIO → 门禁红，重写指令逐条列出缺失文案。
"""
from __future__ import annotations

import re

MIN_ANCHORS = 4
HIT_RATIO = 0.5

# 验收清单 / 职责里的引号串
_QUOTED = re.compile(r"[\"“]([^\"”]{2,60})[\"”]")
# 顿号/逗号分隔短语（清单体）
_SPLIT = re.compile(r"[、,/|]")

_NOISE = re.compile(
    r"^(?:button|Flask Blueprint|JSON API|__global__|"
    r"account|session)$",
    re.I,
)


def extract_manifest_anchors(responsibility: str) -> list[str]:
    """从模块职责文本抽锚点文案（保序去重）。"""
    text = responsibility or ""
    out: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        s = (raw or "").strip().strip("·•- ")
        if len(s) < 2 or len(s) > 60:
            return
        if _NOISE.match(s):
            return
        if s in seen:
            return
        seen.add(s)
        out.append(s)

    # 1) 硬契约清单行（顿号枚举）
    in_manifest = False
    for line in text.splitlines():
        if "【UI 页面与文案清单" in line or "硬契约" in line and "文案" in line:
            in_manifest = True
            continue
        if in_manifest and line.startswith("【"):
            in_manifest = False
        if not in_manifest:
            continue
        body = line.strip()
        if body.startswith("-") or body.startswith("*"):
            # "- section: a、b、c" 或 "- a、b"
            if ":" in body:
                body = body.split(":", 1)[1]
            else:
                body = body.lstrip("-* ").strip()
            for part in _SPLIT.split(body):
                _add(part)

    # 2) 验收节点 / 职责里的引号文案（控件须可见 等）
    for m in _QUOTED.finditer(text):
        _add(m.group(1))

    return out


def check_manifest_landing(
    code: str,
    *,
    responsibility: str = "",
    module: str = "",
    min_anchors: int = MIN_ANCHORS,
    hit_ratio: float = HIT_RATIO,
) -> list[str]:
    """返回问题列表（空=通过）。

    锚点 < min_anchors 时跳过（非 UI 模块 / 契约未注入）。
    """
    anchors = extract_manifest_anchors(responsibility)
    if len(anchors) < min_anchors:
        return []
    src = code or ""
    missing = [a for a in anchors if a not in src]
    hit = len(anchors) - len(missing)
    ratio = hit / len(anchors) if anchors else 1.0
    if ratio >= hit_ratio:
        return []
    where = f"模块 {module}" if module else "本模块"
    miss_list = "、".join(f'「{m}」' for m in missing[:16])
    if len(missing) > 16:
        miss_list += f" 等共 {len(missing)} 条"
    return [
        f"文案落地门禁硬红（{where}）：契约锚点 {len(anchors)} 条，"
        f"源码命中 {hit}（{ratio:.0%} < {hit_ratio:.0%}）。"
        f"重写时必须逐字落地以下缺失文案：{miss_list}"
    ]
