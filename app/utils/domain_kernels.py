# -*- coding: utf-8 -*-
"""领域内核骨架（v44+ P1-D）。

表格题 / 协作平台题的硬功能不全靠一次 LLM 生成：先落确定性
`_shared` 内核（公式最小求值、会话鉴权），模型写 UI/胶水去接。

风险护栏：
- **只增不改**：目标文件已存在则跳过，绝不覆盖作者代码；
- 内核 API 保持最小；标注 `__arcbench_domain_kernel__`；
- 检测靠题面关键词，误判时最多多两个无害文件。
"""
from __future__ import annotations

from pathlib import Path

_FORMULA_KERNEL = '''\
# -*- coding: utf-8 -*-
"""表格公式最小内核（token-burner domain kernel，可被业务模块 import）。

__arcbench_domain_kernel__ = "formula"
支持：数字字面量、+/-/*//、单元格引用 A1/B2、SUM/AVG/MIN/MAX/COUNT。
业务层负责把网格值喂进来；本模块不碰 Flask/路由。
"""
from __future__ import annotations

import ast
import re
from typing import Callable

__arcbench_domain_kernel__ = "formula"

_CELL = re.compile(r"\\b([A-Za-z]+)(\\d+)\\b")


def col_row(ref: str) -> tuple[int, int]:
    m = _CELL.fullmatch(ref.strip())
    if not m:
        raise ValueError(f"bad cell ref: {ref!r}")
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + (ord(ch) - 64)
    return col - 1, int(m.group(2)) - 1


def _to_number(value):
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s.startswith("="):
        raise ValueError("nested formula")
    try:
        return float(s)
    except ValueError:
        return 0.0


def evaluate(expr: str, get_cell: Callable[[str], object]) -> object:
    """求值公式。expr 可带前导 =。get_cell(ref) → 网格原值。"""
    raw = (expr or "").strip()
    if not raw:
        return ""
    if not raw.startswith("="):
        return raw
    body = raw[1:].strip()
    if not body:
        return ""

    def cell_value(ref: str):
        return _to_number(get_cell(ref))

    # SUM(A1:B2) 类
    def _range_vals(a: str, b: str) -> list[float]:
        c1, r1 = col_row(a)
        c2, r2 = col_row(b)
        vals = []
        for r in range(min(r1, r2), max(r1, r2) + 1):
            for c in range(min(c1, c2), max(c1, c2) + 1):
                # 反解列字母
                n, letters = c + 1, []
                while n:
                    n, rem = divmod(n - 1, 26)
                    letters.append(chr(65 + rem))
                ref = "".join(reversed(letters)) + str(r + 1)
                vals.append(cell_value(ref))
        return vals

    body_up = body.upper()
    for fname, folder in (
        ("SUM", sum), ("AVG", lambda xs: sum(xs) / len(xs) if xs else 0.0),
        ("MIN", min), ("MAX", max), ("COUNT", len),
    ):
        m = re.fullmatch(rf"{fname}\\(([^:]+):([^)]+)\\)", body_up)
        if m:
            vals = _range_vals(m.group(1), m.group(2))
            return folder(vals) if fname != "COUNT" else float(len(vals))

    # 替换单元格引用为数值再安全求值
    def repl(m: re.Match) -> str:
        return str(cell_value(m.group(0)))

    numeric = _CELL.sub(repl, body)
    try:
        tree = ast.parse(numeric, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, (ast.Call, ast.Attribute, ast.Name)):
                if isinstance(node, ast.Name) and node.id in {"True", "False"}:
                    continue
                if isinstance(node, (ast.Call, ast.Attribute)):
                    raise ValueError("unsafe")
                if isinstance(node, ast.Name):
                    raise ValueError("unsafe name")
        return eval(compile(tree, "<formula>", "eval"), {"__builtins__": {}}, {})
    except Exception:
        return "#ERROR!"
'''

_SESSION_KERNEL = '''\
# -*- coding: utf-8 -*-
"""会话 / 账号最小内核（token-burner domain kernel）。

__arcbench_domain_kernel__ = "session"
内存用户表 + 签名 cookie 辅助；业务路由负责挂 Flask session。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field

__arcbench_domain_kernel__ = "session"


@dataclass
class UserRecord:
    username: str
    email: str
    password_hash: str


@dataclass
class SessionStore:
    users: dict[str, UserRecord] = field(default_factory=dict)
    # username → token
    tokens: dict[str, str] = field(default_factory=dict)
    secret: str = field(default_factory=lambda: secrets.token_hex(16))

    def _hash(self, password: str) -> str:
        return hashlib.sha256(
            (self.secret + ":" + password).encode("utf-8")).hexdigest()

    def register(self, username: str, email: str, password: str) -> UserRecord:
        if username in self.users:
            raise ValueError("user exists")
        rec = UserRecord(username=username, email=email,
                         password_hash=self._hash(password))
        self.users[username] = rec
        return rec

    def authenticate(self, username: str, password: str) -> UserRecord | None:
        rec = self.users.get(username)
        if not rec:
            return None
        if not hmac.compare_digest(rec.password_hash, self._hash(password)):
            return None
        return rec

    def issue_token(self, username: str) -> str:
        tok = secrets.token_urlsafe(24)
        self.tokens[tok] = username
        return tok

    def user_for_token(self, token: str) -> UserRecord | None:
        user = self.tokens.get(token or "")
        return self.users.get(user) if user else None

    def revoke(self, token: str) -> None:
        self.tokens.pop(token or "", None)


STORE = SessionStore()
'''


def detect_domains(requirement: str) -> set[str]:
    text = (requirement or "").lower()
    out: set[str] = set()
    if any(k in text for k in (
        "workbook", "worksheet", "spreadsheet", "formula", "pivot",
        "csv", "formula bar", "工作簿", "工作表", "公式",
    )):
        out.add("formula")
    if any(k in text for k in (
        "sign in", "sign-in", "sign out", "password", "pull request",
        "repository", "github", "commit", "branch protection",
        "注册", "登录", "仓库",
    )):
        out.add("session")
    return out


def ensure_domain_kernels(code_dir: Path, requirement: str) -> list[str]:
    """在 code/_shared/ 落下缺失的内核文件；已存在则跳过。返回写入相对路径。"""
    code_dir = Path(code_dir)
    written: list[str] = []
    domains = detect_domains(requirement)
    if not domains:
        return written
    shared = code_dir / "_shared"
    shared.mkdir(parents=True, exist_ok=True)
    init = shared / "__init__.py"
    if not init.is_file():
        init.write_text(
            '"""共享层（含 domain kernel）。"""\n', encoding="utf-8")
        written.append("_shared/__init__.py")
    mapping = {
        "formula": ("formula_kernel.py", _FORMULA_KERNEL),
        "session": ("session_kernel.py", _SESSION_KERNEL),
    }
    for dom in sorted(domains):
        name, body = mapping[dom]
        path = shared / name
        if path.is_file():
            continue
        path.write_text(body, encoding="utf-8")
        written.append(f"_shared/{name}")
    return written


def kernel_responsibility_note(requirement: str) -> str:
    """注入模块职责的短契约：写码时必须接内核，禁止另起炉灶装死。"""
    domains = detect_domains(requirement)
    if not domains:
        return ""
    lines = ["\n\n【领域内核（已落盘 _shared/，必须 import 使用，禁止空壳重写）】"]
    if "formula" in domains:
        lines.append(
            "- 公式/重算：from _shared.formula_kernel import evaluate, col_row；"
            "网格变更后重算依赖格；错误显示 #ERROR!。"
        )
    if "session" in domains:
        lines.append(
            "- 账号会话：from _shared.session_kernel import STORE；"
            "注册/登录/登出走 STORE；受保护页无会话必须重定向到登录。"
        )
    return "\n".join(lines) + "\n"


def annotate_plans_with_kernels(plans, requirement: str) -> None:
    note = kernel_responsibility_note(requirement)
    if not note or not plans:
        return
    keys_formula = ("formula", "workbook", "worksheet", "grid", "cell",
                    "pivot", "sheet", "表格", "公式")
    keys_session = ("auth", "user", "account", "login", "session",
                    "repo", "pull", "issue", "账号", "登录")
    domains = detect_domains(requirement)
    for plan in plans:
        text = f"{plan.name} {plan.responsibility}".lower()
        need = False
        if "formula" in domains and any(k in text for k in keys_formula):
            need = True
        if "session" in domains and any(k in text for k in keys_session):
            need = True
        # 保底：任一 UI 模块也提示内核存在
        if not need and any(k in text for k in ("ui", "home", "page", "views")):
            need = True
        if need and "领域内核" not in (plan.responsibility or ""):
            plan.responsibility = (plan.responsibility or "") + note
