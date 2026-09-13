# -*- coding: utf-8 -*-
"""确定性 schema 审计：DDL 列 vs SQL 引用列的零 LLM diff（r13 取证）。

r13 旅程 FAIL 的根因是 search 模块 SELECT * 返回 id 列、detail 模块
WHERE train_id = ?——DDL 里根本没有 train_id。这类「模块内/跨模块
schema 漂移」用纯正则即可确定性发现，不该指望修复 LLM 从旅程级输出
里悟出来。

设计取向（务必保持）：**宁漏报不误报**——审计结论会直接注入修复指令，
误报会把修复引向不存在的缺陷。只有高置信信号才报告：
- 限定引用 ``表.列``（表已知且列不存在）；
- 单表语句的 WHERE/AND/OR/ORDER BY 馆导标识符后跟比较符或 IN；
- INSERT INTO 表 (列清单) 中 DDL 不存在的列。
表未知（别名/子查询/多表 JOIN）一律跳过。返回人类可读结论列表，
空列表 = 未发现漂移（不等于不存在）。
"""

from __future__ import annotations

import re
from pathlib import Path

# DDL 建表语句头（CREATE TABLE 名 (...）
_DDL_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'\[`]?(\w+)[\"'\]]?\s*\(",
    re.IGNORECASE,
)
# 约束行首词（非列定义）
_CONSTRAINT_WORDS = {
    "PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT", "KEY", "INDEX",
}
# 含 SQL 关键字的字符串字面量（启发式：引号内出现语句关键字即视为 SQL）
_SQL_LITERAL_RE = re.compile(
    r"['\"]([^'\"\n]*?\b(?:SELECT\b|INSERT\s+INTO\b|UPDATE\s+\w+|"
    r"DELETE\s+FROM\b)[^'\"\n]*?)['\"]",
    re.IGNORECASE,
)
_TABLE_RE = re.compile(
    r"\b(?:FROM|INTO|UPDATE|JOIN)\s+[\"'\[`]?(\w+)[\"'\]]?", re.IGNORECASE)
_QUALIFIED_RE = re.compile(r"\b(\w+)\.(\w+)\b")
# WHERE/AND/OR 后的「标识符 比较符」形态（即列引用）
_PREDICATE_RE = re.compile(
    r"\b(?:WHERE|AND|OR)\s+([a-zA-Z_]\w*)\s*(?:=|!=|<>|<=|>=|<|>|LIKE|IN|BETWEEN|IS)",
    re.IGNORECASE)
_INSERT_COLS_RE = re.compile(
    r"INSERT\s+INTO\s+[\"'\[`]?(\w+)[\"'\]]?\s*\(([^)]*)\)", re.IGNORECASE)


def _split_table_body(src: str, start: int) -> tuple[str, int]:
    """从 '(' 起做括号配平，返回 (体内文, 结束位置)。"""
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                return src[start + 1:i], i
    return src[start + 1:], len(src) - 1  # 未闭合：尽力而为


def _parse_columns(body: str) -> list[str]:
    """建表体内文 → 列名列表（跳过约束行）。"""
    cols: list[str] = []
    for part in body.split(","):
        part = part.strip()
        if not part:
            continue
        first = re.match(r"[\"'\[`]?(\w+)", part)
        if not first:
            continue
        word = first.group(1)
        if word.upper() in _CONSTRAINT_WORDS:
            continue
        cols.append(word.lower())
    return cols


def collect_ddl(code_dir: Path) -> dict[str, dict[str, list[str]]]:
    """扫描目录内全部 .py 的 CREATE TABLE。

    返回 {表名: {"columns": [...], "sources": ["文件:行"]}}。
    同名表多处定义全部保留（漂移检测素材）。
    """
    tables: dict[str, dict[str, list[str]]] = {}
    for py in sorted(code_dir.rglob("*.py")):
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _DDL_RE.finditer(src):
            name = m.group(1).lower()
            body, _end = _split_table_body(src, m.end() - 1)
            cols = _parse_columns(body)
            line = src.count("\n", 0, m.start()) + 1
            rel = f"{py.relative_to(code_dir).as_posix()}:{line}"
            if name in tables:
                tables[name]["columns"] = sorted(
                    set(tables[name]["columns"]) | set(cols))
                tables[name]["sources"].append(rel)
            else:
                tables[name] = {"columns": cols, "sources": [rel]}
    return tables


def _statement_tables(sql: str) -> set[str]:
    return {t.lower() for t in _TABLE_RE.findall(sql)}


def _known_single_table(sql: str, tables: dict) -> str | None:
    """语句的表若无歧义（恰好一个已知表）则返回之，否则 None。"""
    refs = _statement_tables(sql)
    known = {t for t in refs if t in tables}
    return known.pop() if len(known) == 1 else None


def audit_schema(code_dir: Path) -> list[str]:
    """审计目录内 SQL 引用与 DDL 的列名漂移。

    返回结论列表（人类可读，供修复指令直接引用）；空 = 未发现。
    """
    tables = collect_ddl(code_dir)
    if not tables:
        return []
    findings: list[str] = []
    seen: set[str] = set()

    def _flag(msg: str) -> None:
        if msg not in seen:
            seen.add(msg)
            findings.append(msg)

    for py in sorted(code_dir.rglob("*.py")):
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = py.relative_to(code_dir).as_posix()
        for m in _SQL_LITERAL_RE.finditer(src):
            sql = m.group(1)
            line = src.count("\n", 0, m.start()) + 1
            where = f"{rel}:{line}"

            # 1) INSERT INTO 表 (col, ...) —— 清单里 DDL 不存在的列
            for im in _INSERT_COLS_RE.finditer(sql):
                table, colspec = im.group(1).lower(), im.group(2)
                if table not in tables:
                    continue
                for col in colspec.split(","):
                    col = col.strip().strip("'\"[]`").lower()
                    if col and col not in tables[table]["columns"]:
                        _flag(
                            f"{where}: INSERT INTO {table} 引用列 {col!r} "
                            f"不在 DDL（{tables[table]['sources'][0]}，列:"
                            f" {', '.join(tables[table]['columns'])}）")

            # 2) 限定引用 表.列（表已知、第二段非列）
            for qm in _QUALIFIED_RE.finditer(sql):
                table, col = qm.group(1).lower(), qm.group(2).lower()
                if (table in tables and col not in tables[table]["columns"]
                        and col not in _SQL_KEYWORDS):
                    _flag(
                        f"{where}: {table}.{col} —— 列 {col!r} 不在表 "
                        f"{table} 的 DDL（列: "
                        f"{', '.join(tables[table]['columns'])}）")

            # 3) 单表语句的 WHERE/AND/OR 谓词首标识符
            table = _known_single_table(sql, tables)
            if table is None:
                continue
            for pm in _PREDICATE_RE.finditer(sql):
                col = pm.group(1).lower()
                if col not in tables[table]["columns"] and col != "not":
                    _flag(
                        f"{where}: 查询 {table} 时 WHERE 谓词引用 {col!r} "
                        f"不在 DDL（列: "
                        f"{', '.join(tables[table]['columns'])}）")

    # 4) 同名表多处定义（两套 DDL 本身就是漂移源）
    for name, info in tables.items():
        if len(info["sources"]) > 1:
            _flag(f"表 {name} 存在多处 CREATE TABLE 定义: "
                  f"{', '.join(info['sources'])}——表结构唯一权威是 "
                  f"seed_data 模块，请合并")
    return findings


_SQL_KEYWORDS = {
    "select", "from", "where", "and", "or", "not", "null", "join", "on",
    "group", "order", "by", "limit", "offset", "as", "set", "values",
    "into", "distinct", "case", "when", "then", "else", "end", "exists",
    "in", "like", "between", "is", "update", "insert", "delete", "having",
}
