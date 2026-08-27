"""生成项目的本地 git 版本管理（规格文档 14 章）。

- 项目创建后 git init（纯本地，免推送）；
- 阶段性提交：spec 确认后 / 每模块完成后 / 集成（交付汇总）后；
- 提交信息含阶段语义：[spec] / [module:<name>] / [integration]，
  可追溯哪个阶段产出了哪些文件；
- 命令执行器可注入（runner），单元测试零 git 依赖；
- git 操作失败不中断主管线（记录日志，流程继续——版本管理是
  增强能力而非关键路径）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

# runner: (cwd, *git_args) -> stdout
Runner = Callable[..., str]


def _default_runner(cwd: str, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败: {result.stderr.strip()}")
    return result.stdout


class GitManager:
    """生成项目仓库的本地 git 管理。"""

    def __init__(self, runner: Runner | None = None):
        self._runner = runner or _default_runner

    def init(self, project_root: Path) -> None:
        """项目创建后初始化本地仓库（14 章：免推送）。"""
        root = str(project_root)
        self._safe(root, "init")

    def commit_stage(self, project_root: Path, stage: str, detail: str) -> None:
        """阶段性提交：git add -A + git commit -m "[<stage>] <detail>"。"""
        root = str(project_root)
        self._safe(root, "add", "-A")
        message = f"[{stage}] {detail}"
        self._safe(root, "commit", "-m", message)

    # ------------------------------------------------------------------

    def _safe(self, root: str, *args: str) -> None:
        """git 失败不中断主管线（版本管理非关键路径）。"""
        try:
            self._runner(root, *args)
        except Exception:
            pass
