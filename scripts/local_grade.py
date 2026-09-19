# -*- coding: utf-8 -*-
"""本地官方评分器：导出布局 → 起服 → 跑官方 Playwright 真题 → 出分。

终结「修不全」的那一刀：本地分数 = 平台分数（同一套确定性用例），
交付前所有行为维度缺陷全部显形，不再一次炸一个。零 LLM token。

用法:
    python scripts/local_grade.py --project-dir <projects/xxx> [--task keep]
    python scripts/local_grade.py --exported-dir <已导出的模板根> [--task keep]

输出: grade-report.json + 控制台摘要; 退出码 0=全过, 1=有失败, 2=环境故障。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GRADE_DIR = ROOT / "scripts" / "official_grade"


def _free_port(prefer: int) -> int:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", prefer))
        return prefer
    except OSError:
        sock.close()
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port


def _wait_health(url: str, deadline_s: float = 90) -> bool:
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.6)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", help="生成项目根（含 code/）")
    ap.add_argument("--exported-dir", help="已导出的模板根（含 backend/）")
    ap.add_argument("--task", default="keep",
                    choices=["keep", "bookstack"],
                    help="官方真题套件（当前已装 keep）")
    ap.add_argument("--port", type=int, default=3301)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    if args.exported_dir:
        template = Path(args.exported_dir).resolve()
    elif args.project_dir:
        from app.platform_export import export_platform_layout

        template = ROOT / ".tmp" / "local_grade_template"
        if template.exists():
            shutil.rmtree(template)
        template.mkdir(parents=True)
        summary = export_platform_layout(template, Path(args.project_dir))
        print(f"[grade] 导出: backend={summary['backend_files']}文件, "
              f"frontend={summary['frontend_files']}文件", flush=True)
    else:
        print("[grade] 需要 --project-dir 或 --exported-dir")
        return 2

    backend = template / "backend"
    if not (backend / "main.py").is_file():
        print(f"[grade] {backend} 缺 main.py——先导出布局")
        return 2

    port = _free_port(args.port)
    env = dict(os.environ, PORT=str(port))
    proc = subprocess.Popen(
        [sys.executable, str(backend / "main.py")],
        cwd=str(backend), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not _wait_health(f"http://127.0.0.1:{port}/api/health"):
            print("[grade] 应用健康探针超时——起服失败")
            return 2
        print(f"[grade] 应用就绪: http://127.0.0.1:{port}", flush=True)

        report = args.report or str(GRADE_DIR / "grade-report.json")
        env2 = dict(os.environ, TARGET_URL=f"http://127.0.0.1:{port}",
                    GRADE_REPORT=report,
                    PLAYWRIGHT_OUTPUT_DIR=str(GRADE_DIR / "test-results"))
        npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
        proc_test = subprocess.run(
            [npx, "playwright", "test"],
            cwd=str(GRADE_DIR), env=env2,
            capture_output=True, text=True, timeout=3600)
        # 全量落盘：后台任务 stdout 块缓冲会被截断，崩溃现场必须落本地
        run_log = GRADE_DIR / "grade-run.log"
        run_log.write_text(
            (proc_test.stdout or "") + "\n===== STDERR =====\n"
            + (proc_test.stderr or ""), encoding="utf-8")
        tail = (proc_test.stdout or "").splitlines()[-15:]
        print(f"[grade] playwright rc={proc_test.returncode} "
              f"完整输出: {run_log}")
        for line in tail:
            print("  " + line[:160])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    report_path = Path(report)
    if not report_path.is_file():
        print("[grade] 无评分报告——"
              f"GRADE_REPORT={report}，现场见 grade-run.log")
        return 2
    data = json.loads(report_path.read_text(encoding="utf-8"))
    specs = data.get("suites", [])
    passed = failed = 0
    failures = []
    def _walk(suite):
        nonlocal passed, failed
        for s in suite.get("suites", []):
            _walk(s)
        for spec in suite.get("specs", []):
            ok = all(t.get("status") == "expected"
                     for t in spec.get("tests", [{}])[0].get("results", []))
            if ok:
                passed += 1
            else:
                failed += 1
                failures.append(spec.get("title", "?"))
    for s in specs:
        _walk(s)
    total = passed + failed
    print(f"\n[grade] 官方真题: {passed}/{total} passed"
          f" ({passed / total * 100:.0f}%)" if total else "[grade] 0 用例")
    for f in failures[:15]:
        print(f"  FAIL {f}")
    (GRADE_DIR / "grade-summary.json").write_text(json.dumps({
        "passed": passed, "failed": failed, "total": total,
        "failures": failures,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if total and not failed else 1


import shutil  # noqa: E402  （供导出清理使用）

if __name__ == "__main__":
    sys.exit(main())
