"""第二轮报告入库 + 提交 + 推送。"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "commit_out.log"


def run(args, timeout=60):
    r = subprocess.run(args, cwd=str(ROOT), capture_output=True, timeout=timeout)
    return (r.stdout or b"").decode("utf-8", "replace") + \
        (r.stderr or b"").decode("utf-8", "replace")


lines = ["=== add/commit ==="]
lines.append(run(["git", "add", "scripts/ab_triage_eval.py",
                  "logs/ab_reports/ab_20260901_145806.json"]))
lines.append(run(["git", "commit", "-m",
                  "test: 真实 A/B 评测第二轮复跑（结论可复现：承接 50%、双模式 token 负收益 -141%、KPI 未达）"]))
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
