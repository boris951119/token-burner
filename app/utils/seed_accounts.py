# -*- coding: utf-8 -*-
"""种子账号抽取器（50d1f62e8860 尸检）：题面 GIVEN 的 pre-provisioned 账号
→ 确定性三元组 → kernel 落盘，模型只引用不自造。

官方登录场景只走 首页→登录→POST：种子账号若由各业务模块分散注册，
登录入口永远装不齐 → 401 → 全场 0 分。本模块把"官方到底预置了哪些
账号"从题面机械抽出，作为唯一权威清单。
"""
from __future__ import annotations

import re

# 官方句式（stage-1 实测 4 处）：
#   pre-provisioned a verified and available account with username
#   `alice-dev`, email `alice.dev@example.test`, and password `Valid-password-123!`
# YAML 折行已在调用侧归一为空格。
_ACCOUNT_RE = re.compile(
    r"pre-?provisioned[^`]{0,200}?username\s*`([^`]+)`\s*,\s*email\s*`([^`]+)`"
    r"\s*,\s*and\s+password\s*`([^`]+)`",
    re.IGNORECASE,
)


def extract_seed_accounts(text: str) -> list[tuple[str, str, str]]:
    """题面全文 → [(username, email, password)]，去重保序。"""
    if not text:
        return []
    flat = re.sub(r"\s+", " ", text)
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for m in _ACCOUNT_RE.finditer(flat):
        u, e, p = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        if u and u.lower() not in seen:
            seen.add(u.lower())
            out.append((u, e, p))
    return out
