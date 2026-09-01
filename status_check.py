"""查全量回归状态：进程 / exit 文件 / 日志 mtime。"""

import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
out = [f"now={time.time():.0f}"]

for name in ("pytest_v2.log", "pytest_v2.exit", "pytest_v1.log"):
    p = ROOT / name
    if p.exists():
        out.append(f"{name}: mtime={p.stat().st_mtime:.0f} size={p.stat().st_size}")
    else:
        out.append(f"{name}: MISSING")

r = subprocess.run(
    ["wmic", "process", "where", "name like 'python%'", "get",
     "processid,commandline", "/format:list"],
    capture_output=True, text=True, encoding="utf-8", errors="replace",
)
out.append("--- python processes ---")
out.append(r.stdout)

(ROOT / "full_status.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")
