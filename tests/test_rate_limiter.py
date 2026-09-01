"""M8-5 全局 LLM 限流器测试：令牌桶按供应商排队，超限等待而非报错。

设计锚点（v0.4.md M8-5）：
- 令牌桶：容量=burst（瞬时并发），回填=rps；超限阻塞排队，不抛错；
- 供应商键：openai/glm-4-plus → openai；同供应商模型共享桶；
- 全局性：工厂持有单例，所有任务级 ModelClient 共享（M8-1 配合）；
- 429 退避归 9 章重试（_call_with_retry），限流只管「发出前」的节奏；
- 缺省关闭：Settings() 默认 llm_rate_limit_enabled=False，零行为变化。

测试用假时钟（clock/sleep 注入）单线程确定验证：sleep 即推进时钟。
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.utils.model_client import ModelClient, ModelClientFactory
from app.utils.rate_limiter import RateLimiter, provider_of


class FakeClock:
    """假时钟：sleep 即推进（单线程确定性，不真实等待）。

    推进量下限 1e-9s：极小 wait（如 0.1*10 回填的浮点残差 5.68e-15）
    会因 ULP 吸收导致时钟停滞 → elapsed=0 → 死循环（MemoryError）。
    """

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds if seconds > 1e-9 else 1e-9


_OK_RESPONSE = {
    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 2, "completion_tokens": 3},
}


def _limiter(rps: float, burst: int) -> tuple[RateLimiter, FakeClock]:
    fake = FakeClock()
    return RateLimiter(rps, burst, clock_fn=fake.clock, sleep_fn=fake.sleep), fake


# ---------------------------------------------------------------------------
# provider_of：供应商键提取（确定性规则）
# ---------------------------------------------------------------------------

class TestProviderOf:
    def test_prefixed_model(self):
        assert provider_of("openai/glm-4-plus") == "openai"

    def test_same_provider_models_share_key(self):
        assert provider_of("openai/glm-4-plus") == provider_of("openai/glm-4-air")

    def test_bare_model_keyed_by_itself(self):
        assert provider_of("deepseek-chat") == "deepseek-chat"


# ---------------------------------------------------------------------------
# 令牌桶行为（假时钟）
# ---------------------------------------------------------------------------

class TestTokenBucket:
    def test_burst_allows_instant_acquires(self):
        limiter, fake = _limiter(rps=1.0, burst=3)
        assert limiter.acquire("openai") == 0.0
        assert limiter.acquire("openai") == 0.0
        assert limiter.acquire("openai") == 0.0
        assert fake.sleeps == []

    def test_exhausted_bucket_queues(self):
        limiter, fake = _limiter(rps=2.0, burst=1)
        limiter.acquire("openai")
        waited = limiter.acquire("openai")
        assert waited == 0.5  # (1-0)/2 秒后回填一枚令牌
        assert fake.sleeps == [0.5]

    def test_refill_accumulates(self):
        limiter, fake = _limiter(rps=2.0, burst=2)
        limiter.acquire("openai")
        limiter.acquire("openai")
        limiter.acquire("openai")  # 排队 0.5s，回填 1 枚
        assert limiter.acquire("openai") == pytest.approx(0.5)

    def test_never_exceeds_capacity(self):
        limiter, fake = _limiter(rps=10.0, burst=2)
        fake.now = 100.0  # 长时间闲置：桶应停留在容量而非无限累积
        assert limiter.acquire("openai") == 0.0
        assert limiter.acquire("openai") == 0.0
        assert limiter.acquire("openai") > 0.0  # 第三枚必须排队

    def test_providers_isolated(self):
        limiter, fake = _limiter(rps=0.5, burst=1)
        limiter.acquire("openai")           # openai 桶耗尽
        assert limiter.acquire("deepseek") == 0.0  # 其他供应商不受影响
        assert fake.sleeps == []

    def test_invalid_params_rejected(self):
        with pytest.raises(ValueError):
            RateLimiter(rps=0, burst=1)
        with pytest.raises(ValueError):
            RateLimiter(rps=1.0, burst=0)


# ---------------------------------------------------------------------------
# 配置校验与工厂共享（M8-1 配合：全局限流 = 工厂单例）
# ---------------------------------------------------------------------------

class TestConfigAndFactory:
    def test_config_validation(self):
        with pytest.raises(ValueError):
            Settings(llm_rate_limit_enabled=True, llm_rate_limit_rps=0)
        with pytest.raises(ValueError):
            Settings(llm_rate_limit_enabled=True, llm_rate_limit_burst=0)
        # 关闭时不校验（缺省值即合法）
        Settings(llm_rate_limit_rps=0)

    def test_disabled_by_default(self):
        factory = ModelClientFactory(Settings())
        assert factory.create().rate_limiter is None

    def test_factory_builds_shared_limiter_when_enabled(self):
        s = Settings(llm_rate_limit_enabled=True, llm_rate_limit_rps=5.0)
        factory = ModelClientFactory(s)
        c1, c2 = factory.create(), factory.create()
        assert c1.rate_limiter is not None
        assert c1.rate_limiter is c2.rate_limiter  # 全局单例

    def test_factory_injected_limiter_wins(self):
        limiter, _fake = _limiter(1.0, 1)
        factory = ModelClientFactory(Settings(), rate_limiter=limiter)
        assert factory.create().rate_limiter is limiter


# ---------------------------------------------------------------------------
# ModelClient 集成：每次尝试（含 429 重试）先取令牌
# ---------------------------------------------------------------------------

class TestModelClientIntegration:
    def _client(self, limiter, completion_fn) -> ModelClient:
        return ModelClient(
            Settings(models=["openai/glm-4-plus"]),
            completion_fn=completion_fn,
            rate_limiter=limiter,
        )

    def test_acquire_before_each_attempt(self):
        limiter, fake = _limiter(rps=1.0, burst=1)
        client = self._client(limiter, lambda **kw: _OK_RESPONSE)
        for _ in range(3):
            client.chat("openai/glm-4-plus", [{"role": "user", "content": "hi"}])
        assert len(fake.sleeps) == 2  # 首次免排队，后两次各排 1s

    def test_retry_also_acquires(self):
        limiter, fake = _limiter(rps=100.0, burst=100)  # 桶很深：只看取令牌次数
        calls = {"n": 0}

        def flaky(**kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("HTTP 429 too many requests")  # 瞬态 → 重试
            return _OK_RESPONSE

        client = self._client(limiter, flaky)
        client.chat("openai/glm-4-plus", [{"role": "user", "content": "hi"}])
        assert calls["n"] == 2  # 原始尝试 + 429 重试
        assert len(fake.sleeps) == 0

    def test_disabled_limiter_zero_overhead(self):
        seen = {"n": 0}

        def completion(**kw):
            seen["n"] += 1
            return _OK_RESPONSE

        client = ModelClient(
            Settings(models=["m"]),
            completion_fn=completion,
            rate_limiter=None,
        )
        client.chat("m", [{"role": "user", "content": "hi"}])
        assert seen["n"] == 1
