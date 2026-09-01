"""V5 终极收尾：提交剩余差异 → 推送 → 输出最终状态。"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "final2_out.log"


def run(args: list[str], timeout=60):
    r = subprocess.run(args, cwd=str(ROOT), capture_output=True, timeout=timeout)
    return (r.stdout or b"").decode("utf-8", "replace") + \
        (r.stderr or b"").decode("utf-8", "replace")


lines = ["=== add all ==="]
lines.append(run(["git", "add", "-A"]))
lines.append("=== commit ===")
lines.append(run(["git", "commit", "-m",
                  "chore: 行尾归一收尾（v0.5 Beta 交付终态）"]))
lines.append("=== push ===")
push = subprocess.run(
    [sys.executable, "scripts/git_push_api.py",
     "https://github.com/boris951119/token-burner"],
    cwd=str(ROOT), env=dict(os.environ), capture_output=True, text=True,
    encoding="utf-8", errors="replace", timeout=600,
)
lines.append((push.stdout or "") + (push.stderr or "") + f"\nexit:{push.returncode}")
lines.append("=== final status ===")
lines.append(run(["git", "status", "--short"]))
lines.append("=== final log ===")
lines.append(run(["git", "log", "--oneline", "-6"]))
lines.append("=== tracked count ===")
lines.append(run(["git", "ls-files"]))
OUT.write_text("\n".join(lines), encoding="utf-8")
print("done")
