"""LLM 调用韧性测试（产品审计问题 3 修复，TDD 先行）。

问题：chat/embed 未设 timeout，也无 429/网络抖动重试——真实环境
一次限流或慢响应直接 RuntimeError 终止整个任务。

修复约定：
- 每次 LLM 调用携带 timeout = llm_timeout_seconds（litellm 参数）；
- 瞬态错误（超时/429/连接/5xx/过载）指数退避重试（llm_max_retries 上限，
  sleep = retry_backoff_base * 2**attempt）；非瞬态错误立即上抛；
- 重试耗尽抛 RuntimeError（含尝试次数，可观测）；续写与 embedding 同享重试。
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.utils.model_client import ModelClient


def _resp(content: str, finish: str = "stop"):
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


class FlakyCompletion:
    """前 fail_times 次抛指定错误，之后成功。"""

    def __init__(self, fail_times: int = 1, error: str = "429 rate limit exceeded"):
        self.fail_times = fail_times
        self.error = error
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) <= self.fail_times:
            raise RuntimeError(self.error)
        return _resp("recovered")


class FlakyEmbedding:
    def __init__(self, fail_times: int = 1, error: str = "connection error"):
        self.fail_times = fail_times
        self.error = error
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) <= self.fail_times:
            raise RuntimeError(self.error)
        return {"data": [{"embedding": [1.0, 0.0]}], "usage": {"prompt_tokens": 3}}


class SleepRecorder:
    def __init__(self):
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


@pytest.fixture
def gpt_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def _client(completion=None, sleep=None, embedding=None, **settings_over):
    return ModelClient(
        Settings(**settings_over),
        completion_fn=completion,
        embedding_fn=embedding,
        sleep_fn=sleep,
    )


_MSG = [{"role": "user", "content": "写"}]


# ---------------------------------------------------------------------------
# timeout 透传
# ---------------------------------------------------------------------------


class TestTimeout:
    def test_timeout_passed_to_completion(self, gpt_key):
        flaky = FlakyCompletion(fail_times=0)
        client = _client(completion=flaky, sleep=SleepRecorder())
        client.chat("gpt-4o", _MSG)
        assert flaky.calls[0]["timeout"] == Settings().llm_timeout_seconds

    def test_timeout_passed_to_embedding(self, gpt_key):
        flaky = FlakyEmbedding(fail_times=0)
        client = _client(completion=FlakyCompletion(fail_times=0),
                         embedding=flaky, sleep=SleepRecorder())
        client.embed("text-embedding-3-small", "文本")
        assert flaky.calls[0]["timeout"] == Settings().llm_timeout_seconds


# ---------------------------------------------------------------------------
# 瞬态错误重试（指数退避）
# ---------------------------------------------------------------------------


class TestTransientRetry:
    def test_transient_error_retried_and_recovers(self, gpt_key):
        # 429 一次 → 退避重试 → 成功
        flaky = FlakyCompletion(fail_times=1)
        sleep = SleepRecorder()
        client = _client(
            completion=flaky, sleep=sleep,
            retry_backoff_base=2.0, llm_max_retries=3,
        )
        result = client.chat("gpt-4o", _MSG)
        assert result.content == "recovered"
        assert len(flaky.calls) == 2
        assert sleep.delays == [2.0]  # base * 2**0

    def test_backoff_exponential_growth(self, gpt_key):
        # 连接错误两次后成功 → 退避 [1.0, 2.0]（base=1）
        flaky = FlakyCompletion(fail_times=2, error="connection reset")
        sleep = SleepRecorder()
        client = _client(
            completion=flaky, sleep=sleep,
            retry_backoff_base=1.0, llm_max_retries=3,
        )
        client.chat("gpt-4o", _MSG)
        assert sleep.delays == [1.0, 2.0]

    def test_retries_exhausted_raises_with_count(self, gpt_key):
        # 重试耗尽 → RuntimeError 含尝试次数（可观测，不静默）
        flaky = FlakyCompletion(fail_times=99, error="connection error")
        sleep = SleepRecorder()
        client = _client(
            completion=flaky, sleep=sleep,
            retry_backoff_base=0.0, llm_max_retries=2,
        )
        with pytest.raises(RuntimeError, match="已重试 2 次"):
            client.chat("gpt-4o", _MSG)
        assert len(flaky.calls) == 3  # 1 次原始 + 2 次重试

    def test_non_transient_error_raises_immediately(self, gpt_key):
        # 参数/请求类错误非瞬态 → 不重试立即上抛
        flaky = FlakyCompletion(fail_times=99, error="invalid request: bad param")
        sleep = SleepRecorder()
        client = _client(completion=flaky, sleep=sleep, llm_max_retries=3)
        with pytest.raises(RuntimeError, match="LLM 调用失败"):
            client.chat("gpt-4o", _MSG)
        assert len(flaky.calls) == 1   # 零重试
        assert sleep.delays == []

    def test_timeout_error_is_transient(self, gpt_key):
        # 超时属瞬态 → 重试
        flaky = FlakyCompletion(fail_times=1, error="Request timed out")
        client = _client(
            completion=flaky, sleep=SleepRecorder(),
            retry_backoff_base=0.0, llm_max_retries=2,
        )
        result = client.chat("gpt-4o", _MSG)
        assert result.content == "recovered"


# ---------------------------------------------------------------------------
# 续写与 embedding 同享重试
# ---------------------------------------------------------------------------


class TestContinuationAndEmbedRetry:
    def test_continuation_survives_transient(self, gpt_key):
        # 原始响应 length 截断；续写第一次瞬态失败 → 重试成功 → 内容完整
        class Scripted:
            def __init__(self):
                self.steps = [
                    _resp("前半", finish="length"),
                    RuntimeError("503 service unavailable"),
                    _resp("后半"),
                ]
                self.calls = 0

            def __call__(self, **kwargs):
                step = self.steps[self.calls]
                self.calls += 1
                if isinstance(step, Exception):
                    raise step
                return step

        scripted = Scripted()
        client = _client(
            completion=scripted, sleep=SleepRecorder(),
            retry_backoff_base=0.0, llm_max_retries=2,
        )
        result = client.chat("gpt-4o", _MSG)
        assert result.content == "前半后半"
        assert not result.truncated

    def test_embed_retries_transient(self, gpt_key):
        flaky = FlakyEmbedding(fail_times=1)
        client = _client(
            completion=FlakyCompletion(fail_times=0), embedding=flaky,
            sleep=SleepRecorder(), retry_backoff_base=0.0, llm_max_retries=2,
        )
        vec = client.embed("text-embedding-3-small", "文本")
        assert vec == [1.0, 0.0]
        assert len(flaky.calls) == 2


# ---------------------------------------------------------------------------
# 配置校验
# ---------------------------------------------------------------------------


class TestSettingsValidation:
    def test_invalid_timeout_rejected(self):
        with pytest.raises(ValueError, match="llm_timeout_seconds"):
            Settings(llm_timeout_seconds=0)

    def test_invalid_retries_rejected(self):
        with pytest.raises(ValueError, match="llm_max_retries"):
            Settings(llm_max_retries=0)

    def test_negative_backoff_rejected(self):
        with pytest.raises(ValueError, match="retry_backoff_base"):
            Settings(retry_backoff_base=-1.0)
