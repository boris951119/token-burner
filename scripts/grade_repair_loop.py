# -*- coding: utf-8 -*-
"""评分→定向修复→复评 循环驱动（通用，任何任务）。

每轮：官方全量评分 → 失败清单+错误上下文 → auto_repair（验证信号=
official_probe 跑失败子集）→ 复评。到全过/轮次耗尽/无进展为止。

用法:
    python scripts/grade_repair_loop.py --project-dir <projects/xxx> \
        --task keep --rounds 4
退出码: 0=全过, 1=有剩余失败, 2=参数/环境故障。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GRADE_DIR = ROOT / "scripts" / "official_grade"


def _run_grade(project_dir: Path, task: str) -> tuple[int, int, list[str]]:
    from scripts.local_grade import main as grade_main  # 复用同进程评分

    sys.argv = ["local_grade.py", "--project-dir", str(project_dir),
                "--task", task]
    rc = grade_main()
    summary = GRADE_DIR / "grade-summary.json"
    data = json.loads(summary.read_text(encoding="utf-8"))
    return data.get("passed", 0), data.get("total", 0), data.get("failures", [])


def _failure_contexts(project_dir: Path, failures: list[str],
                      limit: int = 3) -> list[str]:
    """从 test-results 抓前 N 个失败的页面真实快照。"""
    out: list[str] = []
    results = GRADE_DIR / "test-results"
    if not results.is_dir():
        return out
    import time

    cutoff = time.time() - 6 * 3600
    for ctx in sorted(results.glob("*/error-context.md"),
                      key=lambda p: p.stat().st_mtime, reverse=True):
        if ctx.stat().st_mtime < cutoff or len(out) >= limit:
            continue
        try:
            text = ctx.read_text(encoding="utf-8", errors="replace")
            i = text.find("# Page snapshot")
            if i > -1:
                out.append(text[i:i + 900])
        except Exception:
            continue
    return out


def _req_fragments(failures: list[str], limit: int = 6) -> list[str]:
    """失败题名 → official_probe 的 spec 片段（REQ-N 前缀）。"""
    frags = []
    for f in failures:
        m = re.match(r"(REQ-[\d.]+)", f)
        if m and m.group(1) not in frags:
            frags.append(m.group(1))
        if len(frags) >= limit:
            break
    return frags


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--task", default="keep")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--model", default=None, help="覆盖主刀模型（默认 pro）")
    args = ap.parse_args()

    from app.arcbench_smoke import auto_repair
    from app.config import load_settings

    settings = load_settings(config_file=ROOT / "config.json")
    settings.models = ((args.model,) if args.model
                       else ("openai/deepseek-v4-pro",))

    project_dir = Path(args.project_dir)
    final_ok = False
    for rnd in range(1, args.rounds + 1):
        print(f"[loop] === 第 {rnd}/{args.rounds} 轮 ===", flush=True)
        passed, total, failures = _run_grade(project_dir, args.task)
        print(f"[loop] 官方: {passed}/{total}", flush=True)
        if not failures:
            print("[loop] 全过，收工")
            return 0
        contexts = _failure_contexts(project_dir, failures)
        frags = _req_fragments(failures)
        issue = (
            "官方验收测试失败（评测方用 Playwright 按 ARIA 语义逐字断言，"
            "失败即用户需求未满足）。失败清单：\n"
            + "\n".join(f"- {f}" for f in failures[:25])
            + "\n\n页面真实快照（Playwright 实测 DOM，前 3 个失败）：\n"
            + "\n---\n".join(contexts)
            + "\n\n修复要求：失败场景按需求语义真实通过——补交互行为/"
            "对齐逐字文案（按钮/占位符/通知原文）/修导航；"
            "禁止修改 tests/ 目录与官方 specs；禁止删路由；最小化修改。"
        )
        try:
            test_cmd = [sys.executable, str(ROOT / "scripts" / "official_probe.py"),
                        "--project-dir", str(project_dir), "--task", args.task,
                        "--specs", *frags] if frags else None
            auto_repair(project_dir, settings, max_rounds=1,
                        verify_timeout=1800, test_cmd=test_cmd,
                        extra_issue=issue)
        except Exception as exc:
            print(f"[loop] 修复异常: {exc!r}"[:300], flush=True)
    # 末轮复评
    passed, total, failures = _run_grade(project_dir, args.task)
    print(f"[loop] 最终: {passed}/{total}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
