"""经 GitHub REST API 推送全量代码（绕开不稳定的智能 HTTP 协议）。

流程：
  1. GET  /git/ref/heads/main        → 远端 main 提交与树
  2. POST /git/blobs                 → 逐文件上传（文本 utf-8 / 二进制 base64）
  3. POST /git/trees  (base_tree)    → 远端树 + 本地文件 = 合并树
     （本地 index 已删除的文件以 sha:null 同步删除，含安全阈值）
  4. POST /git/commits (单亲=远端)   → 新提交（不覆盖远端历史）
  5. PATCH /git/refs/heads/main      → 快进更新引用
  6. 本地：复用 sync_local 链式重建提交（含签名提交），同步本地 main

用法（沙箱外）：
    # 方式一（推荐）：token 写入项目根 .env（已 gitignore，不入库）
    #   .env 增加：GITHUB_TOKEN=ghp_xxx
    # 方式二：临时环境变量
    $env:GITHUB_TOKEN = "<PAT>"
    python scripts/git_push_api.py https://github.com/<用户名>/<仓库名>
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # 复用 git_init_repo 的过滤规则
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".vendor"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # GITHUB_TOKEN 优先走 .env

from git_init_repo import is_ignored, load_gitignore  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_LOG = ROOT / "api_push.log"
API = "https://api.github.com"


def log(msg: str) -> None:
    with open(_LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
        f.flush()


def api_call(method: str, path: str, token: str, body: dict | None = None,
             retries: int = 3) -> dict:
    """REST 调用（带重试，urllib 通道已被验证稳定）。"""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                f"{API}{path}",
                data=data,
                method=method,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "token-burner-push",
                    "Accept": "application/vnd.github+json",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            log(f"  {method} {path} 第 {attempt} 次失败: {e}")
            if attempt == retries:
                raise
            time.sleep(2 * attempt)


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python scripts/git_push_api.py <仓库URL> [--force-delete]")
        return 2
    owner_repo = sys.argv[1].split("github.com/")[-1].removesuffix(".git").strip("/")
    force_delete = "--force-delete" in sys.argv[2:]
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("缺少 GITHUB_TOKEN 环境变量。")
        return 2

    # 1. 远端现状
    ref = api_call("GET", f"/repos/{owner_repo}/git/ref/heads/main", token)
    remote_sha = ref["object"]["sha"]
    commit = api_call("GET", f"/repos/{owner_repo}/git/commits/{remote_sha}", token)
    base_tree = commit["tree"]["sha"]
    log(f"远端 main: {remote_sha[:12]}  base_tree: {base_tree[:12]}")

    # 2. 收集本地文件（以 git index 为准，与提交内容严格一致；
    #    工作区收集会把未跟踪文件误传、也无法推知删除意图）
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
    ).stdout.decode("utf-8", errors="replace").split("\0")
    files = [ROOT / p for p in tracked if p and (ROOT / p).is_file()]
    log(f"待上传文件: {len(files)} 个（git index）")

    # 2.5 远端现有 blob 清单（内容未变的文件由 base_tree 继承，跳过上传）
    base_listing = api_call(
        "GET", f"/repos/{owner_repo}/git/trees/{base_tree}?recursive=1", token,
    )
    remote_sha_by_path = {
        e["path"]: e["sha"] for e in base_listing.get("tree", [])
        if e["type"] == "blob"
    }

    # 3. 逐文件建 blob（断点续传：api_blob_cache.json 记录已上传的 blob）
    cache_path = ROOT / "api_blob_cache.json"
    try:
        cache: dict[str, str] = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    entries: list[dict] = []
    pending: list[tuple[str, bytes, str]] = []
    for p in files:
        raw = p.read_bytes()
        rel = p.relative_to(ROOT).as_posix()
        sha = hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()
        if remote_sha_by_path.get(rel) == sha:
            continue  # 远端已有同内容 blob：base_tree 继承
        if cache.get(rel) == sha:
            entries.append({"path": rel, "mode": "100644", "type": "blob",
                            "sha": sha})
            continue  # 此前运行已上传：直接引用
        pending.append((rel, raw, sha))
    log(f"需上传: {len(pending)}  缓存命中: "
        f"{sum(1 for e in entries if e['sha'] == cache.get(e['path']))}"
        f"  远端已存在: {len(files) - len(pending) - len(entries)}")

    for i, (rel, raw, sha) in enumerate(pending, 1):
        try:
            text = raw.decode("utf-8")
            body = {"content": text, "encoding": "utf-8"}
        except UnicodeDecodeError:
            body = {"content": base64.b64encode(raw).decode("ascii"),
                    "encoding": "base64"}
        blob = api_call("POST", f"/repos/{owner_repo}/git/blobs", token, body)
        if blob["sha"] != sha:
            raise RuntimeError(f"blob sha 不匹配: {rel}")
        cache[rel] = sha
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
        entries.append({"path": rel, "mode": "100644", "type": "blob",
                        "sha": blob["sha"]})
        if i % 10 == 0 or i == len(pending):
            log(f"  blob 进度: {i}/{len(pending)}")
    log(f"blob 上传完成: {len(pending)} 个")

    # 3.5 删除清单：远端有、本地 index 没有 → 合并树中以 sha:null 移除。
    #     安全阈值：删除量异常大（疑似错误目录下运行/误清空）时中止。
    tracked_rel = {p.relative_to(ROOT).as_posix() for p in files}
    deletions = sorted(p for p in remote_sha_by_path if p not in tracked_rel)
    if (len(deletions) > 200 and len(deletions) > 0.3 * len(remote_sha_by_path)
            and not force_delete):
        raise RuntimeError(
            f"待删除 {len(deletions)} 个文件超过安全阈值（远端共 "
            f"{len(remote_sha_by_path)} 个 blob），疑似误操作，中止推送；"
            f"确属一次性大清理时加 --force-delete 放行。"
        )
    log(f"远端删除: {len(deletions)} 个" + (f"（前 5: {deletions[:5]}）" if deletions else ""))

    # 4. 合并树（base_tree 继承未变更项；本地删除的文件以 sha:null 移除）
    tree = api_call(
        "POST", f"/repos/{owner_repo}/git/trees", token,
        {"base_tree": base_tree, "tree": entries
         + [{"path": p, "mode": "100644", "type": "blob", "sha": None}
            for p in deletions]},
    )
    log(f"合并树: {tree['sha'][:12]}")

    # 5. 新提交（单亲 = 远端 main，快进）；提交信息取本地 HEAD（保持与本地一致）
    head_msg = subprocess.run(
        ["git", "log", "-1", "--format=%B"], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout.strip()
    now = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    author = {"name": "token-burner", "email": "jarvis@local", "date": now}
    new_commit = api_call(
        "POST", f"/repos/{owner_repo}/git/commits", token,
        {
            "message": head_msg,
            "tree": tree["sha"],
            "parents": [remote_sha],
            "author": author,
            "committer": author,
        },
    )
    new_sha = new_commit["sha"]
    log(f"新提交: {new_sha[:12]}")

    # 6. 快进更新 main 引用
    api_call(
        "PATCH", f"/repos/{owner_repo}/git/refs/heads/main", token,
        {"sha": new_sha, "force": False},
    )
    log(f"main 已更新: {new_sha[:12]}（快进，未覆盖历史）")
    print(f"推送完成: https://github.com/{owner_repo}/commit/{new_sha[:12]}")

    # 7. 本地同步：复用 sync_local 的链式重建（含签名提交/时区候选）
    #    SKIP_LOCAL_SYNC=1 跳过——链式重建会覆盖工作区文件（曾致 README
    #    落回循环）；本地 git 历史本就是提交源头，默认跳过更安全
    if os.environ.get("SKIP_LOCAL_SYNC"):
        log("跳过本地同步（SKIP_LOCAL_SYNC=1）")
        return 0
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from sync_local import sync  # noqa: E402

        sync(owner_repo, token)
    except Exception as e:
        log(f"本地同步失败（不影响推送结果）: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
