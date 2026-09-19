# -*- coding: utf-8 -*-
"""官方真题探针：导出布局 → 起服 → 跑指定 Playwright 真题 → 0/1 退出。

用途：作为 auto_repair 的 test_cmd——修复验证信号 = 评分器本尊
（2026-09-20 取证：进程内探针看不见 JS 渲染与真实交互，官方真题
才是唯一可信信号）。

用法:
    python scripts/official_probe.py --project-dir <projects/xxx> \
        --specs REQ-2.1 REQ-2.2 [--task keep] [--port 3455]
退出码: 0=指定真题全过, 1=有失败, 2=环境故障。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GRADE_DIR = ROOT / "scripts" / "official_grade"


def _free_port(prefer: int) -> int:
    import socket

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


def _wait_health(url: str, deadline_s: float = 60) -> bool:
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--specs", nargs="+", required=True,
                    help="真题名片段，如 REQ-2.1 REQ-2.2")
    ap.add_argument("--task", default="keep")
    ap.add_argument("--port", type=int, default=3455)
    args = ap.parse_args()

    from app.platform_export import export_platform_layout

    template = ROOT / ".tmp" / "official_probe_template"
    if template.exists():
        shutil.rmtree(template)
    template.mkdir(parents=True)
    export_platform_layout(template, Path(args.project_dir))
    backend = template / "backend"
    if not (backend / "main.py").is_file():
        print("[oprobe] 导出缺 backend/main.py")
        return 2

    port = _free_port(args.port)
    env = dict(os.environ, PORT=str(port))
    proc = subprocess.Popen(
        [sys.executable, str(backend / "main.py")],
        cwd=str(backend), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not _wait_health(f"http://127.0.0.1:{port}/api/health"):
            print("[oprobe] 健康探针超时")
            return 2
        report = GRADE_DIR / "probe-report.json"
        env2 = dict(os.environ,
                    TARGET_URL=f"http://127.0.0.1:{port}",
                    GRADE_REPORT=str(report),
                    PLAYWRIGHT_TEST_DIR=f"./specs/{args.task}",
                    PLAYWRIGHT_OUTPUT_DIR=str(GRADE_DIR / "test-results-probe"))
        npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
        cmd = [npx, "playwright", "test"]
        for spec in args.specs:
            cmd += [spec]
        proc_test = subprocess.run(
            cmd, cwd=str(GRADE_DIR), env=env2,
            capture_output=True, text=True, timeout=1200)
        (GRADE_DIR / "probe-run.log").write_text(
            (proc_test.stdout or "") + "\n===== STDERR =====\n"
            + (proc_test.stderr or ""), encoding="utf-8")
        if not report.is_file():
            print("[oprobe] 无报告，详见 probe-run.log")
            return 2
        data = json.loads(report.read_text(encoding="utf-8"))
        passed = failed = 0
        failures = []

        def _walk(suite):
            nonlocal passed, failed
            for s in suite.get("suites", []):
                _walk(s)
            for spec in suite.get("specs", []):
                t = (spec.get("tests") or [{}])[0]
                results = (t.get("results") or [{}])
                ok = all(r.get("status") == "passed" for r in results)
                if ok:
                    passed += 1
                else:
                    failed += 1
                    failures.append(spec.get("title", "?"))
        for s in data.get("suites", []):
            _walk(s)
        print(f"[oprobe] {passed}/{passed + failed} passed")
        for f in failures:
            print(f"  FAIL {f}")
        return 0 if not failed and passed else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
