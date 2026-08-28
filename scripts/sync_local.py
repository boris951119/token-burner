"""推送后的本地同步：按远端 main 的真实数据重建本地提交链。

流程：
  1. GET ref/heads/main → 沿父链收集本地缺失的提交（最旧在前）
  2. 对每个缺失提交：拉取递归树清单 → 补齐 blob → 重建 tree →
     重建 commit 原始对象并校验 sha：
       - 签名提交（如网页端提交）：用 verification.payload + gpgsig 逐字节重建
       - 未签名提交：按 author/committer 元数据生成候选（时区 × 消息尾换行）
  3. 全部命中后前移本地 main；并把远端有而本地磁盘缺失的文件落盘
     （EXCLUDE 落盘排除清单除外——本地刻意删除的文件不恢复）

用法（沙箱外）：
    $env:GITHUB_TOKEN = "<PAT>"
    python scripts/sync_local.py https://github.com/<用户名>/<仓库名>
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".vendor"))

from dulwich.objects import Blob, ShaFile, Tree
from dulwich.repo import Repo

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"

# 本地刻意删除、不随同步恢复的路径（含泄露 token 的调试脚本）
EXCLUDE = {"scripts/verify_push.py", "scripts/verify_push_api.py"}


def api_call(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "token-burner-sync",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def tz_str(offset_seconds: int) -> str:
    sign = "+" if offset_seconds >= 0 else "-"
    off = abs(offset_seconds)
    return f"{sign}{off // 3600:02d}{(off % 3600) // 60:02d}"


def epoch(iso_date: str) -> int:
    dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    return int(dt.timestamp())


def build_tree(repo: Repo, entries: list, prefix: str) -> Tree:
    """自底向上建树（git 排序由 dulwich 序列化处理）。"""
    t = Tree()
    files = [(p, m, s) for p, m, s, ty in entries
             if ty == "blob" and p.startswith(prefix)
             and "/" not in p[len(prefix):]]
    dirs = sorted({p[len(prefix):].split("/")[0] for p, _m, _s, ty in entries
                   if ty == "blob" and p.startswith(prefix)
                   and "/" in p[len(prefix):]})
    for rel, mode, sha in files:
        name = rel[len(prefix):]  # 树内条目用相对名
        t.add(name.encode(), int(mode, 8), sha.encode())
    for d in dirs:
        sub = build_tree(repo, entries, f"{prefix}{d}/")
        t.add(d.encode(), 0o040000, sub.id)
    repo.object_store.add_object(t)
    return t


def ensure_blobs(repo: Repo, entries: list, owner_repo: str, token: str) -> None:
    """缺的 blob 从磁盘或 API 补齐（远端是事实源，磁盘内容不符时以 API 为准）。"""
    for path, _mode, sha, typ in entries:
        if typ != "blob" or sha.encode() in repo.object_store:
            continue
        blob = Blob()
        if (ROOT / path).is_file():
            blob.data = (ROOT / path).read_bytes()
            if blob.id == sha.encode():
                repo.object_store.add_object(blob)
                continue
        b = api_call("GET", f"/repos/{owner_repo}/git/blobs/{sha}", token)
        blob.data = base64.b64decode(b["content"])
        if blob.id != sha.encode():
            raise RuntimeError(f"blob sha 不匹配: {path}")
        repo.object_store.add_object(blob)


def signed_raw_candidates(payload: str, sig: str) -> list[bytes]:
    """payload + gpgsig 头 → 原始 commit 对象字节（多候选消歧）。"""
    head, _, msg = payload.partition("\n\n")
    out: list[bytes] = []
    for sig_body in (sig.rstrip("\n"), sig):
        lines = sig_body.split("\n")
        # armor 内的空行编码为「单个空格」行（git 头部续行规则）
        gpg = "gpgsig " + lines[0] + "".join("\n " + l for l in lines[1:])
        for m in (msg, msg + "\n"):
            out.append((head + "\n" + gpg + "\n\n" + m).encode("utf-8"))
    return out


def unsigned_raw_candidates(cj: dict, tree_sha: str) -> list[bytes]:
    """按元数据生成候选（时区 × 消息尾换行 × 提交者行）。"""
    a, c = cj["author"], cj["committer"]
    parents = [p["sha"] for p in cj["parents"]]
    msg = cj["message"].encode("utf-8")
    a_ts, c_ts = epoch(a["date"]), epoch(c["date"])
    out: list[bytes] = []
    for tz in (0, 8 * 3600):
        head = f"tree {tree_sha}\n"
        head += "".join(f"parent {p}\n" for p in parents)
        head += f"author {a['name']} <{a['email']}> {a_ts} {tz_str(tz)}\n"
        head += f"committer {c['name']} <{c['email']}> {c_ts} {tz_str(tz)}\n"
        for m in (msg, msg + b"\n"):
            out.append(head.encode() + b"\n" + m)
    return out


def sync(owner_repo: str, token: str) -> int:
    """核心同步逻辑：供本脚本 CLI 与 git_push_api 推送后复用。"""
    repo = Repo(str(ROOT))
    remote_sha = api_call("GET", f"/repos/{owner_repo}/git/ref/heads/main", token
                          )["object"]["sha"]

    # 1. 沿父链收集本地缺失的提交（最旧在前）
    chain: list[dict] = []
    sha = remote_sha
    while sha.encode() not in repo.object_store:
        cj = api_call("GET", f"/repos/{owner_repo}/git/commits/{sha}", token)
        chain.append(cj)
        parents = cj["parents"]
        if not parents:
            break
        sha = parents[0]["sha"]
    chain.reverse()
    if not chain:
        print(f"本地已是最新（{remote_sha[:12]}），无需同步。")
        return 0
    print(f"远端 main: {remote_sha[:12]}  待重建提交: {len(chain)} 个")

    # 2. 逐个重建（树 + blob + commit 原始对象）
    for cj in chain:
        tree_sha = cj["tree"]["sha"]
        listing = api_call(
            "GET", f"/repos/{owner_repo}/git/trees/{tree_sha}?recursive=1", token,
        )
        if listing.get("truncated"):
            print(f"树清单被截断: {tree_sha[:12]}，中止。")
            return 1
        entries = [(e["path"], e["mode"], e["sha"], e["type"])
                   for e in listing.get("tree", [])]
        ensure_blobs(repo, entries, owner_repo, token)
        new_tree = build_tree(repo, entries, "")
        if new_tree.id != tree_sha.encode():
            print(f"树重建失败: 本地 {new_tree.id.decode()[:12]} "
                  f"≠ 远端 {tree_sha[:12]}")
            return 1

        v = cj.get("verification") or {}
        if v.get("signature") and v.get("payload"):
            candidates = signed_raw_candidates(v["payload"], v["signature"])
        else:
            candidates = unsigned_raw_candidates(cj, tree_sha)
        target = cj["sha"].encode()
        for raw in candidates:
            obj = ShaFile.from_raw_string(1, raw)
            if obj.id == target:
                repo.object_store.add_object(obj)
                print(f"重建提交 {cj['sha'][:12]}: {cj['message'].splitlines()[0][:40]}")
                break
        else:
            print(f"提交重建失败: {cj['sha'][:12]}（候选 {len(candidates)} 个均不匹配）")
            return 1

    # 3. 前移本地 main
    repo.refs[b"refs/heads/main"] = remote_sha.encode()
    print(f"本地 main 已同步: {remote_sha[:12]}（与远端完全一致）")

    # 4. 远端有而本地磁盘缺失的文件落盘（排除清单除外）
    head_listing = api_call(
        "GET", f"/repos/{owner_repo}/git/trees/{chain[-1]['tree']['sha']}?recursive=1",
        token,
    )
    written = []
    for e in head_listing.get("tree", []):
        if e["type"] != "blob" or e["path"] in EXCLUDE:
            continue
        f = ROOT / e["path"]
        if not f.is_file():
            f.parent.mkdir(parents=True, exist_ok=True)
            b = repo.object_store[e["sha"].encode()]
            f.write_bytes(bytes(b.data))
            written.append(e["path"])
    if written:
        print("已落盘远端新增文件:")
        for p in written:
            print(f"  {p}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python scripts/sync_local.py <仓库URL>")
        return 2
    owner_repo = sys.argv[1].split("github.com/")[-1].removesuffix(".git").strip("/")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("缺少 GITHUB_TOKEN 环境变量。")
        return 2
    return sync(owner_repo, token)


if __name__ == "__main__":
    sys.exit(main())
