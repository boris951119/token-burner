"""V5 推送：token 从环境变量读取，结果落盘 push_v5_out.log。"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

r = subprocess.run(
    [sys.executable, "scripts/git_push_api.py",
     "https://github.com/boris951119/token-burner"],
    cwd=str(ROOT),
    env=dict(os.environ),
    capture_output=True, text=True,
    encoding="utf-8", errors="replace", timeout=900,
)
(ROOT / "push_v5_out.log").write_text(
    (r.stdout or "") + "\n--- stderr ---\n" + (r.stderr or "")
    + f"\nexit:{r.returncode}",
    encoding="utf-8",
)
print("exit:", r.returncode)
