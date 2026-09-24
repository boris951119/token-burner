"""批次#63 前置度量（零 LLM）：40 份已知交付按**今天的**导出与启动器重跑一遍
「能不能起服」，给"导出前保底门闸"定频次依据。

为什么现在要重测：批次#49 那轮量到入口发现致死 7/39＝18%，但那时还没有
①拼接机械化（AST 扫蓝图/路由器确定性生成 create_app）、②/api/health 机械补挂、
③导出原子换入 这三件事。致死率可能已经掉下来——掉下来就不该再占一个上传位。

口径与官方 runner 对齐：PORT 环境变量起 backend/main.py → 轮询 /api/health →
再取首页 HTML。分类死因（不猜，逐条留原始日志尾巴）：
  ok            起服 200 且首页有 HTML
  no-health     窗口内 /api/health 始终拿不到 200（进程死了/端口没起）
  health-only   health 200 但首页取不到（404/500）＝批次#61 里半产品的形状
  no-clickable  首页 200 但没有任何可点控件（纯 JSON 出口）
慢样本单独记：health 若接近窗口上限，说明 20s 会造出假红，得加窗口重跑那一份。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CONTROL = ROOT / ".tmp/probe-v42/control"
WORK = ROOT / ".tmp/boot-floor"
HEALTH_WINDOW = float(os.environ.get("BF_WINDOW", "20"))
CLICKABLE = ("<button", "<a href", "<form", 'role="link"', 'role="button"',
             "<input", "<select", "<textarea")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def probe(wd: Path) -> dict:
    backend = wd / "backend"
    if not (backend / "main.py").is_file():
        return {"kind": "no-launcher", "secs": 0.0}
    port = free_port()
    t0 = time.time()
    log = wd / "boot.log"
    env = {**os.environ, "PORT": str(port), "PYTHONUNBUFFERED": "1"}
    with open(log, "wb") as fh:
        proc = subprocess.Popen([sys.executable, "main.py"], cwd=backend,
                                env=env, stdout=fh, stderr=subprocess.STDOUT)
    kind, status = "no-health", None
    try:
        while time.time() - t0 < HEALTH_WINDOW:
            if proc.poll() is not None:
                kind = "dead-on-boot"
                break
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                    if r.status == 200:
                        status = 200
                        break
            except Exception:
                time.sleep(0.4)
        if status == 200:
            kind = "health-only"
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/", timeout=5) as r:
                    body = r.read().decode("utf-8", "replace").lower()
                if "<html" in body or "<!doctype" in body:
                    kind = "ok" if any(c in body for c in CLICKABLE) \
                        else "no-clickable"
            except Exception as exc:
                kind = f"health-only:{type(exc).__name__}"
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return {"kind": kind.split(":")[0], "detail": kind, "secs": round(
        time.time() - t0, 1),
        "log": log.read_text(encoding="utf-8", errors="replace")[-200:]
        if log.exists() else ""}


def main() -> int:
    if not CONTROL.is_dir():
        print(f"!! 对照集不在位: {CONTROL}")
        return 1
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    from app.platform_export import export_platform_layout

    dirs = sorted(p for p in CONTROL.iterdir() if (p / "code").is_dir())
    rows = []
    for src in dirs:
        wd = WORK / src.name
        proj = wd / "projects" / "p"
        wd.mkdir(parents=True)
        shutil.copytree(src, proj, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", "logs", "*.db"))
        try:
            export_platform_layout(wd, proj)
        except Exception as exc:
            rows.append((src.name[:2], "export-fail", 0.0, "export-fail",
                         repr(exc)[:150]))
            continue
        r = probe(wd)
        rows.append((src.name[:2], r["kind"], r["secs"], r.get("detail", ""),
                     r.get("log", "").strip().splitlines()[-1][:150]
                     if r.get("log", "").strip() else ""))
        print(f"  {src.name[:2]} {r.get('detail', r['kind']):<26} {r['secs']:>5.1f}s"
              f"  {rows[-1][4][:90]}", flush=True)
        shutil.rmtree(proj, ignore_errors=True)   # 每份 20MB，逐份回收

    tally: dict[str, int] = {}
    for _, _, _, detail, _log in rows:
        tally[detail] = tally.get(detail, 0) + 1
    slow = [(n, s) for n, _, s, _, _ in rows if s > HEALTH_WINDOW * 0.7]
    print("\n| 死因分类（含首页取不到的具体形态） | 份数 |")
    print("|---|---|")
    for kind, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"| {kind} | {n}/{len(rows)} |")
    print(f"\n慢样本（>={HEALTH_WINDOW * 0.7:.0f}s，窗口可能造出假红）：{slow}")
    bad = [n for n, k, _, _, _ in rows if k not in ("ok",)]
    print(f"非 ok 合计: {len(bad)}/{len(rows)} → {', '.join(bad) or '无'}")
    out = ROOT / ".tmp/boot-floor-readings.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"读数落盘: {out}")
    shutil.rmtree(WORK, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
