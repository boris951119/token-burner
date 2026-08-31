# -*- coding: utf-8 -*-
"""验证远端 main SHA 与本地 HEAD 是否一致（一次性）。"""
import json
import subprocess
import urllib.request

TOKEN = "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"
req = urllib.request.Request(
    "https://api.github.com/repos/boris951119/token-burner/git/ref/heads/main",
    headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "tb-verify"},
)
with urllib.request.urlopen(req, timeout=30) as r:
    remote = json.loads(r.read().decode())["object"]["sha"]

local = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=r"E:\token-burner",
    capture_output=True, text=True,
).stdout.strip()

with open(r"E:\token-burner\_sync_check.txt", "w", encoding="utf-8") as f:
    f.write(f"local ={local}\nremote={remote}\nmatch={local == remote}\n")
print("VERIFY_DONE")
