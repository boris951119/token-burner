"""model_client 单元测试（TDD 先行，全部 mock，不依赖真实 litellm 与网络）。

依据：规格文档 v0.3.1 第 17 章第一阶段：
- 封装 LLM 调用（使用 litellm）；
- 模型支持时携带 response_format={"type": "json_object"}（15.1 第 4 级）；
- 第 2 层护栏：单轮输出上限 max_response_tokens 须作为 max_tokens 传入；
- 11.0 总预算闸门需要每步 token 累计，故调用结果须携带 input/output token 用量；
- 第 5 章安全性：密钥缺失应在调用前快速失败（确定性校验）。
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.utils.model_client import LLMResponse, MissingApiKeyError, ModelClient


def make_response(
    content: str = "ok",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> dict:
    """构造 litellm 风格的响应对象（支持字典访问）。"""
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
        },
    }


class FakeCompletion:
    """记录调用参数的可注入 completion 桩。"""

    def __init__(self, responses=None, fail_on_response_format=False):
        self.calls: list[dict] = []
        self.responses = responses or [make_response()]
        self.fail_on_response_format = fail_on_response_format

    def __call__(self, model: str, messages: list, **kwargs):
        self.calls.append({"model": model, "messages": messages, **kwargs})
        if self.fail_on_response_format and "response_format" in kwargs:
            raise RuntimeError("response_format is not supported by this model")
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


@pytest.fixture
def gpt_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


class TestChatBasics:
    def test_returns_llm_response_with_content(self, gpt_key):
        fake = FakeCompletion(responses=[make_response(content="你好")])
        client = ModelClient(Settings(), completion_fn=fake)
        result = client.chat("gpt-4o", [{"role": "user", "content": "hi"}])
        assert isinstance(result, LLMResponse)
        assert result.content == "你好"
        assert result.model == "gpt-4o"

    def test_passes_model_and_messages(self, gpt_key):
        fake = FakeCompletion()
        client = ModelClient(Settings(), completion_fn=fake)
        messages = [{"role": "user", "content": "hi"}]
        client.chat("gpt-4o", messages)
        assert fake.calls[0]["model"] == "gpt-4o"
        assert fake.calls[0]["messages"] == messages

    def test_max_tokens_from_layer2_guardrail(self, gpt_key):
        # 11.2 第 2 层护栏：单轮输出上限必须传入 max_tokens
        fake = FakeCompletion()
        client = ModelClient(Settings(max_response_tokens=1234), completion_fn=fake)
        client.chat("gpt-4o", [{"role": "user", "content": "hi"}])
        assert fake.calls[0]["max_tokens"] == 1234


class TestTokenUsage:
    def test_usage_extracted(self, gpt_key):
        fake = FakeCompletion(responses=[make_response(input_tokens=100, output_tokens=50)])
        client = ModelClient(Settings(), completion_fn=fake)
        result = client.chat("gpt-4o", [{"role": "user", "content": "hi"}])
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.total_tokens == 150

    def test_usage_missing_defaults_to_zero(self, gpt_key):
        response = {"choices": [{"message": {"content": "ok"}}], "usage": None}
        fake = FakeCompletion(responses=[response])
        client = ModelClient(Settings(), completion_fn=fake)
        result = client.chat("gpt-4o", [{"role": "user", "content": "hi"}])
        assert result.input_tokens == 0
        assert result.output_tokens == 0


class TestJsonMode:
    def test_json_mode_adds_response_format(self, gpt_key):
        # 15.1 第 4 级：模型支持时携带 response_format=json_object
        fake = FakeCompletion()
        client = ModelClient(Settings(), completion_fn=fake)
        client.chat("gpt-4o", [{"role": "user", "content": "hi"}], json_mode=True)
        assert fake.calls[0]["response_format"] == {"type": "json_object"}

    def test_plain_mode_no_response_format(self, gpt_key):
        fake = FakeCompletion()
        client = ModelClient(Settings(), completion_fn=fake)
        client.chat("gpt-4o", [{"role": "user", "content": "hi"}])
        assert "response_format" not in fake.calls[0]

    def test_json_mode_disabled_by_setting(self, gpt_key):
        # 15.5 配置项：可关闭强制 JSON 响应
        fake = FakeCompletion()
        client = ModelClient(Settings(strict_json_response=False), completion_fn=fake)
        client.chat("gpt-4o", [{"role": "user", "content": "hi"}], json_mode=True)
        assert "response_format" not in fake.calls[0]

    def test_json_mode_fallback_when_unsupported(self, gpt_key):
        # 模型不支持 response_format 时降级为普通调用（15.1：不支持的模型走 prompt 约束）
        fake = FakeCompletion(fail_on_response_format=True)
        client = ModelClient(Settings(), completion_fn=fake)
        result = client.chat("gpt-4o", [{"role": "user", "content": "hi"}], json_mode=True)
        assert result.content == "ok"
        assert len(fake.calls) == 2
        assert "response_format" in fake.calls[0]
        assert "response_format" not in fake.calls[1]

    def test_json_mode_failure_still_raises(self, gpt_key):
        # 降级后仍失败 → 向上抛出（15.3：无法降级的关键点给明确失败信息）
        fake = FakeCompletion(fail_on_response_format=True)
        fake_fail_always = _AlwaysFail()
        client = ModelClient(Settings(), completion_fn=fake_fail_always)
        with pytest.raises(RuntimeError):
            client.chat("gpt-4o", [{"role": "user", "content": "hi"}], json_mode=True)


class _AlwaysFail(FakeCompletion):
    def __call__(self, model: str, messages: list, **kwargs):
        self.calls.append({"model": model, "messages": messages, **kwargs})
        raise RuntimeError("api error")


class TestApiKeyValidation:
    def test_missing_api_key_fails_fast(self, monkeypatch):
        # 第 5 章安全性：已知供应商密钥缺失应在发起调用前失败
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        fake = FakeCompletion()
        client = ModelClient(Settings(), completion_fn=fake)
        with pytest.raises(MissingApiKeyError, match="OPENAI_API_KEY"):
            client.chat("gpt-4o", [{"role": "user", "content": "hi"}])
        assert fake.calls == []  # 未发起任何调用

    def test_unknown_provider_not_blocked(self, gpt_key):
        # 未知前缀模型不强制本地密钥校验（交由 litellm 自行处理）
        fake = FakeCompletion()
        client = ModelClient(Settings(models=["qwen-max"]), completion_fn=fake)
        result = client.chat("qwen-max", [{"role": "user", "content": "hi"}])
        assert result.content == "ok"

    def test_unknown_model_rejected_by_settings(self):
        # 模型不在配置列表中 → 确定性拒绝
        fake = FakeCompletion()
        client = ModelClient(Settings(), completion_fn=fake)
        with pytest.raises(ValueError, match="登记"):
            client.chat("not-in-list", [{"role": "user", "content": "hi"}])


class TestTokenAccumulation:
    def test_total_tokens_accumulates(self, gpt_key):
        # 11.0：ModelClient 须支持累计统计，供总预算闸门使用
        fake = FakeCompletion(responses=[make_response(input_tokens=10, output_tokens=5)])
        client = ModelClient(Settings(), completion_fn=fake)
        assert client.total_tokens_used == 0
        client.chat("gpt-4o", [{"role": "user", "content": "a"}])
        client.chat("gpt-4o", [{"role": "user", "content": "b"}])
        assert client.total_tokens_used == 30

    def test_call_log_for_audit(self, gpt_key):
        # 第 5 章可审计：每次调用留有记录（模型、json_mode、token 用量）
        fake = FakeCompletion(responses=[make_response(input_tokens=10, output_tokens=5)])
        client = ModelClient(Settings(), completion_fn=fake)
        client.chat("gpt-4o", [{"role": "user", "content": "a"}], json_mode=True)
        log = client.call_log[0]
        assert log["model"] == "gpt-4o"
        assert log["json_mode"] is True
        assert log["input_tokens"] == 10
        assert log["output_tokens"] == 5


# ---------------------------------------------------------------------------
# 11.2 续写拼接：句中截断时续写头部的真实换行须剥除（bench_v1 试跑取证修复）
# ---------------------------------------------------------------------------
def _length_response(content: str, input_tokens: int = 10, output_tokens: int = 5) -> dict:
    """构造 finish_reason=length 的截断响应。"""
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
    }


class TestContinuationJoin:
    """finish_reason=length 续写拼接（v1.0 V2 试跑发现的换行腐蚀缺陷）。

    事故特征：句中截断 + GLM 续写以真实换行开头 → 拼接点未闭合字符串
    （unterminated string literal）→ 语法门禁拦截 → 修复轮重新生成再次
    截断续写 → 5 轮不收敛 FROZEN。
    """

    def _run(self, responses, gpt_key):
        fake = FakeCompletion(responses=responses)
        client = ModelClient(Settings(models=["gpt-4o"]), completion_fn=fake)
        return client.chat("gpt-4o", [{"role": "user", "content": "写代码"}]), fake

    def test_midline_cut_strips_continuation_leading_newline(self, gpt_key):
        """句中截断：续写开头的真实换行被剥除，字符串原位闭合。"""
        resp, _ = self._run(
            [
                _length_response('f.write("张三,28'),
                make_response(content='\n")\n'),
            ],
            gpt_key,
        )
        assert resp.content == 'f.write("张三,28")\n'
        compile(resp.content, "<bench>", "exec")  # 拼接结果须为合法 Python

    def test_midline_cut_strips_multiple_leading_newlines(self, gpt_key):
        resp, _ = self._run(
            [
                _length_response('x = "abc'),
                make_response(content='\r\n\r\n"'),
            ],
            gpt_key,
        )
        assert resp.content == 'x = "abc"'

    def test_eol_cut_keeps_continuation_verbatim(self, gpt_key):
        """原文结束在行尾：续写内容原样保留（含其自带换行语义）。"""
        resp, _ = self._run(
            [
                _length_response("a = 1\n"),
                make_response(content="\nb = 2\n"),
            ],
            gpt_key,
        )
        assert resp.content == "a = 1\n\nb = 2\n"

    def test_literal_escape_sequence_not_stripped(self, gpt_key):
        """续写以字面反斜杠-n（转义序列文本）开头：不受剥除影响。"""
        resp, _ = self._run(
            [
                _length_response('f.write("data'),
                make_response(content=r'\n")'),
            ],
            gpt_key,
        )
        assert resp.content == r'f.write("data\n")'

    def test_no_continuation_when_finish_stop(self, gpt_key):
        """正常结束（finish_reason 缺失/stop）：单次调用，无续写。"""
        resp, fake = self._run([make_response(content="done")], gpt_key)
        assert resp.content == "done"
        assert len(fake.calls) == 1

    def test_continuation_usage_accumulates(self, gpt_key):
        """续写用量并入总用量（10+10 / 5+5）。"""
        resp, _ = self._run(
            [
                _length_response("part1"),
                make_response(content="part2", input_tokens=10, output_tokens=5),
            ],
            gpt_key,
        )
        assert resp.content == "part1part2"
        assert resp.input_tokens == 20
        assert resp.output_tokens == 10
