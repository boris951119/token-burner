"""收尾提交（行尾归一 + 脚本删除同步远端）+ 推送 + 验证。"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "final_out.log"


def run(args: list[str], timeout=60):
    r = subprocess.run(args, cwd=str(ROOT), capture_output=True, timeout=timeout)
    return (r.stdout or b"").decode("utf-8", "replace") + \
        (r.stderr or b"").decode("utf-8", "replace")


lines = ["=== commit ==="]
lines.append(run(["git", "commit", "-m",
                  "chore: 行尾归一与推送辅助脚本清理同步"]))
lines.append("=== push ===")
push = subprocess.run(
    [sys.executable, "scripts/git_push_api.py",
     "https://github.com/boris951119/token-burner"],
    cwd=str(ROOT), env=dict(os.environ), capture_output=True, text=True,
    encoding="utf-8", errors="replace", timeout=600,
)
lines.append((push.stdout or "") + (push.stderr or "") + f"\nexit:{push.returncode}")
lines.append("=== log ===")
lines.append(run(["git", "log", "--oneline", "-3"]))
lines.append("=== status ===")
lines.append(run(["git", "status", "--short"]))
OUT.write_text("\n".join(lines), encoding="utf-8")
print("done")
