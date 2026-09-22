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


def _pid_alive(pid: int) -> bool:
    # Windows：OpenProcess 探活（无 psutil 依赖）；退出码即存活位
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
            return code.value == 259  # STILL_ACTIVE
        return True
    finally:
        kernel32.CloseHandle(h)


def _acquire_grade_lock():
    """评分互斥锁：模板目录/test-results/summary 全是共享路径，
    9/20 取证：两个修复环并发互相 rmtree 对方模板，起服失败被记 0 分。
    残留锁按 pid 探活自动回收。返回锁文件路径（None=已有实例在跑）。"""
    lock = GRADE_DIR / ".grade.lock"
    if lock.exists():
        try:
            old = int(lock.read_text().strip() or 0)
        except (ValueError, OSError):
            old = 0
        if old and old != os.getpid() and _pid_alive(old):
            return None  # 他进程活锁；同 pid 可重入（修复环同进程复评）
        if old == os.getpid():
            return lock
        lock.unlink(missing_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    try:
        os.write(fd, str(os.getpid()).encode())
    finally:
        os.close(fd)
    return lock


def _wait_health(url: str, deadline_s: float = 60, proc=None) -> bool:
    """就绪探针，预算与放弃条件照抄官方 runner（60 次×1s，服务进程一退出
    就 break）。本地复现的意义在于读数可迁移，90s 的宽限只会让我们把平台
    判 runtime_unhealthy 的交付看成"本地能起"。"""
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        if proc is not None and proc.poll() is not None:
            return False
        time.sleep(1)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", help="生成项目根（含 code/）")
    ap.add_argument("--exported-dir", help="已导出的模板根（含 backend/）")
    ap.add_argument("--task", default="keep",
                    help="官方真题套件名=specs/ 下目录（任意任务，不再枚举）")
    ap.add_argument("--port", type=int, default=3301)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    task_specs = GRADE_DIR / "specs" / args.task
    if not task_specs.is_dir():
        print(f"[grade] 任务套件未安装: {task_specs}"
              f"（把官方 specs 目录放到该处即可接入新任务）")
        return 2

    # 9/20 取证：用系统 python 跑评分→后端缺 flask 秒崩→健康探针 90s
    # 超时报"起服失败"，根因被掩盖。依赖在场性必须前置成即时错误。
    try:
        import flask  # noqa: F401
    except ImportError:
        print(f"[grade] 当前解释器 {sys.executable} 缺 flask——"
              "请用项目 venv 的 python 运行本脚本")
        return 2

    lock = _acquire_grade_lock()
    if lock is None:
        print("[grade] 已有评分实例在跑（.grade.lock 活锁）——"
              "共享模板/报告路径会被并发踩踏，拒绝启动")
        return 2
    import atexit

    atexit.register(lambda: lock.unlink(missing_ok=True))

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
    # 起服现场必须落盘：DEVNULL 吞掉子进程 stderr，500 根因（如接口
    # 漂移 init_db/init_app）永远查不着——9/21 keep 起服失败取证
    boot_log = GRADE_DIR / "app-boot.log"
    boot_fp = open(boot_log, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [sys.executable, str(backend / "main.py")],
        cwd=str(backend), env=env,
        stdout=boot_fp, stderr=boot_fp)
    try:
        if not _wait_health(f"http://127.0.0.1:{port}/api/health",
                            proc=proc):
            print(f"[grade] 应用健康探针超时——起服失败（启动日志: {boot_log}）")
            try:
                tail = boot_log.read_text(encoding="utf-8", errors="replace"
                                          ).splitlines()[-12:]
                for line in tail:
                    print("  " + line[:160])
            except Exception:
                pass
            return 2
        print(f"[grade] 应用就绪: http://127.0.0.1:{port}", flush=True)

        report = args.report or str(GRADE_DIR / "grade-report.json")
        env2 = dict(os.environ, TARGET_URL=f"http://127.0.0.1:{port}",
                    GRADE_REPORT=report,
                    PLAYWRIGHT_TEST_DIR=f"./specs/{args.task}",
                    PLAYWRIGHT_OUTPUT_DIR=str(GRADE_DIR / "test-results"))
        npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
        proc_test = subprocess.run(
            [npx, "playwright", "test"],
            cwd=str(GRADE_DIR), env=env2,
            capture_output=True, text=True, timeout=7200)  # 66 题单 worker 实测 ~60min，3600s 卡线强杀（9/22 so 取证）
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
        try:
            boot_fp.close()
        except Exception:
            pass
        # Windows：terminate 不杀孙进程——孤儿 Flask 服务器会锁死
        # 模板目录与端口（2026-09-20 深夜取证：连环健康探针超时/
        # 目录锁的总根源），taskkill /T 连树击杀
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
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
            # Playwright JSON 报告的状态字面量是 passed/failed/timedOut
            # （"expected" 是 expectedStatus 字段——04:45 取证：写错字面量
            # 把真实通过分报成 0）
            ok = all(t.get("status") == "passed"
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
