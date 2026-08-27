"""similarity（讨论循环检测）单元测试（TDD 先行）。

依据：规格文档 v0.3.1 11.3 节：
- 设计原则：由程序负责判定，LLM 不自我判断；
- 检测粒度：按「关键论点」切分比对，而非整段发言；
  仅对「这一轮新出现的论点」做检测；
- 双层检测（先廉后贵）：
  1) 文本相似度首道拦截（零依赖）：分词 Jaccard 重合度 > 阈值 0.9 → 字面重复；
  2) embedding 语义拦截：余弦相似度 > similarity_threshold（默认 0.85）→ 语义重复
     （MVP 允许 A 案：仅文本层，接口预留 embedding 注入）；
- 判定与打断：同一论点重复 < N（默认 3）次仅记录计数；
  ≥ N 次冻结全部副 LLM 发言权（返回打断信号）；
- 缓存与增量：仅对新论点做比对，历史论点不重复计算。
"""

from __future__ import annotations

from app.utils.similarity import LoopDetector, jaccard


class TestJaccard:
    def test_identical_sets_score_one(self):
        assert jaccard("数据库 权限 模块", "模块 权限 数据库") == 1.0

    def test_disjoint_sets_score_zero(self):
        assert jaccard("数据库 权限", "网络 部署") == 0.0

    def test_partial_overlap(self):
        score = jaccard("数据库 权限 模块", "数据库 权限 接口")
        assert 0.0 < score < 1.0

    def test_chinese_tokenization(self):
        # 中文按字符 bigram 分词（零依赖方案）：共享前缀比例高
        score = jaccard("用户权限管理", "用户权限控制")
        assert score > 0.4

    def test_empty_text(self):
        assert jaccard("", "") == 0.0


def _make_splitter() -> LoopDetector:
    from app.config import Settings
    return LoopDetector(Settings())


class TestArgumentSplitting:
    def test_split_by_bullet_points(self):
        text = "方案要点：\n1. 权限控制不足\n2. 数据库选型存疑\n3. 接口设计合理"
        points = _make_splitter()._split_arguments(text)
        assert len(points) == 3

    def test_split_by_semicolons(self):
        text = "权限不足；数据库存疑；接口合理"
        points = _make_splitter()._split_arguments(text)
        assert len(points) == 3

    def test_split_by_sentences(self):
        text = "权限控制不足。数据库选型存疑。接口设计合理。"
        points = _make_splitter()._split_arguments(text)
        assert len(points) == 3

    def test_short_noise_filtered(self):
        # 过碎噪声（如「同意」「1.」）不参与检测
        text = "同意\n1. 权限控制不足需要细化到角色级\n好"
        points = _make_splitter()._split_arguments(text)
        assert len(points) == 1


class TestLoopDetection:
    def make_detector(self, **kwargs) -> LoopDetector:
        from app.config import Settings
        return LoopDetector(Settings(**kwargs))

    def test_first_occurrence_recorded_not_interrupt(self):
        det = self.make_detector()
        verdict = det.check("评审意见：权限控制需要细化")
        assert verdict.frozen is False
        assert verdict.repeat_counts == {}

    def test_repeat_below_limit_records_count(self):
        det = self.make_detector(loop_repeat_limit=3)
        arg = "权限控制需要细化到角色级别"
        det.check(f"1. {arg}")
        verdict = det.check(f"1. {arg}")
        assert verdict.frozen is False
        assert max(verdict.repeat_counts.values()) == 1  # 第二次出现 → 计数 1

    def test_repeat_reaching_limit_freezes(self):
        # 11.3：同一论点重复 ≥ N 次 → 冻结副 LLM 发言权
        det = self.make_detector(loop_repeat_limit=3)
        arg = "权限控制需要细化到角色级别"
        det.check(f"1. {arg}")   # 首次
        det.check(f"1. {arg}")   # 重复 1
        det.check(f"1. {arg}")   # 重复 2
        verdict = det.check(f"1. {arg}")  # 重复 3 → 达上限
        assert verdict.frozen is True
        assert verdict.frozen_reason

    def test_new_arguments_not_counted(self):
        # 增量检测：仅新论点进入比对，历史论点不重复计数
        det = self.make_detector(loop_repeat_limit=3)
        det.check("1. 权限控制需要细化到角色级别")
        verdict = det.check("1. 数据库应改用 PostgreSQL")
        assert verdict.frozen is False
        assert verdict.repeat_counts == {}

    def test_jaccard_threshold_identifies_repetition(self):
        # 首道拦截：高 Jaccard 重合（> 0.9）判为字面重复
        det = self.make_detector()
        det.check("1. 用户认证应当采用 JWT 令牌机制")
        verdict = det.check("1. 用户认证应当采用 JWT 令牌机制")
        assert max(verdict.repeat_counts.values(), default=0) == 1

    def test_semantically_different_not_repeated(self):
        det = self.make_detector()
        det.check("1. 用户认证应当采用 JWT 令牌机制")
        verdict = det.check("1. 建议引入消息队列削峰填谷")
        assert verdict.repeat_counts == {}

    def test_frozen_persists_after_trigger(self):
        # 冻结后状态保持（11.3：打断后不再自动解冻）
        det = self.make_detector(loop_repeat_limit=2)
        arg = "权限控制需要细化到角色级别"
        det.check(f"1. {arg}")   # 首次入库（count 0）
        det.check(f"1. {arg}")   # 重复 1（count 1）
        det.check(f"1. {arg}")   # 重复 2 → 达上限冻结
        assert det._frozen is True
        verdict = det.check("1. 全新论点")
        assert verdict.frozen is True  # 冻结状态下的发言仅确认冻结，不再计数

    def test_reset_clears_state(self):
        det = self.make_detector(loop_repeat_limit=2)
        arg = "权限控制需要细化到角色级别"
        det.check(f"1. {arg}")
        det.check(f"1. {arg}")
        det.reset()
        verdict = det.check(f"1. {arg}")
        assert verdict.frozen is False
        assert verdict.repeat_counts == {}


class TestEmbeddingLayer:
    """11.3 第二道 embedding 拦截：MVP A 案仅文本层，接口预留注入。"""

    def make_detector(self) -> LoopDetector:
        from app.config import Settings
        return LoopDetector(Settings())

    def test_injectable_embedder_counts_semantic_repeat(self):
        # 注入确定性伪 embedding：相同论点 → 相同向量 → 余弦 1.0
        class FakeEmbedder:
            def embed(self, text: str) -> list[float]:
                # 仅按字符集投影（确定性）
                vec = [0.0] * 8
                for ch in set(text):
                    vec[ord(ch) % 8] += 1.0
                return vec

        det = self.make_detector()
        det.set_embedder(FakeEmbedder())
        # 构造字面不同但向量相同的文本（字符集一致即可）
        det.check("1. abcd")
        verdict = det.check("1. dcba")  # 字面不同（Jaccard 低），字符集相同
        assert verdict.frozen is False
        # 但第二道应记录语义重复
        assert max(verdict.repeat_counts.values(), default=0) == 1

    def test_no_embedder_by_default(self):
        det = self.make_detector()
        assert det._embedder is None
