"""重建本地树并与远端 recursive 清单逐子树比对，定位 sha 分歧点。"""

import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".vendor"))

from dulwich.objects import Blob, Tree
from dulwich.repo import Repo

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"


def api_get(path: str) -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "User-Agent": "token-burner-debug",
                 "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    repo = Repo(str(ROOT))
    ref = api_get("/repos/boris951119/token-burner/git/ref/heads/main")
    commit = api_get(
        f"/repos/boris951119/token-burner/git/commits/{ref['object']['sha']}"
    )
    listing = api_get(
        f"/repos/boris951119/token-burner/git/trees/"
        f"{commit['tree']['sha']}?recursive=1"
    )
    entries = [(e["path"], e["mode"], e["sha"], e["type"])
               for e in listing["tree"]]
    tree_map = {p: s for p, m, s, t in entries if t == "tree"}
    print(f"远端树: {commit['tree']['sha'][:12]}  blobs={len(entries) - len(tree_map)} trees={len(tree_map)}")

    for path, _m, sha, typ in entries:
        if typ != "blob":
            continue
        if sha.encode() in repo.object_store:
            continue
        blob = Blob()
        if (ROOT / path).is_file():
            blob.data = (ROOT / path).read_bytes()
        else:
            b = api_get(
                f"/repos/boris951119/token-burner/git/blobs/{sha}"
            )
            blob.data = base64.b64decode(b["content"])
        if blob.id != sha.encode():
            print(f"  blob sha 不匹配: {path} local={blob.id.decode()[:8]} remote={sha[:8]}")
        repo.object_store.add_object(blob)

    def build(prefix: str, depth: int) -> bytes:
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
            sub_id = build(f"{prefix}{d}/", depth + 1)
            expected = tree_map.get(f"{prefix}{d}")
            if expected and sub_id.decode() != expected:
                print(f"  子树 sha 分歧: {prefix}{d} 本地={sub_id.decode()[:8]} 远端={expected[:8]}")
            elif not expected:
                print(f"  远端清单缺子树: {prefix}{d} 本地={sub_id.decode()[:8]}")
            t.add(d.encode(), 0o040000, sub_id)
        repo.object_store.add_object(t)
        return t.id

    root_id = build("", 0)
    print(f"本地重建根树: {root_id.decode()[:12]}")
    if root_id.decode() == commit["tree"]["sha"]:
        print("根树一致！")
    # 根级条目对照
    remote_root = api_get(
        f"/repos/boris951119/token-burner/git/trees/{commit['tree']['sha']}"
    )
    local_root: Tree = repo[root_id]
    remote_set = {(e["path"], e["mode"], e["sha"]) for e in remote_root["tree"]}
    local_set = {(n.decode(), f"{m:04o}", s.decode()) for n, m, s in local_root.items()}
    for p, m, s in sorted(remote_set - local_set):
        print(f"  仅远端(根): {p} {m} {s[:8]}")
    for p, m, s in sorted(local_set - remote_set):
        print(f"  仅本地(根): {p} {m} {s[:8]}")


if __name__ == "__main__":
    main()
