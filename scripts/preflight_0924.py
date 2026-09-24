"""批次#59 零 LLM 预检：正式赛两套真题面走通「解析→渲染→编译判分环」，
并量出契约八的立项频次——题面里「进入 X 页 / 首页聚合区」这类导航性要求占多少条。

口径说明（为什么不直接 grep 原文）：判分环编译出的 NodeChecklist 已经把每条
ATOMIC 拆成逐字事实，换页类要求长在 scenarios 的 THEN 步里（behavior_expectations
通道在正式赛题面上几乎不装东西，首版按它统计得出假 0）。按逐条 REQ 计数才是
「一条需求需要几个真路由」的频次，整篇 grep 会把一条需求里的三句算成三条。
目的地页名只打印词面统计，不打印题面原文。

不入库的东西：题面原文一律不打印，只打印条数/字数/比例。
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.acceptance_compile import compile_checklists_from_text  # noqa: E402
from app.arcbench_ingest import (  # noqa: E402
    count_requirements,
    load_requirement_tree,
    render_requirement_text,
)
from app.utils.budget import size_aware_budget  # noqa: E402

TASK_ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else (
    Path.home() / "Developer" / "token-burner-taskdata" / "hackathon-req-0924")

# 「换页」的判据：THEN 步里既出现目的地动词，又出现页面类名词。
# 只看 behavior_expectations 会得到假 0（9/24 首版踩过）——正式赛题面的跳转
# 要求全部长在 scenarios 的 THEN 步里，编译器不把它们抄进期望文案通道。
DEST = re.compile(
    r"(open[s]?\b|show[s]?\b|display|appear|navigat\w*|redirect\w*|load[s]?\b"
    r"|take[s]?\b|route[s]?\b|switch\w*\s+to|go(es)?\s+to|land\w*\s+(in|on)"
    r"|返回|进入|跳转|打开)",
    re.I,
)
PAGE_NOUN = re.compile(
    r"\b((?:[A-Za-z][\w'’]*[ ’']?){0,3}?(page|view|screen|editor|dashboard"
    r"|dialog|modal|overview|home|center|list|tab|window))\b",
    re.I,
)
# 词面归一：限定词与泛指词不构成功能面（"the page" 不是一种页），题面专名保留
# 在本机输出里，不写进仓库任何随包文件。
STOP = {
    "the", "a", "an", "this", "that", "its", "their", "your", "same", "other",
    "corresponding", "appropriate", "correct", "respective", "matching",
    "relevant", "previously", "displayed", "shown", "opens", "open", "new",
    "main", "current", "original", "source", "target", "both", "either",
    "time", "on", "in", "of", "to", "and", "or", "is", "be", "as", "with",
}


def normalize_page(phrase: str) -> str:
    words = [w for w in re.split(r"[\s’']+|-", phrase.strip().lower()) if w]
    kept = [w for w in words if w not in STOP][-3:]
    return " ".join(kept)


def nav_facts(checklist) -> list[str]:
    """该条需求里所有「要求换到某个页面」的 THEN 步原文（去重保序）。"""
    out: list[str] = []
    for scen in checklist.scenarios:
        for step in scen.get("steps", []):
            if not str(step.get("keyword", "")).upper().endswith("THEN"):
                continue
            body = str(step.get("content", ""))
            if DEST.search(body) and PAGE_NOUN.search(body):
                for m in PAGE_NOUN.finditer(body):
                    key = normalize_page(m.group(1))
                    if key and key not in out:
                        out.append(key)
    return out


def report(name: str, req_dir: Path) -> None:
    tree, _ = load_requirement_tree(req_dir)
    text = render_requirement_text(tree)
    n_atomic = count_requirements(tree)
    envelope = size_aware_budget(n_atomic, len(text))
    cls = compile_checklists_from_text(text)

    nav_reqs = [c for c in cls if nav_facts(c)]
    pages: Counter = Counter()
    page_mods: dict[str, set] = {}
    for c in nav_reqs:
        for p in nav_facts(c):
            pages[p] += 1
            page_mods.setdefault(p, set()).add(c.module_id)
    mods = Counter(c.module_id for c in cls)
    generic = {p for p in pages if " " not in p}
    named = set(pages) - generic

    print(f"### {name}")
    print(f"  原子条数={n_atomic}  渲染字数={len(text):,}  信封={envelope:,}"
          f"（{envelope / (len(text) / 1000):,.0f} token/千字）")
    print(f"  编译出清单={len(cls)} 条（应等于原子条数：{'一致' if len(cls) == n_atomic else '不一致★'}）")
    print(f"  含换页要求的需求={len(nav_reqs)} 条（{len(nav_reqs) / max(1, len(cls)):.0%}）"
          f"  具名目的地页={len(named)} 种（另泛指 {len(generic)} 种）")
    print(f"  具名页被几个模块提及（只算具名）："
          f"{dict(sorted(Counter(len(v) for p, v in page_mods.items() if ' ' in p).items()))}"
          f"（≥2 ⇒ 单模块注入契约不够覆盖）")
    print(f"  模块数={len(mods)}  每模块需求数 min/中位/max="
          f"{min(mods.values())}/{sorted(mods.values())[len(mods) // 2]}/{max(mods.values())}")
    print(f"  被提及最多的具名页 top5（次数/涉及模块数）：", end="")
    shown = 0
    for p, n in pages.most_common():
        if " " not in p:
            continue
        if shown >= 5:
            break
        print(f" {p}×{n}/{len(page_mods[p])}", end="")
        shown += 1
    print("\n")


def main() -> int:
    tasks = {
        "keep(初赛域)": ROOT / ".tmp/arc-bench-repo/arc-bench-lite/keep/requirements",
        "bookstack(初赛域)": ROOT / ".tmp/arc-bench-repo/arc-bench-lite/bookstack/requirements",
        "sheet(正式赛)": TASK_ROOT / "hackathon--sheet",
        "github(正式赛)": TASK_ROOT / "hackathon--github",
    }
    missing = [str(p) for p in tasks.values() if not p.is_dir()]
    if missing:
        for m in missing:
            print(f"!! 缺目录 {m}")
        return 1
    for name, path in tasks.items():
        report(name, path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
