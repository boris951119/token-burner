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


# ---------------------------------------------------------------------------
# factory26 网关长挂防御（墙钟上限）
# ---------------------------------------------------------------------------


class HangingCompletion:
    """模拟网关长挂：阻塞超过任何合理墙钟（滴字续命绕过 read timeout）。"""

    def __init__(self, hold: float = 30.0):
        self.hold = hold
        self.calls = 0

    def __call__(self, **kwargs):
        import time

        self.calls += 1
        time.sleep(self.hold)
        return _resp("too late")


class TestWallClockDefense:
    def test_off_by_default_passthrough(self, gpt_key):
        """llm_wall_clock_seconds 缺省 0：产品路径零行为变化（无线程）。"""
        flaky = FlakyCompletion(fail_times=0)
        client = _client(completion=flaky, sleep=SleepRecorder())
        resp = client.chat("gpt-4o", _MSG)
        assert resp.content == "recovered"

    def test_hanging_call_aborted_no_same_leg_retry(self, gpt_key):
        """keep7v 取证：墙钟超时已耗 limit 秒，同腿重试只会再耗一次
        （网关挂连接 ×(1+重试)×20min 可烧穿整条链）——超时即换腿，
        立即上抛交上层模型备胎链。"""
        import threading

        hanging = HangingCompletion(hold=30.0)
        recorder = SleepRecorder()
        client = _client(
            completion=hanging,
            sleep=recorder,
            llm_wall_clock_seconds=1,
            llm_max_retries=3,
            retry_backoff_base=0.01,
        )
        with pytest.raises(RuntimeError, match="墙钟上限"):
            client.chat("gpt-4o", _MSG)
        assert hanging.calls == 1          # 仅 1 次尝试，无同腿重试
        assert recorder.delays == []       # 零退避睡眠
        # 守护线程遗留 ≤1，随 hold 到期自行消散
        assert threading.active_count() >= 1

    def test_fast_call_unaffected_by_wall_clock(self, gpt_key):
        """正常速度调用在墙钟内完成：结果原样返回，不引入额外开销。"""
        flaky = FlakyCompletion(fail_times=1, error="429 rate limit")
        recorder = SleepRecorder()
        client = _client(
            completion=flaky,
            sleep=recorder,
            llm_wall_clock_seconds=10,
            retry_backoff_base=0.01,
        )
        resp = client.chat("gpt-4o", _MSG)
        assert resp.content == "recovered"

    def test_timeout_error_is_transient_marker(self):
        from app.utils.model_client import _is_transient

        assert _is_transient(TimeoutError("墙钟 600s timed out"))


# ---------------------------------------------------------------------------
# shape-keep 彩排取证（9/23）：真实网关超时从未命中「换腿」快通道
# ---------------------------------------------------------------------------


class GatewayTimeout(Exception):
    """形态仿真：litellm.Timeout 的 MRO **不含**内建 TimeoutError。

    真身链条 Timeout→APITimeoutError→APIConnectionError→OpenAIError→
    Exception：openai 异常树挂在 Exception 下，与内建 TimeoutError
    （OSError 分支）素无瓜葛——所以 isinstance(exc, TimeoutError) 只在
    自造墙钟异常上成立，生产路径上的超时一律走「瞬态 → 同腿退避重试」。
    """


class AlwaysGatewayTimeout:
    def __init__(self):
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        raise GatewayTimeout(
            "litellm.Timeout: APITimeoutError - Request timed out.")


class TestTimeoutSwitchesLeg:
    """超时＝这条腿已经把这段时间实打实烧完，同腿再烧一次不会更快。"""

    def test_gateway_timeout_escalates_without_same_leg_retry(self, gpt_key):
        """彩排实害：讨论阶段一条腿吃满 (1+3)×120s，3 模型链 24 分钟空烧
        后整跑 rc=1、零交付。修后一次超时即上抛，交上层模型备胎链。"""
        boom = AlwaysGatewayTimeout()
        recorder = SleepRecorder()
        client = _client(
            completion=boom, sleep=recorder,
            llm_max_retries=3, retry_backoff_base=0.01,
        )
        with pytest.raises(RuntimeError) as ei:
            client.chat("gpt-4o", _MSG)
        assert boom.calls == 1, "超时不得同腿重试"
        assert recorder.delays == [], "超时不得同腿退避"
        assert "已重试" not in str(ei.value)

    def test_wall_clock_timeout_still_switches_leg(self, gpt_key):
        """内建 TimeoutError（墙钟）走同一判定，旧行为不回退。"""
        from app.utils.model_client import _is_timeout

        assert _is_timeout(TimeoutError("墙钟上限 600s"))

    def test_real_litellm_timeout_shape(self):
        """钉住真实 SDK 形态：类名含 Timeout 且不是内建 TimeoutError。"""
        pytest.importorskip("litellm")
        from litellm.exceptions import Timeout as LiteLLMTimeout

        from app.utils.model_client import _is_timeout

        exc = LiteLLMTimeout(
            message="Request timed out.", model="gpt-4o", llm_provider="openai")
        assert not isinstance(exc, TimeoutError)  # 旧判定为何失灵
        assert _is_timeout(exc)

    def test_message_mentioning_timeout_keeps_same_leg_retry(self):
        """只按类名匹配，不误伤「消息里带 timeout 字样」的可同腿重试错误
        （429 响应体常含该字样，换腿反而丢掉唯一健康的模型）。"""
        from app.utils.model_client import _is_timeout, _is_transient

        exc = RuntimeError("429 rate limit: retry-after timeout bucket")
        assert not _is_timeout(exc)
        assert _is_transient(exc)

    def test_gateway_timeout_recovers_on_second_leg(self, gpt_key):
        """端到端：一条腿超时后编排层换腿仍能拿到评审——备胎链接力见
        test_discussion_fallback.py（评审路径彩排当场夭折）。"""
        calls = []

        def completion(**kwargs):
            calls.append(kwargs["model"])
            if len(calls) == 1:
                raise GatewayTimeout("litellm.Timeout: Request timed out.")
            return _resp("ok")

        client = _client(
            completion=completion, sleep=SleepRecorder(),
            llm_max_retries=3, retry_backoff_base=0.01,
            models=["gpt-4o", "gpt-4o-mini"],
        )
        with pytest.raises(RuntimeError):
            client.chat("gpt-4o", _MSG)   # ModelClient 不换腿，交上层
        resp = client.chat("gpt-4o-mini", _MSG)
        assert resp.content == "ok"
        assert calls == ["gpt-4o", "gpt-4o-mini"]


class ContentlessThenGood:
    """r7b 取证：网关偶发返回 message.content 缺失的响应（评审模型）。"""

    def __init__(self):
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {"choices": [{"message": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 0}}
        return _resp("recovered")


class TestContentlessResponse:
    def test_contentless_is_transient_and_retried(self, gpt_key):
        """content 缺失 = 网关抖动 → 瞬态重试恢复，不再当场谋杀任务。"""
        flaky = ContentlessThenGood()
        recorder = SleepRecorder()
        client = _client(completion=flaky, sleep=recorder,
                         retry_backoff_base=0.01)
        result = client.chat("gpt-4o", _MSG)
        assert result.content == "recovered"
        assert flaky.calls == 2

    def test_contentless_exhausted_raises_with_count(self, gpt_key):
        from app.utils.model_client import _is_transient

        class _AlwaysContentless:
            def __init__(self):
                self.calls = 0

            def __call__(self, **kwargs):
                self.calls += 1
                return {"choices": [{"message": {}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 0}}

        flaky = _AlwaysContentless()
        client = _client(completion=flaky, sleep=SleepRecorder(),
                         llm_max_retries=1, retry_backoff_base=0.01)
        with pytest.raises(RuntimeError, match="已重试 1 次"):
            client.chat("gpt-4o", _MSG)
        assert flaky.calls == 2  # 1 次首发 + 1 次重试（构建纳入重试范围）
        assert _is_transient(RuntimeError("LLM 响应缺少 message.content 字段"))


# ---------------------------------------------------------------------------
# factory26 r7c：推理模型吃满 max_tokens → finish=length + content 空 → 扩容重试
# ---------------------------------------------------------------------------


class _LengthEmptyThenGood:
    """首两次返回「推理吃满预算」形态（finish=length, content 空），第三次正常。"""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) <= 2:
            return {"choices": [{"message": {"content": ""},
                                 "finish_reason": "length"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": kwargs["max_tokens"]}}
        return _resp("finally")


class TestEmptyContentBudgetExpansion:
    def test_empty_length_doubles_max_tokens_and_recovers(self, gpt_key):
        flaky = _LengthEmptyThenGood()
        client = _client(completion=flaky, sleep=SleepRecorder(),
                         max_response_tokens=3000, retry_backoff_base=0.01)
        result = client.chat("gpt-4o", _MSG)
        assert result.content == "finally"
        caps = [c["max_tokens"] for c in flaky.calls]
        assert caps == [3000, 6000, 12000]  # 翻倍序列
        assert flaky.calls[2]["max_tokens"] == 12000

    def test_ceiling_caps_expansion(self, gpt_key):
        """预算已到天花板附近：不再翻倍，保留空内容结果交给上层。"""
        flaky = _LengthEmptyThenGood()
        flaky.calls.append({"max_tokens": 24000})  # 预热：下次调用起全为坏
        client = _client(completion=flaky, sleep=SleepRecorder(),
                         max_response_tokens=24000, retry_backoff_base=0.01)
        result = client.chat("gpt-4o", _MSG)
        # 24000 已达天花板 → 不扩容（new_cap <= cap → break）；
        # 后续 finish=length 走既有续写通道救回内容
        assert all(c["max_tokens"] <= 24000 for c in flaky.calls)

    def test_normal_content_skips_expansion(self, gpt_key):
        flaky = FlakyCompletion(fail_times=0)
        client = _client(completion=flaky, sleep=SleepRecorder())
        client.chat("gpt-4o", _MSG)
        assert flaky.calls[0]["max_tokens"] == client.settings.max_response_tokens


class TestNullContentReasoningExhaustion:
    """r7c-2 取证：glm-5.2 推理吃满预算返回 content=null（非空串）——
    _get_content 原地抛错会绕过扩容通道，带同预算重试确定性复现。"""

    def _resp_null(self):
        return {"choices": [{"message": {"content": None},
                             "finish_reason": "length"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 120}}

    def test_null_content_with_length_yields_empty_for_expansion(self, gpt_key):
        """finish=length + content=null → 空串放行（进扩容通道），不抛错。"""
        from app.utils.model_client import _get_content

        assert _get_content(self._resp_null()) == ""

    def test_null_content_with_stop_still_raises(self, gpt_key):
        """finish=stop + content=null：真异常响应，保留瞬态重试路径。"""
        from app.utils.model_client import _get_content

        resp = {"choices": [{"message": {"content": None},
                             "finish_reason": "stop"}], "usage": {}}
        with pytest.raises(RuntimeError, match="message.content"):
            _get_content(resp)

    def test_null_content_expands_budget_and_recovers(self, gpt_key):
        """端到端：null+length → 空串 → 扩容翻倍重试 → 正常内容返回。"""
        calls = []

        def flaky(**kwargs):
            calls.append(kwargs["max_tokens"])
            if len(calls) == 1:
                return self._resp_null()
            return _resp("recovered")

        recorder = SleepRecorder()
        client = _client(completion=flaky, sleep=recorder,
                         max_output_continuations=1)
        result = client.chat("gpt-4o", _MSG)
        assert result.content == "recovered"
        assert calls[0] == Settings().max_response_tokens
        assert calls[1] == Settings().max_response_tokens * 2  # 扩容翻倍
