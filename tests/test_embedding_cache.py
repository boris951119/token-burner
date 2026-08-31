"""Embedding 缓存测试（M4-1）。

验收锚点（v0.4.md M4-1）：
- 相同内容（同模型）第二次 embed 命中缓存，零 API 调用；
- 缓存键 = 内容哈希 + 模型名称（+维度校验）；
- 按时间过期（默认 7 天）+ 手动清理；
- 只缓存向量，不缓存任何用户内容（隐私决策）；
- 跨任务共享：工厂产出的不同任务级客户端命中同一缓存。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.utils.embedding_cache import EmbeddingCache
from app.utils.model_client import ModelClient, ModelClientFactory


@pytest.fixture
def cache(tmp_path) -> EmbeddingCache:
    return EmbeddingCache(tmp_path / "cache.db", ttl_days=7)


class TestEmbeddingCacheUnit:
    def test_put_get_roundtrip(self, cache):
        vector = [0.1, 0.2, 0.3]
        cache.put("text-embedding-3-small", "hello", vector)
        assert cache.get("text-embedding-3-small", "hello") == vector
        assert (cache.hits, cache.misses) == (1, 0)

    def test_unknown_text_miss(self, cache):
        assert cache.get("m", "missing") is None
        assert cache.misses == 1

    def test_model_is_part_of_key(self, cache):
        vector = [1.0, 2.0]
        cache.put("model-a", "hello", vector)
        assert cache.get("model-b", "hello") is None  # 换模型 → 不命中
        assert cache.get("model-a", "hello") == vector

    def test_ttl_expiry(self, tmp_path):
        # ttl_days=0 → 写入即过期（确定性测试，不依赖 sleep）
        cache = EmbeddingCache(tmp_path / "c.db", ttl_days=0)
        cache.put("m", "hello", [1.0])
        assert cache.get("m", "hello") is None

    def test_purge_expired_and_clear(self, tmp_path):
        cache = EmbeddingCache(tmp_path / "c.db", ttl_days=0)
        cache.put("m", "a", [1.0])
        cache.put("m", "b", [2.0])
        assert cache.purge_expired() == 2
        cache.put("m", "c", [3.0])
        assert cache.clear() == 1
        assert cache.get("m", "c") is None

    def test_content_never_stored(self, cache, tmp_path):
        # 隐私决策：原文不落盘（仅参与哈希）。直接读 db 文件字节验证。
        db_path = Path(cache._conn.execute("PRAGMA database_list").fetchone()[2])
        secret = "用户私有内容 API_KEY=sk-123"
        cache.put("m", secret, [1.0, 2.0])
        cache.get("m", secret)
        raw = db_path.read_bytes()
        assert b"sk-123" not in raw
        assert "私有内容".encode("utf-8") not in raw

    def test_invalid_ttl_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="ttl_days"):
            EmbeddingCache(tmp_path / "c.db", ttl_days=-1)


class TestModelClientCacheWiring:
    def _embedding_stub(self, calls: list):
        def embed_fn(**kw):
            calls.append(kw)
            return {
                "data": [{"embedding": [0.5] * 4}],
                "usage": {"prompt_tokens": 7},
            }
        return embed_fn

    def test_second_embed_hits_cache_zero_api(self, tmp_path):
        calls: list = []
        client = ModelClient(
            Settings(), embedding_fn=self._embedding_stub(calls),
            embedding_cache=EmbeddingCache(tmp_path / "c.db"),
        )
        v1 = client.embed("text-embedding-3-small", "同一段文本")
        v2 = client.embed("text-embedding-3-small", "同一段文本")
        assert v1 == v2 == [0.5] * 4
        assert len(calls) == 1  # 第二次零 API 调用
        assert client.total_tokens_used == 7  # token 只计一次
        hit_entry = client.call_log[-1]
        assert hit_entry["cache_hit"] is True
        assert hit_entry["input_tokens"] == 0

    def test_different_text_misses(self, tmp_path):
        calls: list = []
        client = ModelClient(
            Settings(), embedding_fn=self._embedding_stub(calls),
            embedding_cache=EmbeddingCache(tmp_path / "c.db"),
        )
        client.embed("m", "文本一")
        client.embed("m", "文本二")
        assert len(calls) == 2

    def test_cache_disabled_every_call_hits_api(self):
        calls: list = []
        client = ModelClient(Settings(), embedding_fn=self._embedding_stub(calls))
        client.embed("m", "同一段文本")
        client.embed("m", "同一段文本")
        assert len(calls) == 2  # 缺省关闭：行为与 v0.3.1 一致


class TestFactorySharedCache:
    def test_cross_task_cache_shared(self, tmp_path):
        # 工厂持有单例缓存：任务 A 写入 → 任务 B（新客户端）命中
        calls: list = []
        settings = Settings(
            embedding_cache_enabled=True,
            embedding_cache_path=tmp_path / "c.db",
        )

        def embed_stub(**kw):
            calls.append(kw)
            return {"data": [{"embedding": [0.5] * 4}],
                    "usage": {"prompt_tokens": 7}}

        factory = ModelClientFactory(settings, embedding_fn=embed_stub)
        task_a = factory.create()
        task_b = factory.create()
        v1 = task_a.embed("m", "跨任务共享文本")
        v2 = task_b.embed("m", "跨任务共享文本")
        assert v1 == v2 == [0.5] * 4
        assert len(calls) == 1          # 任务 B 命中缓存，零 API 调用
        assert factory._embedding_cache.hits == 1

    def test_factory_disabled_no_cache(self):
        factory = ModelClientFactory(Settings())
        client = factory.create()
        assert client.embedding_cache is None
