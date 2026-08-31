# -*- coding: utf-8 -*-
"""最终端到端验收：全新真实任务 → 交付 → 反馈闭环 → 生成物核验。"""
import json
import sys
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(method: str, path: str, body: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))


def poll(task_id: str, timeout_s: float) -> dict:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        state = call("GET", f"/api/tasks/{task_id}")
        line = f"  [{state['status']}] stage={state['stage'] or '—'} tokens={state['tokens_used']}"
        if line != last:
            print(line, flush=True)
            last = line
        if state["status"] in ("succeeded", "failed", "cancelled"):
            return state
        time.sleep(10)
    print("POLL TIMEOUT")
    sys.exit(1)


def main() -> None:
    print("health:", call("GET", "/api/health"))

    # 1. 全新真实任务
    requirement = (
        "开发一个通讯录管理命令行工具 contacts-cli：支持联系人增删改查、"
        "按姓名模糊搜索，联系人含姓名/电话/邮箱字段，数据持久化到 JSON 文件，"
        "附完整单元测试"
    )
    created = call("POST", "/api/tasks", {"kind": "run", "requirement": requirement})
    task_id = created["task_id"]
    print(f"submitted: task_id={task_id}")
    state = poll(task_id, 1500)
    if state["status"] != "succeeded":
        print("TASK FAILED:", state["error"])
        sys.exit(1)

    result = state["result"]
    print("\nkind:", result["kind"], "| frozen:", result.get("frozen_modules"))
    dash = result.get("dashboard") or {}
    print("tokens:", dash.get("total_tokens"), "/", dash.get("budget_tokens"))
    if result["kind"] != "team_flow":
        print("（被节流直出，未走团队流程——需求评估过简）")
        sys.exit(2)

    # 2. 反馈闭环（3.8）：确认成功 → 模块 AWAITING_FEEDBACK → SUCCESS（零 LLM）
    pid = result["project_id"]
    fb = call("POST", "/api/tasks", {
        "kind": "feedback", "project_id": pid, "message": "全部运行成功，无报错",
    })
    fb_state = poll(fb["task_id"], 300)
    if fb_state["status"] != "succeeded":
        print("FEEDBACK FAILED:", fb_state["error"])
        sys.exit(1)
    summary = fb_state["result"].get("deliverable_summary", "")
    print("\n--- 反馈后模块状态 ---")
    for line in summary.splitlines():
        if "：" in line and line.strip().startswith("- "):
            print(" ", line.strip())

    # 3. 生成物核验
    files = call("GET", f"/api/project/{pid}/files")["files"]
    print("\n=== 生成文件 ===")
    for f in files:
        print(" -", f)
    py_files = [f for f in files if f.startswith("code/") and f.endswith(".py")]
    assert py_files, "没有任何生成代码"
    for f in py_files[:2]:
        content = call("GET", f"/api/project/{pid}/file?path={urllib.parse.quote(f)}")["content"]
        first = content.splitlines()[0] if content else ""
        assert "```" not in content, f"{f} 仍含围栏！"
        print(f"\n--- {f} 首行: {first!r}（无围栏 ✓）")
    print("\nFINAL ACCEPTANCE: PASS")


if __name__ == "__main__":
    main()
