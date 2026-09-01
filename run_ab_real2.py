"""真实 A/B 复跑（第二轮稳定性对照）：密钥走环境变量，结果落盘。"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

env = dict(os.environ)
env["OPENAI_API_KEY"] = os.environ["ZHIPU_KEY"]
env["OPENAI_API_BASE"] = "https://open.bigmodel.cn/api/paas/v4"
env["OPENAI_BASE_URL"] = "https://open.bigmodel.cn/api/paas/v4"

r = subprocess.run(
    [sys.executable, "scripts/ab_triage_eval.py", "--real"],
    cwd=str(ROOT), env=env,
    capture_output=True, text=True,
    encoding="utf-8", errors="replace", timeout=900,
)
(ROOT / "ab_real2_out.log").write_text(
    (r.stdout or "") + "\n--- stderr ---\n" + (r.stderr or "")
    + f"\nexit:{r.returncode}",
    encoding="utf-8",
)
print("exit:", r.returncode)
