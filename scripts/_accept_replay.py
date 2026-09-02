# -*- coding: utf-8 -*-
"""v0.5 验收①：模式推荐回放验证（纯统计，无 LLM）。

口径：用每个历史项目的原始需求查询 recommend()，验证推荐模式与该项目
实际执行模式的一致率（KPI ≥80%）；另验证冷启动（不相似需求 → 缺省 safe）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from app.config import Settings  # noqa: E402
from app.recommender import recommend  # noqa: E402

root = Path(__file__).resolve().parent.parent / "projects"
settings = Settings()

print("=== 验收①：模式推荐回放验证 ===")
hits = total = 0
for p in sorted(root.iterdir()):
    req_file = p / "sessions" / "requirements.md"
    state_file = p / "sessions" / "pipeline_state.json"
    if not (req_file.is_file() and state_file.is_file()):
        continue
    req = req_file.read_text(encoding="utf-8").strip()[:120]
    state = json.loads(state_file.read_text(encoding="utf-8"))
    r = recommend(req, root, settings)
    total += 1
    ok = r["mode"] == state.get("mode", "safe")
    hits += ok
    mark = "一致" if ok else "不一致"
    print(f"[{mark}] 实际={state.get('mode')} 推荐={r['mode']} "
          f"预算={r['budget_tokens']} 命中样本={r['history_size']}")
    print(f"   理由: {r['reason']}")
rate = hits / total * 100 if total else 0
print(f"回放一致率: {hits}/{total} = {rate:.0f}%（KPI ≥80% -> "
      f"{'PASS' if rate >= 80 else 'FAIL'}）")

print()
print("=== 冷启动场景（不相似需求 → 缺省 safe） ===")
r = recommend("帮我写一首关于秋天的诗", root, settings)
print(f"推荐={r['mode']} 理由: {r['reason']}")
