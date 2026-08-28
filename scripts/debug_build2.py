"""用 dump_ours.json 的真实清单数据复现 sync_local 的树构建，定位 sha 分歧。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".vendor"))

from dulwich.objects import Tree
from dulwich.repo import Repo

ROOT = Path(__file__).resolve().parent.parent
repo = Repo(str(ROOT))

data = json.loads((ROOT / "dump_ours.json").read_text(encoding="utf-8"))
entries = [(p, m, s, t) for p, m, t, s in data["entries"]]
print(f"entries: {len(entries)}")


def build(prefix: str):
    t = Tree()
    files = [(p, m, s) for p, m, s, ty in entries
             if ty == "blob" and p.startswith(prefix)
             and "/" not in p[len(prefix):]]
    dirs = sorted({p[len(prefix):].split("/")[0] for p, _m, _s, ty in entries
                   if ty == "blob" and p.startswith(prefix)
                   and "/" in p[len(prefix):]})
    for rel, mode, sha in files:
        t.add(rel.encode(), int(mode, 8), sha.encode())
    for d in dirs:
        sub_id = build(f"{prefix}{d}/")
        t.add(d.encode(), 0o040000, sub_id)
    repo.object_store.add_object(t)
    return t.id


# 单独看 app/agents
agents = build("app/agents/")
print("app/agents built:", agents.decode()[:12], "(期望 380a16c1)")
existing = repo[b"380a16c1baf29c30a47d144aa0f6f0c8b023183b"]
built = repo[agents]
print("built items:  ", sorted((n, m, s) for n, m, s in built.items()))
print("existing items:", sorted((n, m, s) for n, m, s in existing.items()))

root = build("")
print("root built:", root.decode()[:12], "(期望", data["tree"][:12] + ")")
