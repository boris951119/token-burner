"""验证推送结果：对比远端/本地引用与提交结构。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".vendor"))

from dulwich.client import get_transport_and_path
from dulwich.repo import Repo

out = []
client, path = get_transport_and_path(
    "https://github.com/boris951119/token-burner.git",
    username="token",
    password="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",
)
ls = client.get_refs(path.encode())
refs = ls.refs if hasattr(ls, "refs") else dict(ls)
for k, v in sorted(refs.items()):
    out.append(f"REMOTE: {k.decode()} {v.decode()[:12]}")

repo = Repo(r"e:\token-burner")
main = repo.refs[b"refs/heads/main"]
out.append(f"LOCAL main: {main.decode()[:12]}")
head = repo[main]
out.append(f"parents: {[p.decode()[:12] for p in head.parents]}")
out.append(f"message: {head.message.decode('utf-8', errors='replace')}")
out.append(f"tree: {sorted(n.decode() for n in repo[head.tree])}")

result = "\n".join(out)
Path(r"e:\token-burner\push_verify.txt").write_text(result, encoding="utf-8")
print(result)
