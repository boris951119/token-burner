"""推送前检查：无旧推送进程逃逸 + 记录本地 HEAD。"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent

r = subprocess.run(
    ["wmic", "process", "where", "name like 'python%'", "get",
     "processid,commandline", "/format:list"],
    capture_output=True, text=True, encoding="utf-8", errors="replace",
)
r2 = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
)
(ROOT / "pre_push.txt").write_text(
    r.stdout + "\nHEAD=" + r2.stdout.strip(), encoding="utf-8"
)
print("ok")
