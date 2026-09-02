# -*- coding: utf-8 -*-
"""v0.5 验收④⑤：Researcher 真实链路 + 可视化数据端点（真实 LLM）。

场景：陌生技术栈（标准库 cmd 模块）+ 用户资料注入 → 全自动 auto 任务。
验收点（M10 降级版闭环 + M11 数据源）：
  ④ Researcher：research=on 触发 → research_brief.md 四段式落盘 →
     交付物消费研究内容（cmd.Cmd / do_* API 出现在代码中）
  ⑤ 可视化：/api/project/{id}/messages 结构化消息（对话流图数据源）、
     task events、cost_report 口径一致
附：auto 模式在 Docker 缺失时降级 LocalExecutor 真实执行（验收②补充）。
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

REQUIREMENT = (
    "基于 Python 标准库 cmd 模块开发一个交互式图书管理命令行程序，"
    "支持图书的添加、删除、修改、列出与按书名/作者搜索，"
    "数据用 JSON 文件持久化。要求全程使用 cmd.Cmd 基类实现命令分发。"
)

# 用户提供的资料（真实准确的 cmd 模块文档摘要——Researcher 降级版输入）
MATERIAL = """Python cmd 模块（标准库，3.x 全系可用）文档摘要：
1. 核心类 cmd.Cmd：继承它并定义 do_<命令名> 方法即注册一条命令，
   如 def do_add(self, arg) 对应命令 add；方法返回 True 时退出循环。
2. 主循环：实例 .cmdloop(intro=None) 阻塞读取命令；空行重复上一条命令
   （可覆写 emptyline 关闭）；未知命令走 default(line) 方法。
3. 参数解析：do_* 的 arg 是命令后整段字符串（不含命令名），
   需自行 split；命令别名可设 aliases 属性（3.x 无内建，需手写）。
4. 帮助系统：doc_ 前缀方法或 do_* 的 docstring 自动生成 help <命令>；
   覆写 help_<命令> 可自定义。
5. 退出约定：惯例实现 do_quit / do_EOF（EOF 处理 Ctrl+D），返回 True。
6. 坑点：prompt 是类属性（默认 '(Cmd) '）需在子类覆盖；命令名大小写敏感；
   cmdloop 内 KeyboardInterrupt 会中断循环而非退出程序（可 try/except 包裹）。
"""

settings = load_settings()          # 读 config.json（智谱三模型 + .env 密钥）
settings.researcher_enabled = True  # 验收开启 Researcher（不改用户配置文件）
print("=== 验收④⑤：Researcher 真实链路（auto 模式，真实 LLM） ===")
print(f"模型: {settings.models} | researcher=on | Docker 缺失 → 降级 LocalExecutor")

app = create_app(settings=settings)
with TestClient(app) as c:
    r = c.post("/api/tasks", json={
        "kind": "run",
        "requirement": REQUIREMENT,
        "mode": "auto",
        "research": "on",
        "research_material": MATERIAL,
    })
    r.raise_for_status()
    task_id = r.json()["task_id"]
    print(f"任务已提交: {task_id}")

    # 轮询至终态（上限 45 分钟）
    deadline = time.time() + 45 * 60
    last_stage = ""
    while time.time() < deadline:
        t = c.get(f"/api/tasks/{task_id}").json()
        if t["stage"] != last_stage:
            print(f"  [{time.strftime('%H:%M:%S')}] 阶段: {t['stage']} "
                  f"tokens={t['tokens_used']}")
            last_stage = t["stage"]
        if t["status"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(10)

    print(f"终态: {t['status']} | 项目: {t.get('project_id')}")
    if t["status"] != "succeeded":
        print(f"错误: {t.get('error', '')[:500]}")
        sys.exit(1)

    pid = t["project_id"]
    proj = Path("projects") / pid
    result = t.get("result") or {}

    print()
    print("--- 验收④ Researcher 链路 ---")
    brief = proj / "sessions" / "research_brief.md"
    ok_brief = brief.is_file()
    print(f"[{'PASS' if ok_brief else 'FAIL'}] research_brief.md 落盘: {ok_brief}")
    if ok_brief:
        text = brief.read_text(encoding="utf-8")
        keys = sum(k in text for k in ("来源", "版本", "示例", "坑"))
        print(f"  四段式完整度: {keys}/4 关键词命中")

    # 交付物是否消费研究内容（cmd.Cmd / do_ API）
    code_hits = []
    for py in (proj / "code").rglob("*.py"):
        src = py.read_text(encoding="utf-8", errors="replace")
        if "cmd.Cmd" in src or "do_" in src.split("def ")[0] or "import cmd" in src:
            code_hits.append(py.name)
    ok_consume = bool(code_hits)
    print(f"[{'PASS' if ok_consume else 'FAIL'}] 交付物消费研究内容"
          f"（cmd.Cmd/do_* API）: {code_hits[:5]}")

    # 执行结果（auto 真实执行）
    print(f"交付摘要: {str(result.get('deliverable_summary', ''))[:200]}")
    print(f"冻结模块: {result.get('frozen_modules')} | 待反馈: {result.get('pending_modules')}")

    print()
    print("--- 验收⑤ 可视化数据端点 ---")
    m = c.get(f"/api/project/{pid}/messages")
    ok_msg = m.status_code == 200 and isinstance(m.json(), list) and m.json()
    print(f"[{'PASS' if ok_msg else 'FAIL'}] /messages 结构化消息: "
          f"{m.status_code}, {len(m.json()) if m.status_code == 200 else 0} 条"
          if m.status_code == 200 else f"[FAIL] {m.status_code}")
    if ok_msg:
        sample = m.json()[0]
        print(f"  消息字段: {sorted(sample.keys())[:8]}")

    ev = c.get(f"/api/tasks/{task_id}/events")
    print(f"事件流端点: {ev.status_code}")

    cost = proj / "logs" / "cost_report.json"
    ok_cost = cost.is_file()
    print(f"[{'PASS' if ok_cost else 'FAIL'}] cost_report 落盘: {ok_cost}")
    if ok_cost:
        cr = json.loads(cost.read_text(encoding="utf-8"))
        print(f"  total_tokens={cr.get('total_tokens')} "
              f"by_stage keys={list((cr.get('by_stage') or {}).keys())[:6]}")

    print()
    print(f"验收④⑤结论: brief={'✓' if ok_brief else '✗'} "
          f"consume={'✓' if ok_consume else '✗'} "
          f"messages={'✓' if ok_msg else '✗'} cost={'✓' if ok_cost else '✗'}")
