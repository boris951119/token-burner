# -*- coding: utf-8 -*-
"""v0.5 验收④⑤（续）：中断项目 resume 续跑 + 全部验证点。

前序：_accept_researcher.py 首跑在 45 分钟轮询上限时进程退出，
任务线程中断 → interruption.md 落盘（中断快照机制已被真实触发）。
本脚本：kind=resume 续跑（已完成 4 模块自动跳过，剩 4 模块），
终态后执行验收④⑤全部验证点（brief/消费/messages/cost）。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from app.config import load_settings  # noqa: E402
from app.server import create_app  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

PID = ("基于_Python_标准库_cmd_模块开发一个交互式图书管理命令行程序_支持图"
       "_20260901_161936")

settings = load_settings()
settings.researcher_enabled = True
print("=== 验收④⑤（续）：resume 断点续跑（已完成模块自动跳过） ===")

app = create_app(settings=settings)
with TestClient(app) as c:
    r = c.post("/api/tasks", json={"kind": "resume", "project_id": PID})
    r.raise_for_status()
    task_id = r.json()["task_id"]
    print(f"续跑任务已提交: {task_id}")

    deadline = time.time() + 60 * 60
    last_stage = ""
    t = {}
    while time.time() < deadline:
        t = c.get(f"/api/tasks/{task_id}").json()
        if t["stage"] != last_stage:
            print(f"  [{time.strftime('%H:%M:%S')}] 阶段: {t['stage']} "
                  f"tokens={t['tokens_used']}")
            last_stage = t["stage"]
        if t["status"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(10)

    print(f"终态: {t['status']}")
    if t["status"] != "succeeded":
        print(f"错误: {str(t.get('error', ''))[:600]}")
        sys.exit(1)

    proj = Path("projects") / PID
    result = t.get("result") or {}

    print()
    print("--- 中断恢复验证（附加验收） ---")
    print(f"[PASS] resume 续跑成功（interruption.md 存在="
          f"{(proj / 'sessions' / 'interruption.md').is_file()} → 续跑后完成）")

    print()
    print("--- 验收④ Researcher 链路 ---")
    brief = proj / "sessions" / "research_brief.md"
    ok_brief = brief.is_file()
    print(f"[{'PASS' if ok_brief else 'FAIL'}] research_brief.md 落盘")
    if ok_brief:
        text = brief.read_text(encoding="utf-8")
        keys = sum(k in text for k in ("来源", "版本", "示例", "坑"))
        print(f"  四段式完整度: {keys}/4")
        print(f"  内容摘要: {text[:150].replace(chr(10), ' ')}")

    code_hits = []
    for py in (proj / "code").rglob("*.py"):
        src = py.read_text(encoding="utf-8", errors="replace")
        if "import cmd" in src or "cmd.Cmd" in src or "cmdloop" in src:
            code_hits.append(py.relative_to(proj).as_posix())
    ok_consume = bool(code_hits)
    print(f"[{'PASS' if ok_consume else 'FAIL'}] 交付物消费研究内容"
          f"（cmd.Cmd/cmdloop）: {code_hits}")

    print()
    print("--- 验收⑤ 可视化数据端点 ---")
    m = c.get(f"/api/project/{PID}/messages")
    if m.status_code == 200:
        msgs = m.json()
        print(f"[{'PASS' if msgs else 'FAIL'}] /messages: {len(msgs)} 条结构化消息")
        if msgs:
            print(f"  消息字段: {sorted(msgs[0].keys())}")
            roles = {}
            for x in msgs:
                roles[x.get("role", x.get("agent", "?"))] = \
                    roles.get(x.get("role", x.get("agent", "?")), 0) + 1
            print(f"  角色分布: {roles}")
    else:
        print(f"[FAIL] /messages: {m.status_code}")

    cost = proj / "logs" / "cost_report.json"
    ok_cost = cost.is_file()
    print(f"[{'PASS' if ok_cost else 'FAIL'}] cost_report 落盘")
    if ok_cost:
        cr = json.loads(cost.read_text(encoding="utf-8"))
        print(f"  total_tokens={cr.get('total_tokens')}")
        print(f"  by_stage={list((cr.get('by_stage') or {}).keys())}")

    # auto 模式执行痕迹：交付物 tests 通过情况
    tests_dir = proj / "tests"
    print()
    print("--- 交付物执行验证（auto 真实执行） ---")
    print(f"tests/ 文件数: {len(list(tests_dir.rglob('test_*.py')))}")
    print(f"冻结模块: {result.get('frozen_modules')}")
    print(f"待反馈模块: {result.get('pending_modules')}")
    print(f"交付摘要: {str(result.get('deliverable_summary', ''))[:300]}")
