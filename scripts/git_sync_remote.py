"""拉取远端初始化提交并与本地合并后推送（不覆盖远端内容）。

场景：GitHub 仓库创建时自带 README/初始化提交，本地已有首次提交。
做法：
  1. fetch 远端 main；
  2. 合并树 = 本地树 ∪ 远端独有文件（递归合并目录，冲突即中止）；
  3. 生成双亲合并提交（保留两侧历史）；
  4. 推送 main（快进，绝不 force）。

用法（沙箱外）：
    $env:GITHUB_TOKEN = "<PAT>"
    python scripts/git_sync_remote.py https://github.com/<用户名>/<仓库名>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".vendor"))

from dulwich import porcelain
from dulwich.client import get_transport_and_path
from dulwich.objects import Commit, Tree
from dulwich.repo import Repo

AUTHOR = b"token-burner <jarvis@local>"
_LOG = Path(__file__).resolve().parent.parent / "sync_progress.log"


def log(msg: str) -> None:
    """进度落盘（进程被杀也能看到卡点）。"""
    with open(_LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
        f.flush()
    print(msg, flush=True)


def merge_trees(repo: Repo, ours_id: bytes, theirs_id: bytes) -> bytes:
    """递归合并两棵树：同路径同名条目必须相同，否则报冲突。返回新树 id。"""
    ours: Tree = repo[ours_id]
    theirs: Tree = repo[theirs_id]
    our_map = {name: (mode, sha) for name, mode, sha in ours.items()}
    their_map = {name: (mode, sha) for name, mode, sha in theirs.items()}

    merged = Tree()
    for name in sorted(set(our_map) | set(their_map)):
        if name not in our_map:
            mode, sha = their_map[name]
            merged.add(name, mode, sha)
        elif name not in their_map:
            mode, sha = our_map[name]
            merged.add(name, mode, sha)
        else:
            m1, s1 = our_map[name]
            m2, s2 = their_map[name]
            if m1 == m2 and s1 == s2:
                merged.add(name, m1, s1)
            elif m1 == 0o040000 and m2 == 0o040000:
                merged.add(name, 0o040000, merge_trees(repo, s1, s2))
            else:
                raise RuntimeError(f"合并冲突: {name.decode(errors='replace')}")
    repo.object_store.add_object(merged)
    return merged.id


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python scripts/git_sync_remote.py <仓库URL>")
        return 2
    url = sys.argv[1].removesuffix(".git") + ".git"
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("缺少 GITHUB_TOKEN 环境变量。")
        return 2

    root = Path(__file__).resolve().parent.parent
    repo = Repo(str(root))
    local = repo.refs[b"refs/heads/main"]
    log(f"开始: 本地 main = {local.decode()[:12]}")

    # 1. 直连远端：取引用 + 拉取对象
    client, path = get_transport_and_path(url, username="token", password=token)
    log("已创建 client，开始 get_refs ...")
    ls = client.get_refs(path.encode())
    log("get_refs 完成")
    remote_refs = ls.refs if hasattr(ls, "refs") else dict(ls)
    remote = remote_refs.get(b"refs/heads/main")
    if remote is None:
        log("远端无 main 分支。")
        return 1
    log(f"本地: {local.decode()[:12]}  远端: {remote.decode()[:12]}")

    if remote == local:
        log("本地与远端一致，无需合并。")
        return 0
    if repo[remote].parents == (local,):
        log("远端已包含本地提交。")
        return 0
    # 拉取远端对象（只取缺失的）
    log("开始 fetch ...")
    client.fetch(path.encode(), repo,
                 determine_wants=lambda refs: [remote] if remote not in repo
                 else [])
    log("fetch 完成")

    # 2. 合并树（远端 README 等独有文件并入本地树）
    merged_tree = merge_trees(
        repo, repo[local].tree, repo[remote].tree
    )

    # 3. 双亲合并提交（保留两侧历史）
    import time as _time
    now = int(_time.time())
    merge_commit = Commit()
    merge_commit.tree = merged_tree
    merge_commit.parents = [local, remote]
    merge_commit.author = AUTHOR
    merge_commit.committer = AUTHOR
    merge_commit.author_time = now
    merge_commit.commit_time = now
    merge_commit.author_timezone = 8 * 3600  # Asia/Shanghai
    merge_commit.commit_timezone = 8 * 3600
    merge_commit.message = "合并远端初始化提交（README 等）".encode("utf-8")
    repo.object_store.add_object(merge_commit)
    repo.refs[b"refs/heads/main"] = merge_commit.id
    log(f"合并提交: {merge_commit.id.decode()[:12]}")

    # 4. 快进推送（远端 main 的内容已包含在合并提交的双亲中）
    log("开始 push ...")
    porcelain.push(
        repo,
        remote_location=url,
        refspecs=[b"refs/heads/main:refs/heads/main"],
        username="token",
        password=token,
    )
    log(f"推送完成: refs/heads/main -> {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
