"""11.3 embedding 第二道循环检测接线测试（TDD 先行）。

规格依据（v0.3.1）：
- 11.3：双层检测先廉后贵——Jaccard（0.9）首道未命中时，
  embedding 余弦相似度（0.85）第二道拦截语义重复；
- 6.1/9 章：embedding 经 model_client 统一封装（litellm），
  token 用量计入总预算闸门（11.0）与审计日志（第 5 章）；
- 11.0：省 token 模式（≥90%）跳过非必要 embedding 比对；
- 11.3：向量缓存与增量比对（历史论点不重复 embed）。
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.utils.similarity import LoopDetector


# ---------------------------------------------------------------------------
# ModelClient.embed（经 model_client 统一封装）
# ---------------------------------------------------------------------------


def _fake_embedding_fn(**kwargs):
    # 简单确定性向量：按文本字符均值生成（测试用，语义可控）
    text = kwargs["input"][0]
    vec = [float(len(text)), 1.0, float(text.count("权限"))]
    return {
        "data": [{"embedding": vec}],
        "usage": {"prompt_tokens": 8},
    }


class TestModelClientEmbed:
    def _client(self, **overrides):
        from app.utils.model_client import ModelClient

        return ModelClient(
            Settings(embedding_model="text-embedding-3-small", **overrides),
            completion_fn=_fake_embedding_fn,
            embedding_fn=_fake_embedding_fn,
        )

    def test_embed_returns_vector(self):
        vec = self._client().embed("text-embedding-3-small", "权限控制方案")
        assert isinstance(vec, list) and len(vec) == 3

    def test_embed_records_usage_and_log(self):
        # 11.0/第 5 章：embedding token 计入累计与审计日志
        client = self._client()
        client.embed("text-embedding-3-small", "权限控制方案")
        assert client.total_tokens_used == 8
        assert len(client.call_log) == 1
        entry = client.call_log[0]
        assert entry["model"] == "text-embedding-3-small"
        assert entry["kind"] == "embedding"

    def test_embed_respects_budget_guard(self):
        # 11.0：embedding 调用同样受总预算闸门约束
        from app.utils.budget import BudgetExceededError, BudgetGuard

        client = self._client()
        client.budget_guard = BudgetGuard(8)  # 每次 embed 8 token
        client.embed("text-embedding-3-small", "第一次调用成功（耗尽预算）")
        with pytest.raises(BudgetExceededError):
            client.embed("text-embedding-3-small", "第二次被总闸拦截")

    def test_embed_retries_then_raises(self):
        # 调用失败 → 明确报错（不静默返回空向量，便于观测）
        from app.utils.model_client import ModelClient

        def failing(**kwargs):
            raise RuntimeError("provider down")

        client = ModelClient(
            Settings(embedding_model="bad-model"),
            completion_fn=_fake_embedding_fn,
            embedding_fn=failing,
        )
        with pytest.raises(RuntimeError, match="embedding 调用失败"):
            client.embed("bad-model", "文本")


# ---------------------------------------------------------------------------
# ModelClientEmbedder 适配器（Embedder 协议 + 失败安全降级）
# ---------------------------------------------------------------------------


class TestEmbedderAdapter:
    def test_adapter_delegates_to_client(self):
        from app.utils.model_client import ModelClient, ModelClientEmbedder

        client = ModelClient(
            Settings(embedding_model="text-embedding-3-small"),
            completion_fn=_fake_embedding_fn,
            embedding_fn=_fake_embedding_fn,
        )
        adapter = ModelClientEmbedder(client, "text-embedding-3-small")
        assert adapter.embed("权限控制") == [4.0, 1.0, 1.0]

    def test_adapter_degrades_to_empty_on_failure(self):
        # 失败降级为空向量（余弦=0 → 不误判重复），讨论流程不中断
        from app.utils.model_client import ModelClient, ModelClientEmbedder

        def failing(**kwargs):
            raise RuntimeError("provider down")

        client = ModelClient(
            Settings(embedding_model="bad-model"),
            completion_fn=_fake_embedding_fn,
            embedding_fn=failing,
        )
        adapter = ModelClientEmbedder(client, "bad-model")
        assert adapter.embed("任意文本") == []


# ---------------------------------------------------------------------------
# LoopDetector：第二道语义拦截 / 节流跳过 / 向量缓存
# ---------------------------------------------------------------------------


class _VecEmbedder:
    """可控向量 embedder：关键词映射返回向量（子串匹配），统计调用次数。"""

    def __init__(self, mapping: dict[str, list[float]]):
        self.mapping = mapping
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        for key, vec in self.mapping.items():
            if key in text:
                return vec
        return [0.0, 0.0, 0.0]


class TestLoopDetectorSecondLayer:
    def _detector(self, embedder) -> LoopDetector:
        detector = LoopDetector(Settings(loop_repeat_limit=3))
        detector.set_embedder(embedder)
        return detector

    def test_semantic_repeat_caught_by_second_layer(self):
        # Jaccard 低（字面不同）但语义相同（同向量）→ 第二道拦截并计数
        embedder = _VecEmbedder({
            "权限模块应当细化到角色级别": [1.0, 0.0, 0.0],
            "鉴权体系需要按角色粒度展开": [1.0, 0.0, 0.0],
            "数据层建议引入缓存策略": [0.0, 1.0, 0.0],
        })
        detector = self._detector(embedder)
        v1 = detector.check("评审意见：权限模块应当细化到角色级别。")
        v2 = detector.check("另一轮：鉴权体系需要按角色粒度展开。")
        assert not v1.frozen and not v2.frozen
        assert v2.repeat_counts  # 第二道命中，计数 +1

    def test_semantic_repeat_freezes_at_limit(self):
        # 首次入库 count=0；第 3 次「重复」（第 4 次出现）→ 冻结副 LLM 发言权
        embedder = _VecEmbedder({
            "权限模块应当细化到角色级别": [1.0, 0.0, 0.0],
            "鉴权体系需要按角色粒度展开": [1.0, 0.0, 0.0],
            "授权设计建议以角色为单位": [1.0, 0.0, 0.0],
            "角色维度的访问设计是必要的": [1.0, 0.0, 0.0],
        })
        detector = self._detector(embedder)
        detector.check("评审意见：权限模块应当细化到角色级别。")
        detector.check("另一轮：鉴权体系需要按角色粒度展开。")
        detector.check("补充：授权设计建议以角色为单位。")
        verdict = detector.check("再补充：角色维度的访问设计是必要的。")
        assert verdict.frozen
        assert "重复" in verdict.frozen_reason

    def test_no_false_positive_for_distinct_arguments(self):
        # 语义不同（向量正交）→ 不计数
        embedder = _VecEmbedder({
            "权限模块应当细化到角色级别": [1.0, 0.0, 0.0],
            "数据层建议引入缓存策略": [0.0, 1.0, 0.0],
        })
        detector = self._detector(embedder)
        detector.check("评审意见：权限模块应当细化到角色级别。")
        verdict = detector.check("另一意见：数据层建议引入缓存策略。")
        assert not verdict.frozen
        assert not verdict.repeat_counts

    def test_vector_cache_no_re_embed_of_history(self):
        # 11.3：历史论点向量已缓存——仅新论点触发 embed（增量比对）
        embedder = _VecEmbedder({
            "权限模块应当细化到角色级别": [1.0, 0.0, 0.0],
        })
        detector = self._detector(embedder)
        detector.check("评审意见：权限模块应当细化到角色级别。")
        detector.check("评审意见：权限模块应当细化到角色级别。")  # Jaccard 命中，无需 embed
        # 首次入库 embed 1 次 + 第二次比对 Jaccard 首道拦截（不再 embed）
        assert len(embedder.calls) == 1

    def test_throttling_skips_second_layer(self):
        # 11.0：省 token 模式 → 跳过 embedding 比对（零 embed 调用）
        embedder = _VecEmbedder({
            "权限模块应当细化到角色级别": [1.0, 0.0, 0.0],
            "鉴权体系需要按角色粒度展开": [1.0, 0.0, 0.0],
        })
        detector = self._detector(embedder)
        detector.check("评审意见：权限模块应当细化到角色级别。")
        embedder.calls.clear()
        detector.throttling = True
        verdict = detector.check("另一轮：鉴权体系需要按角色粒度展开。")
        assert not verdict.frozen
        assert not verdict.repeat_counts
        assert embedder.calls == []  # 第二道完全跳过

    def test_throttling_off_resumes_second_layer(self):
        # 节流恢复后第二道重新生效
        embedder = _VecEmbedder({
            "权限模块应当细化到角色级别": [1.0, 0.0, 0.0],
            "鉴权体系需要按角色粒度展开": [1.0, 0.0, 0.0],
        })
        detector = self._detector(embedder)
        detector.check("评审意见：权限模块应当细化到角色级别。")
        detector.throttling = True
        detector.check("另一轮：鉴权体系需要按角色粒度展开。")
        detector.throttling = False
        verdict = detector.check("补充：鉴权体系需要按角色粒度展开。")
        assert verdict.repeat_counts


# ---------------------------------------------------------------------------
# DiscussionEngine：embedder 自动接线（llm 具备 embed 能力时）
# ---------------------------------------------------------------------------


def _review_payload(weakness: str) -> str:
    return json.dumps(
        {
            "scores": {"feasibility": 9, "security": 9, "maintainability": 9},
            "strengths": ["完善"],
            "weaknesses": [weakness],
            "risks": [],
        },
        ensure_ascii=False,
    )


class TestDiscussionEngineWiring:
    def test_llm_with_embed_wires_second_layer(self):
        # llm 有 embed 方法 → DiscussionEngine 自动注入 embedder（11.3 接线），
        # 讨论全程第二道生效（embed 被实际调用），讨论仍收敛出 spec
        from app.orchestrator import DiscussionEngine

        class EmbeddingLLM:
            """带 embed 的桩：评审 payload 脚本充足，耗尽时返回默认评审。"""

            def __init__(self, scripts):
                self.scripts = list(scripts)
                self.call_log: list[dict] = []
                self.embed_calls = 0

            def chat(self, model, messages, json_mode=False):
                from app.utils.model_client import LLMResponse

                self.call_log.append(
                    {"model": model, "input_tokens": 10, "output_tokens": 5}
                )
                content = (
                    self.scripts.pop(0) if self.scripts
                    else _review_payload("其他独立建议")
                )
                return LLMResponse(
                    model=model, content=content, input_tokens=10, output_tokens=5
                )

            def embed(self, model, text):
                self.embed_calls += 1
                return [1.0, 0.0, 0.0] if "角色" in text else [0.0, 1.0, 0.0]

        llm = EmbeddingLLM(
            ["初始方案"]
            + [_review_payload("权限模块应当细化到角色级别")] * 8
            + ["最终 spec"]
        )
        engine = DiscussionEngine(
            llm=llm,
            main_model="gpt-4o",
            dev_model="deepseek-chat",
            test_model="claude-3-5-sonnet",
            settings=Settings(),
        )
        assert engine._detector._embedder is not None  # 已接线
        outcome = engine.run_discussion("需求")
        assert llm.embed_calls > 0  # 第二道被实际使用
        assert outcome.spec_md  # 讨论仍正常收敛

    def test_llm_without_embed_keeps_first_layer_only(self):
        # llm 无 embed 方法 → 不注入，仅 Jaccard 首道（现状回归）
        from app.orchestrator import DiscussionEngine

        class PlainLLM:
            def __init__(self, scripts):
                self.scripts = list(scripts)
                self.call_log: list[dict] = []

            def chat(self, model, messages, json_mode=False):
                from app.utils.model_client import LLMResponse

                self.call_log.append(
                    {"model": model, "input_tokens": 10, "output_tokens": 5}
                )
                return LLMResponse(
                    model="m", content=self.scripts.pop(0),
                    input_tokens=10, output_tokens=5,
                )

        llm = PlainLLM(["初始方案", _review_payload("字面完全相同"),
                        _review_payload("字面完全相同"), "最终 spec"])
        engine = DiscussionEngine(
            llm=llm,
            main_model="gpt-4o",
            dev_model="deepseek-chat",
            test_model="claude-3-5-sonnet",
            settings=Settings(),
        )
        assert engine._detector._embedder is None

    def test_disable_embedding_check_config(self):
        # 开关关闭（enable_embedding_check=False）→ 有 embed 也不接线
        from app.orchestrator import DiscussionEngine

        class EmbeddingLLM:
            def chat(self, model, messages, json_mode=False):
                raise AssertionError("不应被调用")

            def embed(self, model, text):
                raise AssertionError("不应被调用")

        engine = DiscussionEngine(
            llm=EmbeddingLLM(),
            main_model="gpt-4o",
            dev_model="deepseek-chat",
            test_model="claude-3-5-sonnet",
            settings=Settings(enable_embedding_check=False),
        )
        assert engine._detector._embedder is None
