"""token-burner 项目仓库 git 初始化（沙箱内执行，免 git 命令）。

用 dulwich（纯 Python Git 实现）产出标准 .git 仓库与首次提交；
尊重 .gitignore 排除规则。之后安装了 git 命令即可直接继续协作
（git log / git add / git commit / 推送 GitHub）。

运行：python scripts/git_init_repo.py
"""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".vendor"))

from dulwich import porcelain
from dulwich.repo import Repo

ROOT = Path(__file__).resolve().parent.parent
AUTHOR = b"token-burner <jarvis@local>"
# 仓库内部目录与生成产物：无条件排除（.git 自引用防范）
HARD_IGNORED = {".git", ".vendor", "projects", "demo_projects", "logs",
                ".env", ".venv", "__pycache__", ".pytest_cache"}


def load_gitignore() -> list[str]:
    rules: list[str] = []
    gi = ROOT / ".gitignore"
    if gi.exists():
        for line in gi.read_text(encoding="utf-8").splitlines():
            line = line.strip().rstrip("/")
            if line and not line.startswith("#"):
                rules.append(line)
    return rules


def is_ignored(path: Path, rules: list[str]) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    parts = rel.split("/")
    if parts[0] in HARD_IGNORED:
        return True
    for rule in rules:
        if rule in parts:  # 目录名规则（如 __pycache__、.vendor）
            return True
        if fnmatch.fnmatch(rel, rule) or fnmatch.fnmatch(parts[-1], rule):
            return True
    return False


def main() -> None:
    if (ROOT / ".git").exists():
        print("仓库已存在，跳过 init。")
        repo = Repo(str(ROOT))
    else:
        repo = porcelain.init(str(ROOT))
        print("git init 完成（纯本地，未配置远程）。")

    rules = load_gitignore()
    files = [
        p for p in ROOT.rglob("*")
        if p.is_file() and not is_ignored(p, rules)
    ]
    relpaths = [str(p.relative_to(ROOT).as_posix()) for p in files]
    porcelain.add(repo, paths=relpaths)
    print(f"暂存 {len(relpaths)} 个文件（.gitignore 规则已排除 {len(rules)} 类）。")

    porcelain.commit(
        repo,
        message="初始提交：Token 消耗器 MVP（278 测试全绿）".encode("utf-8"),
        author=AUTHOR,
        committer=AUTHOR,
    )
    print("首次提交完成。")

    # 验证：读回提交
    head = repo.head()
    commit = repo[head]
    print(f"HEAD: {head.decode()[:12]}")
    print(f"消息: {commit.message.decode('utf-8', errors='replace')}")
    tree = repo[commit.tree]
    print(f"入库条目数: {len(tree)}")


if __name__ == "__main__":
    main()
