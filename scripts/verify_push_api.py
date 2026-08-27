"""验证 GitHub 远端状态：列出 main 分支提交（urllib，15s 超时）。"""

import json
import urllib.request
from pathlib import Path

TOKEN = "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"
URL = "https://api.github.com/repos/boris951119/token-burner/commits?per_page=5"

req = urllib.request.Request(URL, headers={
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent": "token-burner-verify",
    "Accept": "application/vnd.github+json",
})
with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read().decode("utf-8"))

lines = []
for c in data:
    lines.append(f"{c['sha'][:12]}  {c['commit']['message'].splitlines()[0]}  parents={len(c['parents'])}")
out = "\n".join(lines)
Path(r"e:\token-burner\push_verify.txt").write_text(out, encoding="utf-8")
print(out)
