# -*- coding: utf-8 -*-
"""M17-1 基准跑批脚本：标准需求集 × auto 模式 → 模块通过率报告。

用法（先启动 server：python -m app.server）：
    python scripts/bench_v1_run.py --ids T1,T2,T3 --out logs/bench_v1/pilot
    python scripts/bench_v1_run.py --ids T1..T10  --out logs/bench_v1/full

产出：
    <out>/<id>_task.json      每任务原始终态（server 返回）
    <out>/<id>_bench.json     每任务基准数据（模块终态/成本/预算命中）
    <out>/bench_report.json   汇总报告（通过率/预算超支率/配置快照）

模块通过率口径（v1.0.md KPI）：终态非 FROZEN 模块 / 全部模块。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"
POLL_INTERVAL = 20
PER_TASK_TIMEOUT = 7200  # 单任务上限 2h（GLM 免费档单次调用可达 10min，5 轮修复链路远超 1h）


def call(method: str, path: str, body: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_terminal(task_id: str) -> dict:
    """轮询任务至终态（复用 _poll_task 语义，超时抛 TimeoutError）。"""
    deadline = time.monotonic() + PER_TASK_TIMEOUT
    last = ""
    while time.monotonic() < deadline:
        s = call("GET", f"/api/tasks/{task_id}")
        line = f"    [{s['status']}] stage={s.get('stage') or '—'} tokens={s.get('tokens_used')}"
        if line != last:
            print(line, flush=True)
            last = line
        if s["status"] in ("succeeded", "failed", "cancelled"):
            return s
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"task {task_id} 超过 {PER_TASK_TIMEOUT}s 未到终态")


def module_states(project_dir: str) -> dict[str, str]:
    """从交付物 changelog/*/validation.md 提取各模块最终状态。"""
    states: dict[str, str] = {}
    for v in sorted(Path(project_dir).glob("changelog/*/validation.md")):
        m = re.search(r"最终状态: (\w+)", v.read_text(encoding="utf-8"))
        if m:
            states[v.parent.name] = m.group(1)
    return states


def cost_of(project_dir: str) -> dict:
    p = Path(project_dir) / "logs" / "cost_report.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    return {
        "total_tokens": d.get("total_tokens"),
        "budget_tokens": d.get("budget_tokens"),
        "over_budget": (
            bool(d.get("budget_tokens")) and d["total_tokens"] > d["budget_tokens"]
        ),
    }


def run_one(task: dict, out_dir: Path, budget_override: int | None,
            models_override: list[str] | None = None) -> dict:
    tid = task["id"]
    print(f"[{tid}] 提交：{task['requirement'][:40]}…")
    body = {
        "kind": "run",
        "requirement": task["requirement"],
        "mode": "auto",                # M17-1：auto 模式（Docker 缺失自动降级进程）
        "spec_confirm": "确认",         # 无人值守：spec 自动确认
        "research": "off",
    }
    if budget_override:
        body["budget_tokens"] = budget_override
    if models_override:
        # M17-1 扩展：按任务覆盖三模型（顺序 PM,dev,test；须互异，3.3）
        body["models"] = models_override
        print(f"[{tid}] models={models_override}")
    created = call("POST", "/api/tasks", body)
    print(f"[{tid}] task_id={created['task_id']}")
    state = wait_terminal(created["task_id"])
    (out_dir / f"{tid}_task.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    result = state.get("result") or {}
    project_dir = result.get("project_dir") or ""
    states = module_states(project_dir) if project_dir else {}
    total = len(states)
    passed = sum(1 for v in states.values() if v != "FROZEN")
    bench = {
        "id": tid,
        "category": task["category"],
        "difficulty_target": task["difficulty_target"],
        "status": state["status"],
        "kind": result.get("kind"),
        "project_dir": project_dir,
        "modules": states,
        "modules_total": total,
        "modules_passed": passed,
        "pass_rate": (passed / total) if total else 0.0,
        "tokens_used": state.get("tokens_used"),
        "cost": cost_of(project_dir) if project_dir else {},
        "error": state.get("error"),
    }
    (out_dir / f"{tid}_bench.json").write_text(
        json.dumps(bench, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{tid}] 终态={state['status']} 模块 {passed}/{total} 非冻结"
          f" tokens={bench['tokens_used']}")
    return bench


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=str(Path(__file__).parent / "bench_tasks.json"))
    ap.add_argument("--ids", required=True, help="逗号分隔任务 id，如 T1,T2,T3")
    ap.add_argument("--out", required=True, help="报告输出目录")
    ap.add_argument("--budget", type=int, default=None,
                    help="任务级预算覆盖（缺省用服务端档位：auto ×2.5）")
    ap.add_argument("--models", default=None,
                    help="逗号分隔三模型覆盖（PM,dev,test；须互异），如 "
                         "openai/glm-4-flash,openai/glm-4.7,openai/glm-4.5-air")
    args = ap.parse_args()

    spec = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
    by_id = {t["id"]: t for t in spec["tasks"]}
    ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    missing = [i for i in ids if i not in by_id]
    if missing:
        sys.exit(f"任务 id 不存在: {missing}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    health = call("GET", "/api/health")
    print("server health:", health)

    results = []
    for tid in ids:
        try:
            models_override = (
                [m.strip() for m in args.models.split(",") if m.strip()]
                if args.models else None
            )
            results.append(run_one(by_id[tid], out_dir, args.budget, models_override))
        except Exception as e:  # 单任务失败不中断批次（报告可归因）
            print(f"[{tid}] 异常：{type(e).__name__}: {e}")
            results.append({"id": tid, "status": "error",
                            "error": f"{type(e).__name__}: {e}"})

    total_modules = sum(r.get("modules_total", 0) for r in results)
    passed_modules = sum(r.get("modules_passed", 0) for r in results)
    ok_tasks = [r for r in results if r.get("status") == "succeeded"]
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tasks_file": str(args.tasks),
        "ids": ids,
        "per_task": results,
        "modules_total": total_modules,
        "modules_passed": passed_modules,
        "module_pass_rate": (passed_modules / total_modules) if total_modules else 0.0,
        "task_success_rate": (len(ok_tasks) / len(results)) if results else 0.0,
        "over_budget_tasks": sum(
            1 for r in results if r.get("cost", {}).get("over_budget")),
        "admission_line": 0.5,
        "admission_passed": bool(results) and total_modules > 0
        and passed_modules / total_modules >= 0.5,
    }
    (out_dir / "bench_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== 汇总 ===")
    print(f"任务成功: {len(ok_tasks)}/{len(results)}  "
          f"模块通过率: {passed_modules}/{total_modules}"
          f" = {report['module_pass_rate']:.0%}  "
          f"准入线(50%): {'达标' if report['admission_passed'] else '未达标'}")


if __name__ == "__main__":
    main()
