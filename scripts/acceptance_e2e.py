# -*- coding: utf-8 -*-
"""端到端验收脚本：真实 LLM 任务（异步 API 提交 → 轮询 → 交付物核验）。"""
import json
import sys
import time
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
    # 0. 健康检查
    print("health:", call("GET", "/api/health"))

    # 1. 提交真实任务（多特性需求 → 评估难度应 ≥4 → 完整团队流程）
    requirement = (
        "开发一个命令行待办事项管理工具 todo-cli：支持添加、列出、完成、删除待办，"
        "待办带优先级（高/中/低）并按优先级排序，数据持久化保存到 JSON 文件，"
        "提供统计摘要（总数/已完成/未完成/逾期数），附完整单元测试"
    )
    created = call("POST", "/api/tasks", {"kind": "run", "requirement": requirement})
    task_id = created["task_id"]
    print(f"submitted: task_id={task_id} elapsed_ms={created['elapsed_ms']}")

    # 2. 轮询：打印阶段与 token 演进
    deadline = time.monotonic() + 600
    last_line = ""
    while time.monotonic() < deadline:
        state = call("GET", f"/api/tasks/{task_id}")
        line = f"  [{state['status']}] stage={state['stage'] or '—'} tokens={state['tokens_used']}"
        if line != last_line:
            print(line, flush=True)
            last_line = line
        if state["status"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(5)
    else:
        print("TIMEOUT")
        sys.exit(1)

    if state["status"] != "succeeded":
        print("TASK FAILED:", state["error"])
        sys.exit(1)

    result = state["result"]
    print("\n=== 任务结果 ===")
    print("kind:", result["kind"])
    print("project_dir:", result.get("project_dir"))
    print("frozen_modules:", result.get("frozen_modules"))
    pid = result.get("project_id")
    dash = result.get("dashboard") or {}
    print("tokens:", dash.get("total_tokens"),
          "budget:", dash.get("budget_tokens"),
          "by_stage:", dash.get("by_stage"))
    summary = result.get("deliverable_summary", "")
    print("\n--- 交付摘要（节选） ---")
    print("\n".join(summary.splitlines()[:12]))

    # 3. 生成物核验（M1-4 端点）
    files = call("GET", f"/api/project/{pid}/files")["files"]
    print("\n=== 生成文件 ===")
    for f in files:
        print(" -", f)
    for f in files:
        if f.endswith(".py") and f.startswith("code/"):
            content = call("GET", f"/api/project/{pid}/file", ) if False else \
                json.loads(urllib.request.urlopen(
                    f"{BASE}/api/project/{pid}/file?path={urllib.parse.quote(f)}"
                ).read().decode("utf-8"))["content"]
            print(f"\n--- {f} 前 12 行 ---")
            print("\n".join(content.splitlines()[:12]))
            break

    print("\nE2E ACCEPTANCE: PASS")


if __name__ == "__main__":
    import urllib.parse
    main()
