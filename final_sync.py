"""最终收尾：提交 sync 残留 + 推送 + 终态验证。"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "f.log"


def run(args, timeout=60):
    r = subprocess.run(args, cwd=str(ROOT), capture_output=True, timeout=timeout)
    return (r.stdout or b"").decode("utf-8", "replace") + \
        (r.stderr or b"").decode("utf-8", "replace")


lines = ["=== add/commit ==="]
lines.append(run(["git", "add", "-A"]))
lines.append(run(["git", "commit", "-m", "chore: 同步收尾"]))
lines.append("=== push ===")
push = subprocess.run(
    [sys.executable, "scripts/git_push_api.py",
     "https://github.com/boris951119/token-burner"],
    cwd=str(ROOT), env=dict(os.environ), capture_output=True, text=True,
    encoding="utf-8", errors="replace", timeout=600,
)
lines.append((push.stdout or "") + (push.stderr or "") + f"\nexit:{push.returncode}")
lines.append("=== FINAL ===")
lines.append(run(["git", "status", "--short"]))
lines.append(run(["git", "log", "--oneline", "-3"]))
lines.append(run(["git", "rev-parse", "HEAD"]))
OUT.write_text("\n".join(lines), encoding="utf-8")
print("done")
