# -*- coding: utf-8 -*-
"""题面→提示词通道覆盖率审计（零 LLM，秒级）。

用途：拿到任何新题（官方/自造）后，不花钱先量一遍——需求树里的逐字
事实（helpers.ts 夹具精确串、requirements.md 独有条款、reference 截图）
有多少真的进了开发契约文本。漏在通道外的事实，模型再强也看不见。

用法：python3 scripts/task_channel_audit.py <webapp-root>
      （目录下每个子题含 requirements/ 与 tests/）
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.arcbench_ingest import (  # noqa: E402
    _atomic_nodes, load_fixture_hint, load_requirement_tree,
    render_requirement_text,
)

QUOTED = re.compile(r"['\"`]([^'\"`\n]{3,80})['\"`]")
_SKIP_PREFIX = ("http", "./", "../", "//", "${", "=>")


def _facts(text: str) -> set[str]:
    out = set()
    for s in QUOTED.findall(text):
        s = s.strip()
        if len(s) >= 3 and not s.startswith(_SKIP_PREFIX):
            out.add(s)
    return out


def _find_fixture(requirements_dir: Path) -> Path | None:
    for cand in (requirements_dir.parent / "tests" / "helpers.ts",
                 requirements_dir / "tests" / "helpers.ts",
                 requirements_dir / "helpers.ts"):
        if cand.is_file():
            return cand
    return None


def audit_app(app_dir: Path) -> list[str]:
    req = app_dir / "requirements"
    if not req.is_dir():
        return [f"{app_dir.name}: SKIP（无 requirements/）"]
    tree, _path = load_requirement_tree(req)
    fixture = _find_fixture(req)
    hint = load_fixture_hint(req)
    text = render_requirement_text(tree, fixture_hint=hint)
    notes: list[str] = []

    nodes = _atomic_nodes(tree)
    notes.append(f"{app_dir.name:13} ATOMIC={len(nodes):3} 契约文本={len(text):6} "
                 f"夹具注入={len(hint):5}")

    # ① helpers.ts 精确串是否可见
    if fixture:
        want = _facts(fixture.read_text(encoding="utf-8", errors="replace"))
        miss = sorted(s for s in want if s not in text)
        notes.append(f"  夹具串 {len(want)} 个，契约未见 {len(miss)}"
                     + (f"  ← 例: {miss[:3]}" if miss else "  ✓"))

    # ② requirements.md 是否携带 yaml 之外的条款（ingest 只读 yaml）
    md = req / "requirements.md"
    if md.is_file():
        yaml_facts = _facts(_path.read_text(encoding="utf-8", errors="replace"))
        md_only = sorted(s for s in _facts(md.read_text(encoding="utf-8",
                                                         errors="replace"))
                         if s not in yaml_facts)
        notes.append(f"  md 独有串 {len(md_only)}"
                     + (f"  ← 例: {md_only[:3]}" if md_only else "  ✓"))

    # ③ 截图转写覆盖（_vision_cache.json 键为图片路径）
    refs = sorted(p.name for p in (req / "reference").glob("*.png")) \
        if (req / "reference").is_dir() else []
    cache: dict = {}
    cp = req / "_vision_cache.json"
    if cp.is_file():
        try:
            cache = json.loads(cp.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    if refs:
        covered = sum(1 for r in refs
                      if any(r in k for k in cache))
        flag = "✓" if covered == len(refs) else f"← 缺 {len(refs) - covered}"
        notes.append(f"  截图 {len(refs)}，已转写 {covered} {flag}")
    return notes


def main(root: str) -> int:
    base = Path(root)
    apps = sorted(p for p in base.iterdir() if (p / "requirements").is_dir())
    if not apps:
        print(f"{base} 下没有子题目录")
        return 1
    for app in apps:
        for line in audit_app(app):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else ".tmp/arc-bench-repo/arc-bench/webapp"))
