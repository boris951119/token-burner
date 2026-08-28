"""经 GitHub REST API 推送全量代码（绕开不稳定的智能 HTTP 协议）。

流程：
  1. GET  /git/ref/heads/main        → 远端 main 提交与树
  2. POST /git/blobs                 → 逐文件上传（文本 utf-8 / 二进制 base64）
  3. POST /git/trees  (base_tree)    → 远端树 + 本地文件 = 合并树
  4. POST /git/commits (单亲=远端)   → 新提交（不覆盖远端历史）
  5. PATCH /git/refs/heads/main      → 快进更新引用
  6. 本地：复用 sync_local 链式重建提交（含签名提交），同步本地 main

用法（沙箱外）：
    $env:GITHUB_TOKEN = "<PAT>"
    python scripts/git_push_api.py https://github.com/<用户名>/<仓库名>
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # 复用 git_init_repo 的过滤规则
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".vendor"))

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
        print("用法: python scripts/git_push_api.py <仓库URL>")
        return 2
    owner_repo = sys.argv[1].split("github.com/")[-1].removesuffix(".git").strip("/")
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

    # 2. 收集本地文件（.gitignore 规则复用）
    rules = load_gitignore()
    files = [p for p in ROOT.rglob("*") if p.is_file() and not is_ignored(p, rules)]
    log(f"待上传文件: {len(files)} 个")

    # 3. 逐文件建 blob
    entries = []
    for p in files:
        raw = p.read_bytes()
        rel = p.relative_to(ROOT).as_posix()
        try:
            text = raw.decode("utf-8")
            body = {"content": text, "encoding": "utf-8"}
        except UnicodeDecodeError:
            body = {"content": base64.b64encode(raw).decode("ascii"),
                    "encoding": "base64"}
        blob = api_call("POST", f"/repos/{owner_repo}/git/blobs", token, body)
        entries.append({"path": rel, "mode": "100644", "type": "blob",
                        "sha": blob["sha"]})
    log(f"blob 上传完成: {len(entries)} 个")

    # 4. 合并树（base_tree 保留远端 README 等独有文件）
    tree = api_call(
        "POST", f"/repos/{owner_repo}/git/trees", token,
        {"base_tree": base_tree, "tree": entries},
    )
    log(f"合并树: {tree['sha'][:12]}")

    # 5. 新提交（单亲 = 远端 main，快进）
    now = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    author = {"name": "token-burner", "email": "jarvis@local", "date": now}
    new_commit = api_call(
        "POST", f"/repos/{owner_repo}/git/commits", token,
        {
            "message": "feat: v0.4 桌面版与 API server（budget/local_executor、17 个新测试、投资人交付物）",
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
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from sync_local import sync  # noqa: E402

        sync(owner_repo, token)
    except Exception as e:
        log(f"本地同步失败（不影响推送结果）: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
