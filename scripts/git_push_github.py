"""推送 token-burner 仓库到 GitHub（沙箱外执行）。

用法（在沙箱外 / 本机 PowerShell）：
    $env:GITHUB_TOKEN = "<你的 PAT>"
    python scripts/git_push_github.py https://github.com/<用户名>/<仓库名>

- 分支对齐：本地 master 重命名为 main（GitHub 默认），仅一次提交的新仓库安全；
- 推送方式：dulwich 纯 Python Git（无需安装 git 命令）；
- 认证：HTTPS + Basic（用户名任意，密码为 PAT）；
- 不使用 --force；远端已有内容时拒绝覆盖（先报告远端状态）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".vendor"))

from dulwich import porcelain
from dulwich.client import get_transport_and_path
from dulwich.repo import Repo


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python scripts/git_push_github.py <仓库URL>")
        return 2
    url = sys.argv[1].removesuffix(".git")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("缺少 GITHUB_TOKEN 环境变量。")
        return 2

    root = Path(__file__).resolve().parent.parent
    repo = Repo(str(root))

    # 分支对齐 GitHub 默认（一次性，新仓库安全）
    if b"refs/heads/main" not in repo.refs:
        if b"refs/heads/master" in repo.refs:
            repo.refs[b"refs/heads/main"] = repo.refs[b"refs/heads/master"]
            repo.refs.remove_if_equals(b"refs/heads/master", repo.refs[b"refs/heads/main"])
            with open(root / ".git" / "HEAD", "wb") as f:
                f.write(b"ref: refs/heads/main\n")
            print("分支重命名: master -> main")

    # 检查远端是否已有内容（拒绝覆盖非空仓库）
    client, path = get_transport_and_path(url + ".git", username="token", password=token)
    try:
        remote_refs = client.get_refs(path.encode())
        pushables = {k: v for k, v in remote_refs.items()
                     if k.startswith(b"refs/heads/")}
        if pushables:
            print(f"远端非空（{len(pushables)} 个分支），拒绝覆盖。请先核对远端内容。")
            return 1
    except Exception as e:
        print(f"连接远端失败: {e}")
        return 1

    # 推送
    porcelain.push(
        repo,
        remote_location=url + ".git",
        refspecs=[b"refs/heads/main:refs/heads/main"],
        username="token",
        password=token,
    )
    print("推送完成: refs/heads/main ->", url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
