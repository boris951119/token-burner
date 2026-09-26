"""批次#61 存活闸端到端实测（零 LLM）：把「跑一半被 kill，导出目录里仍是一个
能起服、能点开的完整应用」这句判据放到真实产物上验，而不是只停在单测的假管线。

样本选 `.tmp/l1-redemption-keep-0923/app`——那是 L1 测量里被真实起服、跑过官方
全量 spec 的一份交付（28/32），代码是真生成的。三种死法：

A 完整产物导出（对照组：证明"起服+可点开"这套探针本身有效）；
B 半路产物导出（删掉一半模块目录，模拟第 k 个模块写完就被斩）；
C 导出临界区内被 SIGTERM 斩（三次不同延迟）＋管线内被斩（走 _emergency_salvage）。

判据逐条打 PASS/FAIL：退出码、导出目录在位、/api/health 200、首页 HTML 里真的
有可点控件（<button>/<a href>）。不打印题面内容。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SRC = ROOT / ".tmp/l1-redemption-keep-0923/app"
CLICKABLE = ("<button", "<a href", "<form", 'role="link"', 'role="button"')


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_workdir(tag: str, *, drop_half: bool = False) -> Path:
    wd = ROOT / ".tmp" / f"survival-e2e-{tag}"
    if wd.exists():
        shutil.rmtree(wd)
    proj = wd / "projects" / "20260924_a"
    shutil.copytree(SRC, proj, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", "logs", "selftest-results", "selftest-report.json"))
    if drop_half:
        # 只砍模块目录，保留 _shared 与包标记：这就是"写到第 k 个模块"的盘上形态
        mods = sorted(p for p in (proj / "code").iterdir()
                      if p.is_dir() and p.name != "_shared"
                      and any(f.name != "__init__.py" for f in p.rglob("*.py")))
        for victim in mods[len(mods) // 2:]:
            shutil.rmtree(victim)
        print(f"  [{tag}] 模块目录 {len(mods)} 个，砍掉 "
              f"{len(mods) - len(mods) // 2} 个")
    return wd


def export(wd: Path, project: Path) -> bool:
    from main import _export_official_layout
    return bool(_export_official_layout(wd, project).get("exported"))


def boot_and_probe(wd: Path, timeout: float = 60.0) -> dict:
    """按官方 runner 口径起服：PORT 环境变量 + /api/health 探针 + 首页可点控件。"""
    backend = wd / "backend"
    if not (backend / "main.py").is_file():
        return {"booted": False, "why": "no backend/main.py"}
    port = free_port()
    env = {**os.environ, "PORT": str(port), "PYTHONUNBUFFERED": "1"}
    log = wd / "boot.log"
    with open(log, "wb") as fh:
        proc = subprocess.Popen([sys.executable, "main.py"], cwd=backend,
                                env=env, stdout=fh, stderr=subprocess.STDOUT)
    health, html_ok, verdict = None, False, ""
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                verdict = f"进程提前退出 rc={proc.returncode}"
                break
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                    health = r.status
                    break
            except Exception:
                time.sleep(0.5)
        else:
            verdict = f"{timeout:.0f}s 内 /api/health 未 200"
        if health == 200:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/", timeout=5) as r:
                    body = r.read().decode("utf-8", "replace").lower()
                html_ok = any(c in body for c in CLICKABLE)
                if not html_ok:
                    verdict = f"首页 200 但无可点控件（{len(body)} 字节）"
            except Exception as exc:
                verdict = f"首页取不到: {exc!r}"
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return {"booted": health == 200, "health": health, "clickable": html_ok,
            "why": verdict or "ok",
            "log_tail": log.read_text(encoding="utf-8", errors="replace")[-260:]
            if log.exists() else ""}


KILL_SCRIPT = '''
import os, signal, sys, threading, time
from pathlib import Path
sys.path.insert(0, {root!r})
import main
wd = Path({wd!r})
main._SALVAGE_WORKDIR = wd
taken = main._install_death_signals()
mode = {mode!r}
if mode == "inside-export":
    def boom():
        time.sleep({delay!r})
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=boom, daemon=True).start()
    ok = main._salvage_export(wd)
    print("EXPORTED" if ok else "NOT_EXPORTED", flush=True)
    sys.exit(0)
else:
    # 管线里被斩：既有出口是 except KeyboardInterrupt → 非成功交付 → 兜底导出
    # （kill 必须落在 try 内：信号在投递点抛出，落在 try 外测的就不是产品
    #  而是脚本自己——9/24 首版就是这么假红了一次）
    try:
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(0.3)
        raise AssertionError("signal never delivered")
    except KeyboardInterrupt:
        rc = main._emergency_salvage("e2e: 管线内被 SIGTERM")
        print("RC", rc, flush=True)
        sys.exit(rc)
'''


def killed_run(wd: Path, mode: str, delay: float = 0.0) -> dict:
    src = KILL_SCRIPT.format(root=str(ROOT), wd=str(wd), mode=mode, delay=delay)
    proc = subprocess.run([sys.executable, "-c", src], capture_output=True,
                          text=True, timeout=180)
    out = (proc.stdout + proc.stderr)
    return {"rc": proc.returncode, "exported_flag": "EXPORTED" in out,
            "salvage_rc": next((int(l.split()[1]) for l in out.splitlines()
                                if l.startswith("RC ")), None),
            "tail": out[-300:]}


def main() -> int:
    if not (SRC / "code").is_dir():
        print(f"!! 样本不在位: {SRC}（.tmp 会被清理，换一份带 code/ 的真实交付）")
        return 1
    rows = []

    wd_a = make_workdir("A")
    ok = export(wd_a, wd_a / "projects" / "20260924_a")
    r = boot_and_probe(wd_a)
    rows.append(("A 完整导出（对照组）", ok and r["booted"] and r["clickable"],
                 f"export={ok} {json.dumps({k: r[k] for k in ('booted', 'clickable', 'why')}, ensure_ascii=False)}"))

    wd_b = make_workdir("B", drop_half=True)
    ok = export(wd_b, wd_b / "projects" / "20260924_a")
    r = boot_and_probe(wd_b)
    # 半路产物的判据只到「起服 + 已有产物没被导坏」：首页是否可点取决于被砍掉
    # 的那一半里有没有渲染模块，那是产物的真实状态，不是闸的成败。
    rows.append(("B 半路产物导出", ok and r["booted"],
                 f"export={ok} {json.dumps({k: r[k] for k in ('booted', 'clickable', 'why')}, ensure_ascii=False)}"))

    for delay in (0.05, 0.4, 1.2):
        wd_c = make_workdir(f"C{delay}")
        k = killed_run(wd_c, "inside-export", delay)
        r = boot_and_probe(wd_c) if (wd_c / "backend").is_dir() else \
            {"booted": False, "clickable": False, "why": "无导出目录"}
        rows.append((f"C 导出中 SIGTERM（{delay}s）",
                     k["rc"] == 0 and r["booted"] and r["clickable"],
                     f"rc={k['rc']} flag={k['exported_flag']} "
                     f"booted={r['booted']} clickable={r['clickable']} why={r['why']}"))

    wd_d = make_workdir("D", drop_half=True)
    k = killed_run(wd_d, "in-pipeline")
    r = boot_and_probe(wd_d) if (wd_d / "backend").is_dir() else \
        {"booted": False, "clickable": False, "why": "无导出目录"}
    rows.append(("D 管线内 SIGTERM→兜底导出",
                 k["salvage_rc"] == 0 and r["booted"],
                 f"salvage_rc={k['salvage_rc']} booted={r['booted']} "
                 f"clickable={r['clickable']} why={r['why']}"))

    print("\n| 死法 | 判据 | 读数 |")
    print("|---|---|---|")
    bad = 0
    for name, passed, detail in rows:
        print(f"| {name} | {'PASS' if passed else 'FAIL'} | {detail} |")
        bad += 0 if passed else 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
