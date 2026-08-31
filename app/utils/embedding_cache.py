"""Embedding 本地缓存（规格 M4-1，SQLite 单文件）。

键 = sha256(模型名 + \\0 + 文本)；值 = JSON 向量 + 维度 + 写入时间。

隐私决策（v0.4.md M4）：只缓存向量，不缓存任何用户私有内容——
原文仅参与哈希运算，不落盘。
线程安全：内部互斥锁（B3 并发改造后多任务共享同一缓存实例）。
失效：按时间过期（默认 7 天，初始化时惰性清理）+ clear() 手动清空。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS embeddings (
    key TEXT PRIMARY KEY,
    vector TEXT NOT NULL,
    dim INTEGER NOT NULL,
    created_at REAL NOT NULL
)
"""

# M4-4：tokens 列（原调用 prompt_tokens，命中时用于节省量统计）；
# 旧库无此列 → ALTER 幂等补齐
_TOKENS_MIGRATION = (
    "ALTER TABLE embeddings ADD COLUMN tokens INTEGER NOT NULL DEFAULT 0"
)


def _cache_key(model: str, text: str) -> str:
    return hashlib.sha256(f"{model}\x00{text}".encode("utf-8")).hexdigest()


class EmbeddingCache:
    """跨任务共享的 embedding 向量缓存（命中即零 API 调用、零 token）。"""

    def __init__(self, db_path: Path | str, ttl_days: int = 7):
        if not isinstance(ttl_days, int) or isinstance(ttl_days, bool) or ttl_days < 0:
            raise ValueError(f"ttl_days 必须为非负整数，当前值: {ttl_days!r}")
        self.ttl_seconds = ttl_days * 86400
        # 命中率统计（M4-4 看板的数据源，先落计数）
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(_SCHEMA)
        try:
            self._conn.execute(_TOKENS_MIGRATION)
        except sqlite3.OperationalError:
            pass  # 列已存在（旧库升级路径）
        self._conn.commit()
        self.purge_expired()
        # M4-4：命中节省的 token 累计（进程级观测）
        self.saved_tokens = 0

    # ------------------------------------------------------------------

    def get(self, model: str, text: str) -> list[float] | None:
        """命中返回向量（旧接口，语义不变）；未命中/过期/维度异常返回 None。"""
        vector, _saved = self.lookup(model, text)
        return vector

    def lookup(self, model: str, text: str) -> tuple[list[float] | None, int]:
        """M4-4：查询缓存，返回 (向量或 None, 命中时节省的 token 数)。

        未命中返回 (None, 0)；命中时 saved = 原调用 prompt_tokens
        （本次零 API 调用、零消耗）。计数器 hits/misses/saved_tokens 同步累计。
        """
        key = _cache_key(model, text)
        with self._lock:
            row = self._conn.execute(
                "SELECT vector, dim, created_at, tokens FROM embeddings WHERE key=?",
                (key,),
            ).fetchone()
        if row is None:
            self.misses += 1
            return None, 0
        vector_json, dim, created_at, tokens = row
        if time.time() - created_at > self.ttl_seconds:
            # ttl_seconds=0 → 写入即过期（极端配置的确定性语义）
            with self._lock:
                self._conn.execute("DELETE FROM embeddings WHERE key=?", (key,))
                self._conn.commit()
            self.misses += 1
            return None, 0
        vector = json.loads(vector_json)
        if len(vector) != dim:
            self.misses += 1
            return None, 0
        saved = int(tokens or 0)
        self.hits += 1
        self.saved_tokens += saved
        return vector, saved

    def put(
        self, model: str, text: str, vector: list[float], tokens: int = 0
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?, ?, ?)",
                (_cache_key(model, text), json.dumps(vector), len(vector),
                 time.time(), int(tokens)),
            )
            self._conn.commit()

    # ------------------------------------------------------------------

    def purge_expired(self) -> int:
        """删除过期条目，返回删除数（初始化时惰性执行）。"""
        cutoff = time.time() - self.ttl_seconds
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM embeddings WHERE created_at < ?", (cutoff,)
            )
            self._conn.commit()
            return cur.rowcount

    def clear(self) -> int:
        """手动清空（M4：清理入口），返回删除条数。"""
        with self._lock:
            cur = self._conn.execute("DELETE FROM embeddings")
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()
