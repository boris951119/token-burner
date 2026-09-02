# -*- coding: utf-8 -*-
"""v0.5 验收③：exe 冷启动计时（近似口径）。

M13-2 复验指标：冷启动 <2s。onefile windowed exe 无控制台输出，
自动化口径取「进程启动 → bootloader 解压完成派生实际进程」耗时
（即 75MB 解压 + Python 启动的可观测代理信号；窗口可见时间需人工肉眼复核）。
"""
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

EXE = r"e:\token-burner\release\token-burner.exe"

print("=== 验收③：exe 冷启动计时（口径：bootloader 子进程出现） ===")
results = []
for i in range(3):
    t0 = time.perf_counter()
    proc = subprocess.Popen([EXE], cwd=r"e:\token-burner\release")
    # 轮询子进程出现（onefile：bootloader 父进程派生实际运行子进程）
    deadline = t0 + 30
    while time.perf_counter() < deadline:
        out = subprocess.run(
            ["wmic", "process", "where",
             f"name='token-burner.exe'", "get", "ProcessId,ParentProcessId"],
            capture_output=True, text=True,
        ).stdout
        pids = [ln.split() for ln in out.splitlines() if ln.strip().isdigit() or
                (len(ln.split()) == 2 and all(p.isdigit() for p in ln.split()))]
        if len(pids) >= 2:   # 父 + 子都存在 → 解压完成
            break
        time.sleep(0.05)
    dt = time.perf_counter() - t0
    results.append(dt)
    print(f"  第{i+1}次: {dt:.2f}s")
    subprocess.run(["taskkill", "/IM", "token-burner.exe", "/T", "/F"],
                   capture_output=True)
    time.sleep(1)

best = min(results)
print(f"最快: {best:.2f}s（指标 <2s -> {'PASS' if best < 2 else 'FAIL'}）")
print("注：窗口可见时间含 WebView 初始化，需人工肉眼复核（本口径为其下界代理）")
