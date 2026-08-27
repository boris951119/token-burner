"""LLM 调用统一封装（规格文档第 17 章第一阶段、第 9 章 API 集成）。

职责：
- 统一经 litellm 调用不同供应商模型（第 9 章）；
- 落实第 2 层护栏（11.2）：每次调用携带 max_tokens = max_response_tokens；
- 模型支持时携带 response_format={"type": "json_object"}（15.1 第 4 级），
  不支持则自动降级为普通调用（提示词层约束由 prompt_templates 负责）；
- 返回结构化 LLMResponse（content + input/output token 用量），
  并维护调用累计与调用日志，供总预算闸门（11.0）与审计（第 5 章）使用；
- 密钥缺失在调用前快速失败（确定性校验，总则 D.1）。

litellm 采用懒加载：测试与无需真实调用的环境不依赖其安装；
completion_fn 可注入桩函数（依赖倒置）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from app.config import MODEL_ENV_KEYS, Settings

# 注入点：调用签名与 litellm.completion 一致
CompletionFn = Callable[..., Any]


class MissingApiKeyError(RuntimeError):
    """已知供应商的 API 密钥缺失（应在发起调用前抛出）。"""


@dataclass
class LLMResponse:
    """单次 LLM 调用的结构化结果（8.4 之外的内部数据结构）。"""

    model: str
    content: str
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _default_completion_fn() -> CompletionFn:
    """懒加载 litellm.completion（沙箱/测试环境无需安装）。"""
    try:
        import litellm
    except ImportError as exc:  # pragma: no cover - 环境缺依赖时的明确报错
        raise ImportError(
            "litellm 未安装，无法发起真实 LLM 调用。"
            "请先安装：pip install litellm"
        ) from exc
    litellm.suppress_debug_info = True
    return litellm.completion


class ModelClient:
    """面向 Agent 的统一模型调用客户端。"""

    def __init__(self, settings: Settings, completion_fn: CompletionFn | None = None):
        self.settings = settings
        self._completion_fn = completion_fn
        # 11.0 可观测性：每步 token 累计
        self.total_tokens_used: int = 0
        # 第 5 章可审计：调用日志（模型、模式、用量）
        self.call_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        json_mode: bool = False,
    ) -> LLMResponse:
        """发起一次对话补全。

        Args:
            model: 模型名称（须已在 Settings.models 登记）。
            messages: OpenAI 风格消息列表。
            json_mode: 请求结构化 JSON 输出（15.1 第 4 级）。

        Raises:
            ValueError: 模型未登记。
            MissingApiKeyError: 已知供应商密钥缺失。
            RuntimeError: 调用失败（含降级重试后仍失败）。
        """
        if model not in self.settings.models:
            raise ValueError(
                f"模型「{model}」未在配置中登记，可用模型: {self.settings.models}"
            )
        self._check_api_key(model)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": self.settings.max_response_tokens,  # 第 2 层护栏
        }
        use_json = json_mode and self.settings.strict_json_response
        if use_json:
            kwargs["response_format"] = {"type": "json_object"}

        completion = self._completion_fn or _default_completion_fn()

        try:
            response = completion(**kwargs)
        except Exception as exc:
            if use_json:
                # 15.1：模型不支持 response_format 时降级为普通调用
                kwargs.pop("response_format", None)
                response = completion(**kwargs)
            else:
                raise RuntimeError(f"LLM 调用失败（{model}）: {exc}") from exc

        return self._build_response(model, response, json_mode=json_mode, messages=messages)

    # ------------------------------------------------------------------

    def _check_api_key(self, model: str) -> None:
        """已知供应商密钥缺失时快速失败（第 5 章：密钥仅从环境变量读取）。"""
        for prefix, env_name in MODEL_ENV_KEYS:
            if model.startswith(prefix):
                if not os.environ.get(env_name):
                    raise MissingApiKeyError(
                        f"模型「{model}」需要环境变量 {env_name}，"
                        "请在 .env 或环境中配置后再调用"
                    )
                return  # 命中已知供应商即结束

    def _build_response(
        self,
        model: str,
        response: Any,
        json_mode: bool,
        messages: list[dict[str, str]] | None = None,
    ) -> LLMResponse:
        """从 litellm 响应提取内容与 token 用量（兼容 dict 与对象两种访问方式）。"""
        content = _get_content(response)
        input_tokens, output_tokens = _get_usage(response)

        result = LLMResponse(
            model=model,
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        # 11.0 累计与第 5 章审计日志
        self.total_tokens_used += result.total_tokens
        self.call_log.append(
            {
                "model": model,
                "json_mode": json_mode,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "content_chars": len(content),
                "system_hint": (messages[0]["content"] if messages else ""),  # 8.5 环节归属
            }
        )
        return result


def _get_content(response: Any) -> str:
    choices = _index(response, "choices")
    if not choices:
        raise RuntimeError("LLM 响应缺少 choices 字段")
    message = _index(choices[0], "message")
    content = _index(message, "content")
    if content is None:
        raise RuntimeError("LLM 响应缺少 message.content 字段")
    return str(content)


def _get_usage(response: Any) -> tuple[int, int]:
    usage = _index(response, "usage")
    if usage is None:
        return 0, 0
    prompt = _index(usage, "prompt_tokens")
    completion = _index(usage, "completion_tokens")
    return int(prompt or 0), int(completion or 0)


def _index(obj: Any, key: str) -> Any:
    """兼容 dict 访问与属性访问（litellm ModelResponse 两者皆可）。"""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
