# -*- coding: utf-8 -*-
"""统计各历史项目模块通过/冻结状态（模型档位 vs 收敛率对照）。"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

for proj in sorted(Path("projects").iterdir()):
    stats: dict = {}
    for v in proj.glob("changelog/*/validation.md"):
        m = re.search(r"最终状态: (\w+)", v.read_text(encoding="utf-8"))
        if m:
            stats[m.group(1)] = stats.get(m.group(1), 0) + 1
    try:
        models = json.loads(
            (proj / "sessions" / "pipeline_state.json").read_text(encoding="utf-8")
        ).get("models", [])
    except Exception:
        models = []
    short = ",".join(m.split("/")[-1] for m in models)
    print(f"{proj.name[:40]:<42} 模型:{short:<38} 模块状态:{stats}")
