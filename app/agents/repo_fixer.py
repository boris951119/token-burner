"""v1.2 S1 repo-patch：修已有仓库的 issue(最小改动补丁 + 真实测试验证)。

设计锚点(v1.2-workplan S1)：
- 单模块直通：issue 即 spec,跳过拆分/spec 确认,复用「生成 → 验证 →
  修复循环」精神,但工作区是**已有仓库**而非全新文件树；
- 最小改动：提示词强制「只改与 issue 相关的文件,禁止重构无关代码、
  禁止修改测试(除非 issue 明确要求)」；
- 安全边界：LLM 只能改文件(路径越界/绝对路径一律拒绝),命令执行仅限
  我方验证运行；仓库无 .git 时跳过 diff(其余能力不变)；
- 门禁诚实边界：repo 模式无 interfaces.json,链接/接口门禁不适用,
  验收以仓库自带测试为准(写入文档)。

流程：plan(issue+文件树 → 目标文件清单) → patch(逐文件完整新版) →
verify(运行验证命令) → fix(失败带输出重出补丁,≤ max_rounds)。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.utils.parse import parse_json

DEFAULT_TEST_CMD = [sys.executable, "-m", "pytest", "-q"]
_MAX_TREE_ENTRIES = 400
_MAX_FILE_CHARS = 60_000


@dataclass
class RepoFixResult:
    """repo-patch 执行结果。"""

    ok: bool
    changed_files: list[str] = field(default_factory=list)
    rounds: int = 0
    diff: str = ""                       # git diff(仓库无 .git 时为空)
    test_output: str = ""                # 最后一轮验证命令输出(截尾)
    error: str = ""                      # 未通过原因/异常摘要
    skipped_paths: list[str] = field(default_factory=list)  # 被拒绝的越界路径


class RepoFixer:
    """issue → 最小改动补丁 → 仓库测试验证 → 失败带输出重试。"""

    def __init__(
        self,
        llm,                                   # callable(system: str, user: str) -> str
        repo_path: str | Path,
        test_cmd: list[str] | None = None,
        max_rounds: int = 3,
        test_timeout: int = 300,
    ):
        self.llm = llm
        self.repo = Path(repo_path).resolve()
        self.test_cmd = list(test_cmd or DEFAULT_TEST_CMD)
        self.max_rounds = max_rounds
        self.test_timeout = test_timeout

    # ---- 公共入口 ----

    def fix(self, issue: str, test_files: list[str] | None = None) -> RepoFixResult:
        # 无 .git 照常修复：diff 仅是结果报告（_diff 无 git 时返回空串）。
        # r4 取证：此前此处硬拒绝，而平台入口 enable_git=False（平台侧
        # 统一走 runtime.git），导致交付修复安全网在参赛路径恒为死路
        # （0 轮即返，LocalProxy 类组装缺陷无人生还）。
        plan = self._plan(issue)
        if plan is None:
            return RepoFixResult(ok=False, error="修复方案解析失败")
        planned: list[tuple[str, str]] = []
        skipped: list[str] = []
        for f in plan.get("files", []):
            path = str(f.get("path", "")).strip()
            change = str(f.get("change", "")).strip()
            ok_path, resolved = self._safe_path(path)
            if not ok_path:
                skipped.append(path)
                continue
            planned.append((resolved, change))
        if not planned:
            return RepoFixResult(ok=False, skipped_paths=skipped,
                                 error="修复方案未包含任何仓库内文件")

        # 逐文件生成完整新版(plan 只给清单与意图,内容在这里产出)
        changed: dict[str, str] = {}
        for path, change in planned:
            fp = self.repo / path
            current = (fp.read_text(encoding="utf-8", errors="replace")
                       [:_MAX_FILE_CHARS] if fp.exists() else "")
            content = self._patch_file(issue, path, change, current)
            if content:
                changed[path] = content
        if not changed:
            return RepoFixResult(ok=False, skipped_paths=skipped,
                                 error="逐文件补丁生成失败")

        result = RepoFixResult(ok=False, changed_files=list(changed),
                               skipped_paths=skipped)
        detail = ""
        last_sig: str | None = None
        for attempt in range(1, self.max_rounds + 1):
            result.rounds = attempt
            rejected = self._apply(changed)
            # 被拒文件的草稿退回磁盘现行版：下一轮从**真实内容**出发重出，
            # 而不是把这份非法草稿当"当前内容"继续放大。
            for rel, _msg in rejected:
                fp = self.repo / rel
                changed[rel] = (
                    fp.read_text(encoding="utf-8", errors="replace")
                    [:_MAX_FILE_CHARS] if fp.exists() else "")
            passed, output = self._verify(self.test_cmd, test_files)
            result.test_output = output[:4000]
            if passed:
                result.ok = True
                result.diff = self._diff()
                return result
            detail = output[-2500:]
            # 无进展止损（2026-09-20 平台双跑取证：修复轮烧满 max_rounds
            # 却零收敛是 ¥130 级失血点）——数字归一化后失败输出本质相同
            # 即判定无进展，立即退出，不再烧后续轮次。
            sig = re.sub(r"\d+", "N", detail)
            if sig == last_sig:
                result.error = (f"连续两轮失败输出相同，无进展止损"
                                f"（{attempt} 轮）：{detail[:200]}")
                result.diff = self._diff()
                return result
            last_sig = sig
            # 修复轮：带失败输出重出全部已改文件的完整新版。语法拒收的
            # 文件必须点名告知模型——不说的话模型只知道"测试还红着"，
            # 会照着同一份非法输出再撞一次（keep 彩排实证同一文件连拒 4 轮）。
            failure = detail
            if rejected:
                failure = (
                    detail
                    + "\n\n## 系统拒收清单（上一版语法非法，未写入磁盘）\n"
                    + "\n".join(f"- {rel}: {msg}" for rel, msg in rejected)
                    + "\n上述文件磁盘上仍是修改前的旧版，必须整文件重发，"
                      "且先自检 Python 语法（括号/缩进/引号闭合）再输出。")
            repatched = self._repatch(issue, changed, failure)
            if repatched:
                # 修复轮不得让文件集缩水：模型漏发的文件沿用上一版内容，
                # 否则该文件被静默踢出修复范围（与语法拒收同类的失血口）。
                for rel, content in changed.items():
                    repatched.setdefault(rel, content)
                changed = repatched
                result.changed_files = list(changed)
        result.error = f"验证 {self.max_rounds} 轮未通过：{detail[:300]}"
        result.diff = self._diff()
        return result

    # ---- 阶段实现 ----

    def _plan(self, issue: str) -> dict | None:
        system = (
            "你是资深工程师,在真实仓库中修复 issue。"
            "只输出 JSON(不要围栏):"
            '{"analysis": "根因简析", '
            '"files": [{"path": "相对路径", "change": "修改说明"}]}。'
            "只列必须修改的文件;禁止修改测试文件(除非 issue 明确要求);"
            "路径使用相对仓库根的 POSIX 格式。"
        )
        user = f"## Issue\n{issue}\n\n## 仓库文件树\n{self._tree()}"
        obj, detail = parse_json(self._chat(system, user), location="repo_fix.plan")
        if obj is None or not isinstance(obj, dict):
            print(f"[repo_fix] plan 解析失败: {detail}")
            return None
        return obj

    def _patch_file(self, issue: str, path: str, change: str,
                    current: str) -> str | None:
        system = (
            "你是资深工程师。输出指定文件的完整新版内容(最小必要修改:"
            "只改与 issue 相关的部分,保持风格与缩进,禁止重构无关代码,"
            "禁止修改测试断言)。只输出文件内容本身,不要围栏、不要解释。"
        )
        current_section = (
            f"## 当前文件内容\n{current[:_MAX_FILE_CHARS]}"
            if current else "## 当前文件内容\n(新文件)"
        )
        out = self._chat(
            system,
            f"## Issue\n{issue}\n\n## 修改目标\n{change}\n\n"
            f"{current_section}\n\n请输出该文件的完整新版内容。",
        )
        content = out.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
        return content or None

    def _repatch(self, issue: str, changed: dict[str, str],
                 failure: str) -> dict[str, str] | None:
        """修复轮:带失败输出,重出全部已改文件。"""
        system = (
            "你是资深工程师。上一版修改未通过仓库测试。"
            "根据失败输出重新给出所有已改文件的完整新版内容。"
            "只输出 JSON(不要围栏):"
            '{"files": [{"path": "相对路径", "content": "完整新版内容"}]}'
        )
        files_section = "\n".join(
            f"### {p}\n当前内容:\n{(c or '')[:_MAX_FILE_CHARS]}"
            for p, c in changed.items())
        obj, _ = parse_json(
            self._chat(system,
                       f"## Issue\n{issue}\n\n## 已改文件\n{files_section}\n\n"
                       f"## 测试失败输出\n{failure}"),
            location="repo_fix.repatch",
        )
        if not isinstance(obj, dict):
            return None
        out: dict[str, str] = {}
        for f in obj.get("files", []):
            path = str(f.get("path", "")).strip()
            ok_path, resolved = self._safe_path(path)
            if ok_path and f.get("content"):
                out[resolved] = str(f["content"])
        return out or None

    # ---- 应用 / 验证 / 工具 ----

    def _safe_path(self, path: str) -> tuple[bool, str]:
        """路径安全:必须为仓库内相对 POSIX 路径(防越界写入)。"""
        if not path or path.startswith("/") or ".." in Path(path).parts:
            return False, ""
        resolved = (self.repo / path).resolve()
        try:
            resolved.relative_to(self.repo)
        except ValueError:
            return False, ""
        return True, resolved.relative_to(self.repo).as_posix()

    def _apply(self, changed: dict[str, str]) -> list[tuple[str, str]]:
        """落盘本轮草稿，返回被拒清单 [(rel, 语法错误)]。

        2026-09-20 取证：修复 LLM 曾把 .py 整文件写成 HTML 残渣
        （'<!-- ... -->' 开头）——落盘前语法自证，垃圾写一律不入库，
        对应文件保持磁盘上的旧合法内容。
        拒收不等于退出修复线：内容留在 changed 里由 fix() 打回磁盘版
        并在下一轮提示词点名（旧实现把拒收文件从 changed 弹出，等于
        悄悄把它踢出修复范围，模型此后再没机会改这个文件）。
        """
        rejected: list[tuple[str, str]] = []
        for rel, content in changed.items():
            target = self.repo / rel
            if target.suffix == ".py":
                try:
                    compile(content, str(target), "exec")
                except SyntaxError as exc:
                    msg = f"invalid syntax: {exc.msg} (line {exc.lineno})"
                    print(f"[repo_fix] 拒收语法非法的修复内容 {rel}: {exc}",
                          flush=True)
                    rejected.append((rel, msg))
                    continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        if rejected:
            print(f"[repo_fix] 本轮拒收 {len(rejected)} 个文件: "
                  f"{[r for r, _ in rejected]}", flush=True)
        return rejected

    def _verify(self, verify_cmd: list[str],
                test_files: list[str] | None) -> tuple[bool, str]:
        cmd = list(verify_cmd)
        if test_files:
            cmd += list(test_files)
        self._clear_pycache()
        proc = subprocess.run(cmd, cwd=self.repo, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=self.test_timeout,
                              env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                       PYTHONDONTWRITEBYTECODE="1"))
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, output

    def _clear_pycache(self) -> None:
        """验证前清字节码缓存（与 arcbench_smoke._clear_pycache 同源）。

        等长同秒覆写（`return a - b` → `return a + b` 恰好同长度）会命中
        pyc 的 mtime 秒级 + 源大小双重校验，验证子进程导入陈旧模块——
        修复循环对着旧代码判定成败：假红、震荡、非确定。测试污染实证
        该缺陷曾让同一修复轮反复"失败"。
        """
        for cache in self.repo.rglob("__pycache__"):
            try:
                shutil.rmtree(cache, ignore_errors=True)
            except Exception:
                pass

    def _diff(self) -> str:
        try:
            proc = subprocess.run(
                ["git", "diff"], cwd=self.repo, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30)
            return proc.stdout or ""
        except Exception:
            return ""

    def _tree(self) -> str:
        entries: list[str] = []
        for p in sorted(self.repo.rglob("*")):
            rel = p.relative_to(self.repo).as_posix()
            if rel.startswith((".git", "__pycache__", ".pytest_cache",
                               "node_modules", ".venv")):
                continue
            entries.append(rel + ("/" if p.is_dir() else ""))
            if len(entries) >= _MAX_TREE_ENTRIES:
                entries.append("...(截断)")
                break
        return "\n".join(entries)

    def _chat(self, system: str, user: str) -> str:
        return self.llm(system, user) or ""
