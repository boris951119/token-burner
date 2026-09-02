# -*- coding: utf-8 -*-
"""v0.5 验收④⑤（只读验证）：不依赖任务终态，验证已产出的数据。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from app.config import load_settings  # noqa: E402
from app.server import create_app  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

PID = ("基于_Python_标准库_cmd_模块开发一个交互式图书管理命令行程序_支持图"
       "_20260901_161936")
proj = Path("projects") / PID

print("=== 验收④⑤：只读验证（7/8 模块已完成时点的数据） ===\n")

print("--- 验收④ Researcher 真实链路 ---")
brief = proj / "sessions" / "research_brief.md"
ok_brief = brief.is_file()
print(f"[{'PASS' if ok_brief else 'FAIL'}] research_brief.md 落盘: {ok_brief}")
if ok_brief:
    text = brief.read_text(encoding="utf-8")
    keys = sum(k in text for k in ("来源", "版本", "示例", "坑"))
    print(f"  四段式关键词命中: {keys}/4")
    print(f"  开头 200 字: {text[:200]}")

print()
code_hits = []
for py in (proj / "code").rglob("*.py"):
    src = py.read_text(encoding="utf-8", errors="replace")
    if "import cmd" in src or "cmd.Cmd" in src or "cmdloop" in src or "do_" in src:
        code_hits.append(py.relative_to(proj / "code").as_posix())
ok_consume = bool(code_hits)
print(f"[{'PASS' if ok_consume else 'FAIL'}] 交付物消费研究内容（cmd API）:")
for h in code_hits:
    print(f"  · {h}")

print()
print("--- 验收⑤ 可视化数据端点 ---")
settings = load_settings()
app = create_app(settings=settings)
with TestClient(app) as c:
    m = c.get(f"/api/project/{PID}/messages")
    if m.status_code == 200:
        msgs = m.json()
        print(f"[{'PASS' if msgs else 'FAIL'}] /messages: {len(msgs)} 条")
        if msgs:
            print(f"  字段: {sorted(msgs[0].keys())}")
            roles: dict = {}
            for x in msgs:
                r = x.get("role", x.get("agent", x.get("sender", "?")))
                roles[r] = roles.get(r, 0) + 1
            print(f"  角色分布: {roles}")
    else:
        print(f"[FAIL] /messages: {m.status_code} {m.text[:100]}")

    # 模块状态全景数据源（files 端点）
    fl = c.get(f"/api/project/{PID}/files")
    print(f"  /files 端点: {fl.status_code}")

print()
cost = proj / "logs" / "cost_report.json"
print(f"cost_report.json 存在: {cost.is_file()}"
      f"（失败任务按设计不生成终态报告——见 11.0 止损语义）")

print()
print("--- 已完成模块清单 ---")
mods = sorted((p.name for p in (proj / "code").iterdir() if p.is_dir()))
print(f"  {len(mods)} 个: {', '.join(mods)}")
state = json.loads(
    (proj / "sessions" / "pipeline_state.json").read_text(encoding="utf-8"))
done = set(state.get("module_status", {}).get("done", [])
           ) if isinstance(state.get("module_status"), dict) else set()
print(f"  快照 order: {state.get('order')}")
print(f"  interruption.md（可续跑）: "
      f"{(proj / 'sessions' / 'interruption.md').is_file()}")
