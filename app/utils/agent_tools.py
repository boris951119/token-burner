# -*- coding: utf-8 -*-
"""刀P 修复环工具带（agent tools）——大脑+工具范式（INBOX-017）。

设计约束（用户定）：
- **一事一具**：每个工具只干一件事；
- **参数 ≤3**：超过说明职责切错了，拆；
- **沙箱**：所有路径操作限制在仓库根内，禁止逃逸（../、绝对路径拦截）；
- **可观测**：每次调用留名入轨迹（修复轮报告用）。

病灶对症（sheet_p0/自测8连败/validation_rules 尸检）：修复 agent
从"蒙眼开整文件药方"变成"小步触诊"——check 看红 → grep 找宿主 →
edit 补三行 → 再 check 验证。check/probe 复用既有 checker 思路，
不重复实现判分。
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_EDIT_MAX = 200_000          # edit 目标文件上限（字节）：超大的整文件重写不是外科手术
_GREP_MAX_HITS = 40
_READ_MAX_BYTES = 120_000


@dataclass
class ToolResult:
    ok: bool
    output: str
    call: str = ""            # 轨迹行：tool(arg1, arg2) -> ok


@dataclass
class ToolBelt:
    """五工具执行器（沙箱限 root 内；无状态，轨迹外部聚合）。"""
    root: Path
    check_cmd: list[str] | None = None     # 起服+判分的复测命令（cwd=root）
    base_url: str = ""                    # probe 用
    trace: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()

    # ---- 沙箱 ----
    def _safe(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not str(p).startswith(str(self.root)):
            raise ValueError(f"路径逃逸沙箱: {rel}")
        return p

    def _record(self, name: str, args: str, ok: bool, out: str) -> ToolResult:
        line = f"{name}({args}) -> {'ok' if ok else 'err'}"
        self.trace.append(line)
        return ToolResult(ok=ok, output=out, call=line)

    # ---- 工具 1：read(path) ----
    def read(self, path: str) -> ToolResult:
        try:
            p = self._safe(path)
            if not p.is_file():
                return self._record("read", repr(path), False, "文件不存在")
            text = p.read_text(encoding="utf-8", errors="replace")
            head = text[:_READ_MAX_BYTES]
            numbered = "\n".join(
                f"{i+1}\t{ln}" for i, ln in enumerate(head.splitlines()))
            return self._record("read", repr(path), True,
                                numbered or "(空文件)")
        except Exception as exc:
            return self._record("read", repr(path), False,
                                f"{type(exc).__name__}: {exc}"[:200])

    # ---- 工具 2：grep(pattern, path) ----
    def grep(self, pattern: str, path: str = ".") -> ToolResult:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return self._record("grep", repr(pattern), False,
                                f"非法正则: {exc}")
        try:
            base = self._safe(path)
            roots = [base] if base.is_dir() else [base.parent]
            hits: list[str] = []
            for root in roots:
                for py in sorted(root.rglob("*.py")):
                    if "__pycache__" in py.parts:
                        continue
                    try:
                        for i, ln in enumerate(
                                py.read_text(encoding="utf-8",
                                             errors="replace").splitlines(),
                                1):
                            if rx.search(ln):
                                rel = py.relative_to(self.root)
                                hits.append(f"{rel}:{i}: {ln.strip()[:120]}")
                                if len(hits) >= _GREP_MAX_HITS:
                                    break
                    except OSError:
                        continue
                    if len(hits) >= _GREP_MAX_HITS:
                        break
            out = "\n".join(hits) or "(无命中)"
            return self._record("grep", f"{pattern!r}, {path!r}", True, out)
        except Exception as exc:
            return self._record("grep", f"{pattern!r}, {path!r}", False,
                                f"{type(exc).__name__}: {exc}"[:200])

    # ---- 工具 3：edit(file, old, new) ----
    def edit(self, file: str, old: str, new: str) -> ToolResult:
        args = f"{file!r}, old[{len(old)}B], new[{len(new)}B]"
        try:
            p = self._safe(file)
            if not p.is_file():
                return self._record("edit", args, False, "文件不存在")
            if p.stat().st_size > _EDIT_MAX:
                return self._record("edit", args, False,
                                    f"文件超 {_EDIT_MAX}B——外科上限，禁止整文件重写")
            text = p.read_text(encoding="utf-8", errors="replace")
            n = text.count(old)
            if n == 0:
                return self._record("edit", args, False,
                                    "old 未命中（精确匹配；先 read/grep 核对）")
            if n > 1:
                return self._record("edit", args, False,
                                    f"old 命中 {n} 处——补上下文使其唯一")
            p.write_text(text.replace(old, new, 1), encoding="utf-8")
            try:
                compile(p.read_text(encoding="utf-8"), str(p), "exec")
            except SyntaxError as exc:
                # 语法回滚：坏补丁绝不落盘
                p.write_text(text, encoding="utf-8")
                return self._record("edit", args, False,
                                    f"补丁语法非法已回滚: {exc}")
            return self._record("edit", args, True,
                                f"已替换 1 处（{len(old)}B -> {len(new)}B）")
        except Exception as exc:
            return self._record("edit", args, False,
                                f"{type(exc).__name__}: {exc}"[:200])

    # ---- 工具 4：check() ----
    def check(self) -> ToolResult:
        if not self.check_cmd:
            return self._record("check", "", False, "未配置复测命令")
        try:
            proc = subprocess.run(
                self.check_cmd, cwd=str(self.root), capture_output=True,
                text=True, timeout=300)
            out = ((proc.stdout or "") + (proc.stderr or ""))[-4000:]
            return self._record(
                "check", "", proc.returncode == 0,
                f"rc={proc.returncode}\n{out}".strip())
        except Exception as exc:
            return self._record("check", "", False,
                                f"{type(exc).__name__}: {exc}"[:200])

    # ---- 工具 5：probe(route) ----
    def probe(self, route: str) -> ToolResult:
        if not self.base_url:
            return self._record("probe", repr(route), False, "未配置 base_url")
        import urllib.request
        url = self.base_url.rstrip("/") + "/" + route.lstrip("/")
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                body = r.read(4000).decode("utf-8", errors="replace")
                return self._record(
                    "probe", repr(route), r.status == 200,
                    f"status={r.status}\n{body[:2000]}")
        except Exception as exc:
            return self._record("probe", repr(route), False,
                                f"{type(exc).__name__}: {exc}"[:200])

    # ---- 描述（注入 LLM 系统提示用）----
    TOOLS_DOC = """可用工具（每轮只能调一个，输出会作为下一轮输入）：
- read(path) —— 读仓库内一个文件（带行号）
- grep(pattern, path=".") —— 正则搜 .py，返回 文件:行: 内容
- edit(file, old, new) —— 外科替换：old 必须在文件中唯一命中且完整
- check() —— 起服+跑验收判分，返回红字清单
- probe(route) —— GET 一个路由看实际响应

纪律：先 read/grep 看清再 edit；edit 的 old 抄原文片段保证唯一；
每轮一步；check 绿了就停止并报告。"""


def run_tool_loop(llm, belt: ToolBelt, issue: str,
                  max_turns: int = 24, system: str = "") -> dict:
    """大脑+工具循环：LLM 每轮发一条工具调用，结果回喂，直到达标/预算尽。

    llm(system, user) -> str。返回 {ok, turns, trace, last_output}。
    协议极简（无 function-calling 依赖，任意 chat 模型可用）：
    模型每轮只输出一行 `工具(参数)` 或 `DONE 原因`。
    """
    sys_prompt = (system or "你是修复工程师，用小步工具修红字。") + "\n\n" + \
        ToolBelt.TOOLS_DOC + f"\n\n问题：\n{issue[:6000]}"
    history: list[dict] = []
    for turn in range(1, max_turns + 1):
        user = ("\n".join(history[-8:]) if history else "(开始)")
        raw = (llm(sys_prompt, user) or "").strip()
        line = raw.splitlines()[0].strip() if raw else ""
        if line.upper().startswith("DONE"):
            belt.trace.append(f"[turn{turn}] DONE {line[4:60]}")
            final = belt.check()
            return {"ok": final.ok, "turns": turn,
                    "trace": list(belt.trace), "last_output": final.output}
        m = re.match(r"(read|grep|edit|check|probe)\((.*)\)\s*$", line)
        if not m:
            history.append(f"[系统] 格式错误，只输出一行如 edit('a.py', old, new) "
                           f"或 DONE 原因。你上一轮输出: {line[:120]}")
            belt.trace.append(f"[turn{turn}] bad-format")
            continue
        name, argstr = m.group(1), m.group(2)
        arity = {"read": 1, "grep": 2, "edit": 3, "check": 0,
                 "probe": 1}.get(name)
        try:
            args = _parse_args(argstr, arity)
        except ValueError as exc:
            history.append(f"[系统] 参数解析失败: {exc}")
            belt.trace.append(f"[turn{turn}] bad-args")
            continue
        if name == "grep" and len(args) == 1:
            args = args + (".",)
        try:
            res = getattr(belt, name)(*args)
        except TypeError as exc:
            history.append(f"[系统] 参数个数不符: {exc}")
            belt.trace.append(f"[turn{turn}] bad-arity")
            continue
        history.append(f"[{name} 结果] {'ok' if res.ok else 'err'}\n{res.output[:3000]}")
        if name == "check" and res.ok:
            belt.trace.append(f"[turn{turn}] check-green 收敛")
            return {"ok": True, "turns": turn, "trace": list(belt.trace),
                    "last_output": res.output}
    return {"ok": False, "turns": max_turns, "trace": list(belt.trace),
            "last_output": history[-1][:2000] if history else ""}


def _parse_args(argstr: str, expected: int | None = None) -> tuple:
    """`'a.py', 'old', 'new'` → ('a.py', 'old', 'new')。

    显式引号切分：每个参数必须是 '...' 或 "..." 包裹（引号内逗号/空格/
    换行原样，换行用 \n 转义）；shlex 会把引号外的分隔逗号并进参数，
    故不用。expected 校验个数，错配当场报。
    """
    parts: list[str] = []
    i, n = 0, len(argstr)
    while i < n:
        while i < n and argstr[i] in " ,\t":
            i += 1
        if i >= n:
            break
        if argstr[i] not in "'\"":
            raise ValueError(f"参数必须引号包裹，位置 {i}: {argstr[i:i+20]!r}")
        q = argstr[i]
        i += 1
        buf: list[str] = []
        while i < n and argstr[i] != q:
            if argstr[i] == "\\" and i + 1 < n and argstr[i + 1] == "n":
                buf.append("\n")
                i += 2
                continue
            buf.append(argstr[i])
            i += 1
        if i >= n:
            raise ValueError("引号未闭合")
        parts.append("".join(buf))
        i += 1
    if expected is not None and len(parts) != expected:
        raise ValueError(f"需要 {expected} 个参数，解析出 {len(parts)} 个：{parts}")
    return tuple(parts)


def tool_repair(llm, repo_root: Path, issue: str,
                check_cmd: list[str], max_turns: int = 24) -> dict:
    """刀P：工具循环修复入口（auto_repair 试验通道调用）。

    llm(system, user) 与 RepoFixer 同签名；repo_root=项目根（含 code/）；
    check_cmd=同闸复测命令（cwd=root）。返回 run_tool_loop 同构 dict，
    末次 check 结果即成败判据（与 RepoFixer 的 test_cmd 语义对齐）。
    """
    belt = ToolBelt(root=repo_root, check_cmd=check_cmd)
    return run_tool_loop(llm, belt, issue, max_turns=max_turns)
