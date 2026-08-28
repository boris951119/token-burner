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
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.config import MODEL_ENV_KEYS, Settings
from app.utils.budget import BudgetGuard

# 注入点：调用签名与 litellm.completion / litellm.embedding 一致
CompletionFn = Callable[..., Any]
EmbeddingFn = Callable[..., Any]

# 9 章韧性：瞬态错误特征（超时/限流/连接/过载/5xx）→ 指数退避重试；
# 其余错误（参数/鉴权类）非瞬态 → 立即上抛。匹配异常类名 + 消息文本。
_TRANSIENT_MARKERS: tuple[str, ...] = (
    "timeout", "timed out",
    "connection", "connect error",
    "429", "rate limit", "ratelimit", "too many requests",
    "temporarily", "overloaded", "unavailable",
    "502", "503", "504", "internal server error",
)


def _is_transient(exc: Exception) -> bool:
    """判断异常是否为瞬态（可退避重试）。"""
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


class MissingApiKeyError(RuntimeError):
    """已知供应商的 API 密钥缺失（应在发起调用前抛出）。"""


@dataclass
class LLMResponse:
    """单次 LLM 调用的结构化结果（8.4 之外的内部数据结构）。"""

    model: str
    content: str
    input_tokens: int
    output_tokens: int
    # 11.2：续写上限耗尽仍截断 → 按未完成处理（交调用方决策，不静默丢弃）
    truncated: bool = False

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


def _default_embedding_fn() -> EmbeddingFn:
    """懒加载 litellm.embedding（同 completion 的懒加载模式）。"""
    try:
        import litellm
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "litellm 未安装，无法发起 embedding 调用。"
            "请先安装：pip install litellm"
        ) from exc
    litellm.suppress_debug_info = True
    return litellm.embedding


def _get_embedding(response: Any) -> tuple[list[float], int]:
    """从 litellm embedding 响应提取向量与 token 用量。"""
    data = _index(response, "data")
    if not data:
        raise RuntimeError("embedding 响应缺少 data 字段")
    vector = _index(data[0], "embedding")
    if vector is None:
        raise RuntimeError("embedding 响应缺少 embedding 向量")
    usage = _index(response, "usage") or {}
    prompt_tokens = int(_index(usage, "prompt_tokens") or 0)
    return list(vector), prompt_tokens


class ModelClientEmbedder:
    """Embedder 协议适配器（11.3：LoopDetector ← ModelClient.embed）。

    失败安全降级：embed 调用失败时返回空向量（余弦=0 → 不误判
    重复），讨论流程不中断；失败已在 ModelClient 侧记入观测日志。
    """

    def __init__(self, client: "ModelClient", model: str):
        self._client = client
        self._model = model

    def embed(self, text: str) -> list[float]:
        try:
            return self._client.embed(self._model, text)
        except Exception:
            return []


class ModelClient:
    """面向 Agent 的统一模型调用客户端。"""

    def __init__(
        self,
        settings: Settings,
        completion_fn: CompletionFn | None = None,
        budget_guard: BudgetGuard | None = None,
        embedding_fn: EmbeddingFn | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ):
        self.settings = settings
        self._completion_fn = completion_fn
        self._embedding_fn = embedding_fn
        self._sleep = sleep_fn or time.sleep  # 9 章退避（测试可注入记录器）
        # 11.0 第 0 层总闸：任务级预算护栏（由 Pipeline 挂接/卸载）
        self.budget_guard: BudgetGuard | None = budget_guard
        # 11.0 可观测性：每步 token 累计
        self.total_tokens_used: int = 0
        # 第 5 章可审计：调用日志（模型、模式、用量）
        self.call_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------

    def _call_with_retry(
        self,
        fn: Callable[..., Any],
        kwargs: dict[str, Any],
        model: str,
        error_prefix: str,
    ) -> Any:
        """调用 LLM 接口（9 章韧性：瞬态错误指数退避重试）。

        - 瞬态错误（超时/429/连接/5xx/过载）重试至多 llm_max_retries 次，
          退避 sleep = retry_backoff_base * 2**attempt；
        - 非瞬态错误（参数/鉴权类）立即上抛（重试无意义，徒耗预算）；
        - 重试耗尽抛 RuntimeError（含尝试次数，可观测）。
        """
        max_retries = self.settings.llm_max_retries
        for attempt in range(max_retries + 1):
            try:
                return fn(**kwargs)
            except Exception as exc:
                if not _is_transient(exc):
                    raise RuntimeError(
                        f"{error_prefix}（{model}）: {exc}"
                    ) from exc
                if attempt >= max_retries:
                    raise RuntimeError(
                        f"{error_prefix}（{model}，已重试 {max_retries} 次）: {exc}"
                    ) from exc
                self._sleep(self.settings.retry_backoff_base * (2 ** attempt))
        raise AssertionError("unreachable")  # pragma: no cover

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
        # 11.0：超预算 → 立即中止该任务（每次调用前拦截）
        if self.budget_guard is not None:
            self.budget_guard.ensure_allowed()
        self._check_api_key(model)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": self.settings.max_response_tokens,  # 第 2 层护栏
            "timeout": self.settings.llm_timeout_seconds,     # 9 章：单次调用超时
        }
        use_json = json_mode and self.settings.strict_json_response
        if use_json:
            kwargs["response_format"] = {"type": "json_object"}

        completion = self._completion_fn or _default_completion_fn()

        try:
            response = self._call_with_retry(
                completion, kwargs, model, "LLM 调用失败"
            )
        except RuntimeError:
            if use_json:
                # 15.1：模型不支持 response_format 时降级为普通调用
                kwargs.pop("response_format", None)
                response = self._call_with_retry(
                    completion, kwargs, model, "LLM 调用失败"
                )
            else:
                raise

        result = self._build_response(
            model, response, json_mode=json_mode, messages=messages
        )

        # 11.2：截断（finish_reason=length）分块续写，不静默丢弃
        continuations = 0
        while (
            _get_finish_reason(response) == "length"
            and continuations < self.settings.max_output_continuations
        ):
            continuations += 1
            # 上下文接续：原对话 + 已生成部分（assistant）+ 继续指令
            kwargs["messages"] = (
                messages
                + [{"role": "assistant", "content": result.content}]
                + [{"role": "user", "content": "继续，从中断处接着输出剩余部分，不要重复已有内容。"}]
            )
            try:
                response = self._call_with_retry(
                    completion, kwargs, model, "LLM 续写调用失败"
                )
            except RuntimeError:
                raise
            continuation = self._build_response(
                model, response, json_mode=json_mode, messages=kwargs["messages"]
            )
            # 合并：内容拼接、用量累计
            result = LLMResponse(
                model=model,
                content=result.content + continuation.content,
                input_tokens=result.input_tokens + continuation.input_tokens,
                output_tokens=result.output_tokens + continuation.output_tokens,
                truncated=continuation.truncated,
            )
        if _get_finish_reason(response) == "length":
            result.truncated = True
        return result

    def embed(self, model: str, text: str) -> list[float]:
        """发起一次 embedding 调用（11.3 第二道，经 model_client 统一封装）。

        token 用量计入总预算闸门（11.0）与审计日志（第 5 章）。
        Raises:
            RuntimeError: 调用失败或响应结构非法。
        """
        # 11.0：embedding 调用同样受总预算闸门约束
        if self.budget_guard is not None:
            self.budget_guard.ensure_allowed()

        embedding = self._embedding_fn or _default_embedding_fn()
        response = self._call_with_retry(
            embedding,
            {
                "model": model,
                "input": [text],
                "timeout": self.settings.llm_timeout_seconds,
            },
            model,
            "embedding 调用失败",
        )

        vector, prompt_tokens = _get_embedding(response)
        # 11.0 累计与第 5 章审计日志（kind=embedding）
        self.total_tokens_used += prompt_tokens
        if self.budget_guard is not None:
            self.budget_guard.record(prompt_tokens)
        self.call_log.append(
            {
                "model": model,
                "kind": "embedding",
                "json_mode": False,
                "input_tokens": prompt_tokens,
                "output_tokens": 0,
                "content_chars": len(text),
                "system_hint": "",
            }
        )
        return vector

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
        if self.budget_guard is not None:
            self.budget_guard.record(result.total_tokens)
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


def _get_finish_reason(response: Any) -> str | None:
    """提取 finish_reason（11.2 截断判定；缺失视为正常结束）。"""
    choices = _index(response, "choices")
    if not choices:
        return None
    reason = _index(choices[0], "finish_reason")
    return str(reason) if reason else None


def _index(obj: Any, key: str) -> Any:
    """兼容 dict 访问与属性访问（litellm ModelResponse 两者皆可）。"""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
