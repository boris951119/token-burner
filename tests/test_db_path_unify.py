# -*- coding: utf-8 -*-
"""库文件路径漂移修复器：种子/迁移模块写错库文件的机械统一。"""
from pathlib import Path

from app.utils.auto_fixer import fix_db_path_unify

CORE_INIT = "from db_core.db_core import init_app\n"
CORE = '''\
from pathlib import Path as _Path

_BASE_DIR = _Path(__file__).resolve().parent
if __package__:
    _BASE_DIR = _BASE_DIR.parent
_DB_PATH = _BASE_DIR / "instance" / "keep.db"


def init_app(app):
    pass
'''
SEED_INIT = "from seed_data.seed_data import init_seed_data\n"
SEED = '''\
import os
import sqlite3

_DEFAULT_DB_PATH = "take_a_note.db"
_ENV_DB_PATH = "TAKE_A_NOTE_DB"


def _get_db_path():
    return os.getenv(_ENV_DB_PATH, _DEFAULT_DB_PATH)


def init_seed_data() -> None:
    conn = sqlite3.connect(_get_db_path())
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER)")
        conn.commit()
    finally:
        conn.close()
'''


def _make_project(tmp_path: Path) -> Path:
    code = tmp_path / "code"
    (code / "db_core").mkdir(parents=True)
    (code / "seed_data").mkdir(parents=True)
    (code / "db_core" / "__init__.py").write_text(CORE_INIT, encoding="utf-8")
    (code / "db_core" / "db_core.py").write_text(CORE, encoding="utf-8")
    (code / "seed_data" / "__init__.py").write_text(SEED_INIT, encoding="utf-8")
    (code / "seed_data" / "seed_data.py").write_text(SEED, encoding="utf-8")
    return code


def test_split_db_paths_get_unified(tmp_path, monkeypatch):
    code = _make_project(tmp_path)
    fixes = fix_db_path_unify(code)
    assert fixes, "两个不同库文件必须被判为分裂并统一"
    assert any("seed_data" in f for f in fixes), fixes
    # 行为级实证：统一后 _DEFAULT_DB_PATH 解析到核心模块的同一文件
    monkeypatch.syspath_prepend(str(code))
    import seed_data.seed_data as sd
    import db_core.db_core as dc
    assert Path(sd._DEFAULT_DB_PATH).resolve() == Path(dc._DB_PATH).resolve()


def test_idempotent_second_run(tmp_path):
    code = _make_project(tmp_path)
    assert fix_db_path_unify(code)
    assert not fix_db_path_unify(code), "第二轮不应再产生修改（幂等）"


def test_same_file_not_touched(tmp_path):
    code = tmp_path / "code"
    (code / "db_core").mkdir(parents=True)
    (code / "db_core" / "db_core.py").write_text(
        'from pathlib import Path as _P\n'
        '_DB_PATH = _P(__file__).resolve().parent / "app.db"\n',
        encoding="utf-8")
    (code / "migrate.py").write_text(
        '_TARGET = "app.db"\n', encoding="utf-8")
    assert not fix_db_path_unify(code), "同名同库不应改写"


def test_cycle_import_skipped(tmp_path):
    code = tmp_path / "code"
    (code / "db_core").mkdir(parents=True)
    (code / "db_core" / "db_core.py").write_text(
        'from pathlib import Path as _P\n'
        'import migrate\n'  # 核心依赖目标模块 → 环，禁止改写
        '_DB_PATH = _P(__file__).resolve().parent / "app.db"\n',
        encoding="utf-8")
    (code / "migrate.py").write_text(
        '_TARGET = "other.db"\n', encoding="utf-8")
    assert not fix_db_path_unify(code), "环导入场景必须跳过"
