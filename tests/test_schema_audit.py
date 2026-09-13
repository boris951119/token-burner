# -*- coding: utf-8 -*-
"""schema_audit 回归测试（r13 取证：train_id/id 列名漂移导致旅程 FAIL，
修复环 2 轮未定位——确定性审计必须抓住此类缺陷且不误报）。"""

from __future__ import annotations

from pathlib import Path

from app.utils.schema_audit import audit_schema, collect_ddl


def _write(tmp_path: Path, rel: str, text: str) -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


SEED = '''
DDL = """
CREATE TABLE IF NOT EXISTS trains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL
);
"""
'''


class TestCollectDdl:
    def test_parses_columns_and_skips_constraints(self, tmp_path):
        _write(tmp_path, "seed_data/seed_data.py", SEED)
        tables = collect_ddl(tmp_path)
        assert set(tables) == {"trains", "users"}
        assert tables["trains"]["columns"] == [
            "id", "number", "origin", "destination"]

    def test_duplicate_table_definitions_collected(self, tmp_path):
        _write(tmp_path, "seed_data/seed_data.py", SEED)
        _write(tmp_path, "auth/extra.py",
               'x = "CREATE TABLE trains (train_id INTEGER)"')
        tables = collect_ddl(tmp_path)
        assert len(tables["trains"]["sources"]) == 2


class TestAuditFindings:
    def test_r13_case_where_column_drift(self, tmp_path):
        """r13 实证：DDL 列是 id，查询用 WHERE train_id —— 必须命中。"""
        _write(tmp_path, "seed_data/seed_data.py", SEED)
        _write(tmp_path, "search/search.py",
               "sql = \"SELECT * FROM trains WHERE train_id = ?\"\n")
        findings = audit_schema(tmp_path)
        assert findings, "列名漂移必须被发现"
        assert any("train_id" in f and "trains" in f for f in findings)

    def test_insert_unknown_column(self, tmp_path):
        _write(tmp_path, "seed_data/seed_data.py", SEED)
        _write(tmp_path, "auth/auth.py",
               'sql = "INSERT INTO users (username, password_hash, id) '
               "VALUES (?, ?, ?)\"\n")
        findings = audit_schema(tmp_path)
        assert any("id" in f and "INSERT INTO users" in f for f in findings)

    def test_qualified_reference(self, tmp_path):
        _write(tmp_path, "seed_data/seed_data.py", SEED)
        _write(tmp_path, "booking/booking.py",
               'sql = "SELECT * FROM trains t WHERE t.train_id = ?"\n')
        findings = audit_schema(tmp_path)
        # 别名下的限定引用允许漏报（v1 宁漏不误），但直接 t.train_id 中
        # t 不是已知表——此用例只需不崩溃且不误报其他列
        assert all("origin" not in f for f in findings)

    def test_clean_sql_no_findings(self, tmp_path):
        _write(tmp_path, "seed_data/seed_data.py", SEED)
        _write(tmp_path, "search/search.py",
               "sql = \"SELECT number, origin FROM trains "
               "WHERE origin = ? AND destination = ?\"\n")
        assert audit_schema(tmp_path) == []

    def test_unknown_table_ignored(self, tmp_path):
        _write(tmp_path, "seed_data/seed_data.py", SEED)
        _write(tmp_path, "x/x.py",
               'sql = "SELECT * FROM orders WHERE order_id = ?"\n')
        assert audit_schema(tmp_path) == []

    def test_duplicate_ddl_reported(self, tmp_path):
        _write(tmp_path, "seed_data/seed_data.py", SEED)
        _write(tmp_path, "auth/extra.py",
               'x = "CREATE TABLE trains (train_id INTEGER)"')
        findings = audit_schema(tmp_path)
        assert any("多处 CREATE TABLE" in f for f in findings)


class TestSelectListCoverage:
    """r15 取证：SELECT 清单列名漂移（departure vs departure_time）
    曾因清单不覆盖而漏检——恰为 search 500 的直接死因。"""

    def test_select_list_drift_detected(self, tmp_path):
        _write(tmp_path, "seed_data/seed_data.py", SEED)
        _write(tmp_path, "search/search.py",
               'sql = "SELECT train_number, departure, arrival FROM trains '
               'WHERE origin = ?"\n')
        findings = audit_schema(tmp_path)
        assert any("departure" in f for f in findings), findings
        assert any("arrival" in f for f in findings), findings

    def test_select_clean_and_aggregates_skipped(self, tmp_path):
        _write(tmp_path, "seed_data/seed_data.py", SEED)
        _write(tmp_path, "search/search.py",
               'sql = "SELECT DISTINCT number, origin, COUNT(*) AS n '
               'FROM trains WHERE origin = ? GROUP BY number"\n')
        assert audit_schema(tmp_path) == []


class TestSelectLiteralFalsePositive:
    """SELECT '字面量' 不是列——误报会把修复引向不存在的缺陷。"""

    def test_string_literal_in_select_ignored(self, tmp_path):
        _write(tmp_path, "seed_data/seed_data.py", SEED)
        _write(tmp_path, "x/x.py",
               'sql = "SELECT \'1\', number FROM trains WHERE origin = ?"\n')
        findings = audit_schema(tmp_path)
        assert all("'1'" not in f and "'1'" not in repr(f) or "SELECT '1'" not in f
                   for f in findings), findings
        assert not any("1'" in f and "不在 DDL" in f for f in findings), findings

    def test_bare_numeric_literal_ignored(self, tmp_path):
        _write(tmp_path, "seed_data/seed_data.py", SEED)
        _write(tmp_path, "x/x.py",
               'sql = "SELECT 1 FROM trains WHERE origin = ?"\n')
        assert audit_schema(tmp_path) == []


class TestTableDrift:
    """表名漂移：引用不存在的表但存在近名 DDL 表（单复数错位）。"""

    def test_singular_plural_drift_detected(self, tmp_path):
        _write(tmp_path, "seed_data/seed_data.py", SEED)
        _write(tmp_path, "auth/auth.py",
               'sql = "SELECT username FROM user WHERE username = ?"\n')
        findings = audit_schema(tmp_path)
        assert any("疑似应为" in f and "users" in f for f in findings), findings

    def test_unrelated_unknown_table_still_ignored(self, tmp_path):
        _write(tmp_path, "seed_data/seed_data.py", SEED)
        _write(tmp_path, "x/x.py",
               'sql = "SELECT * FROM orders WHERE order_id = ?"\n')
        assert audit_schema(tmp_path) == []

    def test_sqlite_internals_ignored(self, tmp_path):
        _write(tmp_path, "seed_data/seed_data.py", SEED)
        _write(tmp_path, "x/x.py",
               'sql = "SELECT name FROM sqlite_master WHERE type = ?"\n')
        assert audit_schema(tmp_path) == []
