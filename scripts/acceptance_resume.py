# -*- coding: utf-8 -*-
"""断点续跑验收：从最新中断项目恢复（已完成模块跳过，未完成重跑）。"""
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


def main() -> None:
    print("health:", call("GET", "/api/health"))

    resumable = call("GET", "/api/resumable")
    if not resumable:
        print("无可恢复项目")
        sys.exit(1)
    target = resumable[0]  # 最新优先
    project_id = target["project_id"]
    print(f"恢复目标: {project_id} (mode={target['mode']} interrupted={target['interrupted']})")
    print("待续跑模块顺序:", target["order"])

    created = call("POST", "/api/tasks", {"kind": "resume", "project_id": project_id})
    task_id = created["task_id"]
    print(f"resume submitted: task_id={task_id}")

    deadline = time.monotonic() + 600
    last = ""
    while time.monotonic() < deadline:
        state = call("GET", f"/api/tasks/{task_id}")
        line = f"  [{state['status']}] stage={state['stage'] or '—'} tokens={state['tokens_used']}"
        if line != last:
            print(line, flush=True)
            last = line
        if state["status"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(5)
    else:
        print("TIMEOUT")
        sys.exit(1)

    if state["status"] != "succeeded":
        print("RESUME FAILED:", state["error"])
        sys.exit(1)

    result = state["result"]
    print("\n=== 续跑结果 ===")
    print("kind:", result["kind"])
    print("frozen_modules:", result.get("frozen_modules"))
    dash = result.get("dashboard") or {}
    print("tokens:", dash.get("total_tokens"), "budget:", dash.get("budget_tokens"))
    print("\n--- 交付摘要 ---")
    print(result.get("deliverable_summary", "")[:1200])

    files = call("GET", f"/api/project/{project_id}/files")["files"]
    print("\n=== 生成文件 ===")
    for f in files:
        print(" -", f)
    print("\nRESUME ACCEPTANCE: PASS")


if __name__ == "__main__":
    main()
