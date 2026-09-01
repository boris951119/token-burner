"""README 重写提交 + 推送。"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "c.log"


def run(args, timeout=60):
    r = subprocess.run(args, cwd=str(ROOT), capture_output=True, timeout=timeout)
    return (r.stdout or b"").decode("utf-8", "replace") + \
        (r.stderr or b"").decode("utf-8", "replace")


lines = ["=== add/commit ==="]
lines.append(run(["git", "add", "README.md"]))
lines.append(run(["git", "commit", "-m",
                  "docs: README 重写至 v0.5.0-beta 口径（功能全景/三入口/配置表/发布与文档指引）"]))
lines.append("=== push ===")
push = subprocess.run(
    [sys.executable, "scripts/git_push_api.py",
     "https://github.com/boris951119/token-burner"],
    cwd=str(ROOT), env=dict(os.environ), capture_output=True, text=True,
    encoding="utf-8", errors="replace", timeout=600,
)
lines.append((push.stdout or "") + (push.stderr or "") + f"\nexit:{push.returncode}")
lines.append("=== status ===")
lines.append(run(["git", "status", "--short"]))
OUT.write_text("\n".join(lines), encoding="utf-8")
print("done")
