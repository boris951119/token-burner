# -*- coding: utf-8 -*-
"""后台轮询任务至终态并落盘结果 JSON（供验收脚本链复用）。"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
task_id = sys.argv[1]
out_path = sys.argv[2]

deadline = time.monotonic() + 2400
while time.monotonic() < deadline:
    with urllib.request.urlopen(f"{BASE}/api/tasks/{task_id}", timeout=60) as r:
        s = json.loads(r.read().decode("utf-8"))
    if s["status"] in ("succeeded", "failed", "cancelled"):
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
        print(f"TERMINAL {s['status']} tokens={s['tokens_used']}")
        sys.exit(0)
    time.sleep(15)
print("STILL_RUNNING")
sys.exit(3)
