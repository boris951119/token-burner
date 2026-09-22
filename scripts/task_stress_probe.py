# 零 LLM 试题格式抗压测试：6 官方题面 × 三解析通道（ingest/验收编译/节点切分）
from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.arcbench_ingest import (  # noqa: E402
    load_requirement_tree, render_requirement_text, load_fixture_hint,
    _atomic_nodes,
)
from app.acceptance_compile import (  # noqa: E402
    compile_checklists, compile_checklists_from_text,
)
from app.utils.selftest_gate import _split_atomic_nodes  # noqa: E402

APPS = ["keep", "bookstack", "stackoverflow", "prestashop", "12306", "ctrip"]
BASE = ROOT / ".tmp/arc-bench-repo/arc-bench/webapp"


fails = 0
for app in APPS:
    req_dir = BASE / app / "requirements"
    yaml_path = req_dir / "requirements.yaml"
    print(f"\n===== {app} =====")
    try:
        tree, _ = load_requirement_tree(req_dir)
        text = render_requirement_text(tree, fixture_hint=load_fixture_hint(req_dir))
        ids = [n.get("id") for n in _atomic_nodes(tree)]
        yaml_cl = compile_checklists(yaml_path)
        text_cl = compile_checklists_from_text(text)
        split_nodes, _ctx = _split_atomic_nodes(text)
        print(f"  树 ATOMIC={len(ids)}  YAML清单={len(yaml_cl)}  文本清单={len(text_cl)}  节点切分={len(split_nodes)}")
        yaml_ids = {c.req_id for c in yaml_cl}
        text_ids = {c.req_id for c in text_cl}
        miss_in_text = yaml_ids - text_ids
        extra_in_text = text_ids - yaml_ids
        if miss_in_text:
            print(f"  !! 文本通道漏抽: {sorted(miss_in_text)[:8]}")
        if extra_in_text:
            print(f"  !! 文本通道多抽: {sorted(extra_in_text)[:8]}")
        # 逐字事实对比：YAML 通道为权威，文本通道应至少覆盖同等控件线索
        y_facts = sum(len(c.control_labels) + len(c.behavior_expectations) + len(c.seed_entities) for c in yaml_cl)
        t_facts = sum(len(c.control_labels) + len(c.behavior_expectations) + len(c.seed_entities) for c in text_cl)
        print(f"  逐字事实 YAML={y_facts} 文本={t_facts}")
        split_ids = {nid for nid, _ in split_nodes}
        miss_split = {i for i in yaml_ids if i not in split_ids}
        if miss_split:
            print(f"  !! 节点切分缺失: {sorted(miss_split)[:8]}")
        # 两通道 checklist 内容级 diff（同 id 的可见控件集合）
        ymap = {c.req_id: c for c in yaml_cl}
        tmap = {c.req_id: c for c in text_cl}
        for rid in sorted(ymap.keys() & tmap.keys()):
            yv, tv = set(ymap[rid].control_labels), set(tmap[rid].control_labels)
            if yv != tv:
                print(f"  ~~ {rid} 控件差异 YAML-only={sorted(yv-tv)[:3]} TEXT-only={sorted(tv-yv)[:3]}")
    except Exception:
        fails += 1
        print(f"  XXX 异常:\n{traceback.format_exc()}")

print(f"\n完成。异常题面数: {fails}")
