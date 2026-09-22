# -*- coding: utf-8 -*-
"""编译判分器：requirements.yaml → 验收清单 spec → 本地逐 REQ 红绿报告。

交付前自评分环的判分半边（与 app/acceptance_compile.py 配对）。复用
官方评分基建（scripts/official_grade 的 playwright + config 环境变量
通道），但 spec 目录走 specs-compiled/<task>/ 独立命名——与官方真题
评分链完全分道，互不污染。

前置：目标应用已在 --url 处运行（起服/生命周期由调用方管，
local_loop / 修复环均如此）。

产出 compiled-summary.json：
  {passed, failed, total, failures: ["REQ-x.y: <断言标题>", ...]}
语义与 official_grade/grade-summary.json 同构，修复环可直接换读。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.acceptance_compile import (  # noqa: E402
    compile_checklists, render_checklist_spec, to_json)

GRADE_DIR = ROOT / "scripts" / "official_grade"


def compile_for_task(requirements_dir: Path, task: str) -> dict:
    """编译清单并落 spec；返回统计。spec 为空（无 home_visible 事实）也
    写占位文件，判分器可读。"""
    yaml_path = Path(requirements_dir) / "requirements.yaml"
    if not yaml_path.is_file():
        raise SystemExit(f"[compiled] 缺 requirements.yaml: {yaml_path}")
    checklists = compile_checklists(yaml_path)
    spec_dir = GRADE_DIR / "specs-compiled" / task
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "checklist.spec.ts").write_text(
        render_checklist_spec(checklists), encoding="utf-8")
    (spec_dir / "checklists.json").write_text(
        to_json(checklists), encoding="utf-8")
    static_n = sum(1 for c in checklists if c.home_visible)
    return {"nodes": len(checklists), "static_assert_nodes": static_n,
            "spec_dir": str(spec_dir)}


def run_grade(task: str, url: str, timeout_s: int = 1800) -> dict:
    """跑编译 spec 判分，解析 playwright json 报告 → summary。"""
    report = GRADE_DIR / "compiled-report.json"
    env = dict(os.environ)
    env.update({
        "PLAYWRIGHT_TEST_DIR": f"./specs-compiled/{task}",
        "TARGET_URL": url,
        "GRADE_REPORT": str(report),
        "PLAYWRIGHT_OUTPUT_DIR": "compiled-results",
        # 单断言最多探 16 个一跳页，60s 默认卡线
        "PLAYWRIGHT_TEST_TIMEOUT": "180000",
    })
    if report.is_file():
        report.unlink()  # 防陈旧报告被读成本轮结果
    proc = subprocess.run(
        ["npx", "playwright", "test", "--config", "playwright.config.ts"],
        cwd=str(GRADE_DIR), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout_s,
        shell=(os.name == "nt"),
    )
    if not report.is_file():
        tail = (proc.stderr or proc.stdout or "")[-800:]
        raise SystemExit(f"[compiled] 无评分报告 rc={proc.returncode}\n{tail}")
    data = json.loads(report.read_text(encoding="utf-8"))
    passed = failed = 0
    failures: list[str] = []

    def _walk(suites):
        nonlocal passed, failed
        for suite in suites:
            for spec in suite.get("specs", []):
                tests = spec.get("tests", [])

                def _ok(t):
                    # JSON 报告 tests[].status 是 outcome（expected/
                    # unexpected），单次运行的权威状态在 results[]。
                    if tests and t.get("results"):
                        if any(r.get("status") == "passed"
                               for r in t["results"]):
                            return True
                    return t.get("status") in ("expected", "passed")

                ok = bool(tests) and all(_ok(t) for t in tests)
                if ok:
                    passed += 1
                else:
                    failed += 1
                    failures.append(spec.get("title", ""))
            _walk(suite.get("suites", []))

    _walk(data.get("suites", []))
    summary = {"passed": passed, "failed": failed, "total": passed + failed,
               "failures": failures}
    (GRADE_DIR / "compiled-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--requirements", required=True,
                    help="需求目录（含 requirements.yaml）")
    ap.add_argument("--task", required=True, help="任务名（目录命名用）")
    ap.add_argument("--url", default="http://127.0.0.1:3301",
                    help="运行中的应用地址")
    ap.add_argument("--compile-only", action="store_true",
                    help="只编译落盘不判分（供生成期注入/离线核对）")
    args = ap.parse_args()

    stats = compile_for_task(Path(args.requirements), args.task)
    print(f"[compiled] 节点 {stats['nodes']}，静态可判 "
          f"{stats['static_assert_nodes']} → {stats['spec_dir']}")
    if args.compile_only:
        return 0
    s = run_grade(args.task, args.url)
    print(f"[compiled] {s['passed']}/{s['total']} 通过")
    for f in s["failures"][:30]:
        print("  FAIL", f)
    return 0 if s["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
