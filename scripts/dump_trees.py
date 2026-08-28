"""导出远端两个提交的树清单（JSON 落盘，供人工比对）。"""

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"


def api_get(path: str) -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "User-Agent": "token-burner-dump",
                 "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def dump(commit_sha: str, name: str) -> None:
    commit = api_get(
        f"/repos/boris951119/token-burner/git/commits/{commit_sha}"
    )
    tree_sha = commit["tree"]["sha"]
    listing = api_get(
        f"/repos/boris951119/token-burner/git/trees/{tree_sha}?recursive=1"
    )
    out = {
        "commit": commit_sha,
        "message": commit["message"],
        "tree": tree_sha,
        "truncated": listing.get("truncated", False),
        "entries": sorted(
            (e["path"], e["mode"], e["type"], e["sha"])
            for e in listing["tree"]
        ),
    }
    path = ROOT / f"dump_{name}.json"
    path.write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"{name}: commit {commit_sha[:12]} tree {tree_sha[:12]} "
          f"entries={len(out['entries'])} truncated={out['truncated']}")


if __name__ == "__main__":
    # 服务器主线
    ref = api_get("/repos/boris951119/token-burner/git/ref/heads/main")
    dump(ref["object"]["sha"], "head")
    # 我们推的提交（从列表取全 sha）
    commits = api_get(
        "/repos/boris951119/token-burner/commits?per_page=10"
    )
    for c in commits:
        if c["sha"].startswith("ad2afd24"):
            dump(c["sha"], "ours")
            break
