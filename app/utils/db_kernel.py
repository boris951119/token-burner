# -*- coding: utf-8 -*-
"""数据库标准部件（刀O，db kernel）——sheet_p0 尸检的对症修复。

尸检实证（09-30 sheet_p0，预算 2M 全烧）：
- 39/39 模块的修复史都含「_shared 缺 get_db/init_app」——30 个模块
  每个烧满 5 轮修复全部冻结；
- 规范的 20 行样板（_shared/shared.py：DB_PATH/get_db/init_app）晚到
  7 小时（预算中止前 26 分钟才被写出），整场 2M 预算就烧在这上面；
- 且 _shared/__init__.py 为空时 `from _shared import get_db` 依然会炸
  （包属性未再导出）——两层都要补。

方案：确定性落盘 db_kernel.py + __init__ 再导出补丁（与 domain_kernels
同款只增不改）。落盘后「_shared 缺标准 DB 符号」这一失效类不可能再发生。
"""
from __future__ import annotations

from pathlib import Path

_DB_KERNEL = '''# -*- coding: utf-8 -*-
"""数据库标准部件（token-burner db kernel，可被业务模块 import）。

__arcbench_domain_kernel__ = "db"
标准三件套：DB_PATH / get_db() / init_app(app)。sqlite3 零依赖。
换数据库引擎时保持本模块 API 不变，业务层不改 import。
"""
from __future__ import annotations

import os
import sqlite3

__arcbench_domain_kernel__ = "db"

DB_PATH = os.environ.get("ARC_DB_PATH", "arc_data.db")

__all__ = ["DB_PATH", "get_db", "init_app"]


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_app(app) -> None:
    """Flask 应用接线钩子（teardown 释放连接位）；非 Flask 可不调用。"""
    try:
        @app.teardown_appcontext
        def _close_db(_exc):
            pass
    except Exception:
        pass
'''

_REEXPORT = (
    "# db kernel 标准符号再导出（from _shared import get_db 直达；"
    "09-30 尸检配套）\n"
    "try:\n"
    "    from _shared.db_kernel import DB_PATH, get_db, init_app  "
    "# noqa: F401,F403\n"
    "except Exception:\n"
    "    pass\n"
)


def ensure_db_kernel(code_dir: Path) -> list[str]:
    """落下数据库标准部件 + __init__ 再导出补丁。只增不改，幂等。

    - _shared/db_kernel.py 已存在 → 跳过（作者同名文件优先，不覆盖）；
    - _shared/__init__.py 未含 db_kernel 再导出 → 追加（get_db 已在
      __init__ 显式定义时不补，避免覆盖作者语义）。
    返回写入/修改的相对路径列表。
    """
    code_dir = Path(code_dir)
    shared = code_dir / "_shared"
    shared.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    target = shared / "db_kernel.py"
    if not target.is_file():
        target.write_text(_DB_KERNEL, encoding="utf-8")
        written.append("_shared/db_kernel.py")
    init = shared / "__init__.py"
    cur = init.read_text(encoding="utf-8") if init.is_file() else ""
    if "db_kernel" not in cur and "get_db" not in cur:
        init.write_text(cur + ("\n" if cur.strip() else "") + _REEXPORT,
                        encoding="utf-8")
        written.append("_shared/__init__.py(补再导出)")
    compile(target.read_text(encoding="utf-8"), "db_kernel", "exec")
    return written
