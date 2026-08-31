# -*- coding: utf-8 -*-
"""git push + 远端核验（一次性，完整输出落盘）。"""
import json
import subprocess
import urllib.request

TOKEN = "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"
URL = f"https://{TOKEN}@github.com/boris951119/token-burner.git"
OUT = r"E:\token-burner\_push_detail.txt"

lines: list[str] = []

push = subprocess.run(
    ["git", "push", URL, "HEAD:main"],
    cwd=r"E:\token-burner", capture_output=True, text=True,
    encoding="utf-8", errors="replace", timeout=120,
)
lines.append(f"push rc={push.returncode}")
lines.append(f"push stdout:\n{push.stdout}")
lines.append(f"push stderr:\n{push.stderr}")

try:
    req = urllib.request.Request(
        "https://api.github.com/repos/boris951119/token-burner/git/ref/heads/main",
        headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "tb-verify"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        remote = json.loads(r.read().decode())["object"]["sha"]
    lines.append(f"remote main={remote}")
except Exception as e:  # noqa: BLE001
    lines.append(f"remote check error: {e!r}")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
