# -*- coding: utf-8 -*-
"""种子账号 kernel（50d1f62e8860 尸检的对症修复，db_kernel 同款只增不改）。

尸检实证：官方登录场景只走 首页→登录→POST，而生成代码把预置账号分散在
业务模块各自的 ensure_seed 里（alice-dev 只在 orgs 模块）——登录入口永远
装不齐 → 401 → 30 场景全灭。提示词约束（v62）管不住结构，这里改为：
题面 pre-provisioned 账号由本模块**确定性抽取并落盘** _shared/seed_accounts.py，
登录/认证模块只被要求机械引用。"种子分裂"这一失效类从结构上消灭。
"""
from __future__ import annotations

import re
from pathlib import Path

from app.utils.seed_accounts import extract_seed_accounts

_TEMPLATE = '''# -*- coding: utf-8 -*-
"""预置账号唯一权威清单（token-burner seed kernel，由题面机械抽取）。

官方评测以这些账号直接登录（不先逛任何业务页）。登录/认证模块的
首请求引导**必须**执行：

    from _shared.seed_accounts import register_all
    register_all(STORE)          # STORE 为 _shared.session_kernel.SessionStore()

禁止把预置账号分散到业务模块各自的初始化——分散 = 登录 401 全场 0 分。
"""
from __future__ import annotations

SEED_ACCOUNTS = %(accounts)r


def register_all(store) -> int:
    """把全部预置账号注册进会话存储（幂等），返回新注册数。"""
    n = 0
    for username, email, password in SEED_ACCOUNTS:
        if username not in (getattr(store, "users", None) or dict()):
            store.register(username, email, password)
            n += 1
    return n


def ensure_db_rows(get_db, hash_fn) -> int:
    """预置账号落库（幂等）：users(username, email, password_hash) 表。"""
    n = 0
    try:
        conn = get_db()
        for username, email, password in SEED_ACCOUNTS:
            row = conn.execute(
                "SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO users (username, email, password_hash) "
                    "VALUES (?, ?, ?)", (username, email, hash_fn(password)))
                n += 1
        conn.commit()
    except Exception:
        pass
    return n
'''


def ensure_seed_accounts(code_dir: Path, requirement_text: str) -> list[str]:
    """从题面抽预置账号 → 落盘 _shared/seed_accounts.py。只增不改。

    题面无 pre-provisioned 账号（如 sheet）→ 不落盘不干预（零行为）。
    作者同名文件已存在 → 跳过（不覆盖）。
    返回写入的相对路径列表。
    """
    accounts = extract_seed_accounts(requirement_text or "")
    if not accounts:
        return []
    code_dir = Path(code_dir)
    shared = code_dir / "_shared"
    shared.mkdir(parents=True, exist_ok=True)
    target = shared / "seed_accounts.py"
    if target.is_file():
        # 作者已写同名文件：只要它含全部官方账号就放行，否则**追加**官方清单
        # （改名不覆盖：seed_accounts_official.py，提示词与闸都认官方文件）
        try:
            have = target.read_text(encoding="utf-8")
        except OSError:
            have = ""
        missing = [a for a in accounts if a[0] not in have]
        if not missing:
            return []
        alt = shared / "seed_accounts_official.py"
        alt.write_text(_TEMPLATE % {"accounts": accounts}, encoding="utf-8")
        compile(alt.read_text(encoding="utf-8"), "seed_accounts_official", "exec")
        return ["_shared/seed_accounts_official.py(官方清单追加)"]
    target.write_text(_TEMPLATE % {"accounts": accounts}, encoding="utf-8")
    compile(target.read_text(encoding="utf-8"), "seed_accounts", "exec")
    return ["_shared/seed_accounts.py"]
