"""M4-2/4-3/4-4 缓存扩展测试。

设计锚点（v0.4.md M4、config M4-2 注释）：
- M4-2 论点库：跨任务复用论点文本与向量；**冻结计数不跨任务累计**——
  预载论点本任务首次复现视为首次入库（计数归零），冻结时机与不预载
  完全一致（回归锚点：N=3 时第 4 次复现才冻结）；
- M4-3 _shared 上下文缓存：同任务跨模块零重读盘；_shared 变更精确失效；
  公共层代码进提示词（此前根本不进——依赖模块看不到公共层）；
- M4-4 命中率统计：EmbeddingCache.lookup 返回节省量；看板 cache_stats
  命中率 + 节省 token；无 embedding 调用时各项为零（不展示）。
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.dashboard.cost_dashboard import CostDashboard
from app.tools.file_manager import FileManager
from app.utils.embedding_cache import EmbeddingCache
from app.utils.similarity import LoopDetector
from tests.test_dev_loop import FakeExecutor, ScriptedLLM, make_engine


# ---------------------------------------------------------------------------
# M4-2 论点库持久化
# ---------------------------------------------------------------------------

_ARG = "接口命名必须与规格文档保持一致，避免双向绑定失效"


def _msg(text: str) -> str:
    return f"1. {text}"  # 编号列表项 → 论点切分


class _CountingEmbedder:
    def __init__(self):
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        # 玩具向量 [len, 1.0]：任意两条余弦 ≈ 0.999（语义等价的确定性模拟）
        return [float(len(text)), 1.0]


class TestLoopLibrary:
    def test_persists_new_arguments(self, tmp_path):
        lib = tmp_path / "lib.json"
        det = LoopDetector(Settings(), library_path=str(lib))
        det.check(_msg(_ARG))
        data = json.loads(lib.read_text(encoding="utf-8"))
        assert len(data["arguments"]) == 1
        assert data["arguments"][0]["text"] == _ARG

    def test_freeze_parity_with_seeded_library(self, tmp_path):
        """回归锚点：预载论点复现时冻结时机与不预载完全一致（第 4 次冻结）。"""
        lib = tmp_path / "lib.json"
        LoopDetector(Settings(), library_path=str(lib)).check(_msg(_ARG))

        det = LoopDetector(Settings(), library_path=str(lib))
        verdicts = [det.check(_msg(_ARG)) for _ in range(4)]
        assert [v.frozen for v in verdicts] == [False, False, False, True]
        # 首次复现 = 等价首次入库：不计入重复（冻结计数不跨任务）
        assert verdicts[0].repeat_counts == {}
        assert verdicts[1].repeat_counts != {}

    def test_seeded_vec_reused_for_semantic_match(self, tmp_path):
        """第二道加速：历史论点向量来自库文件，本任务零历史 embed。

        构造字面不重叠（Jaccard 首道必未命中）但玩具向量近似
        （余弦 ≈ 0.999 > 阈值 0.99）的两段文本 → 只能靠缓存向量命中。
        """
        lib = tmp_path / "lib.json"
        s = Settings(similarity_threshold=0.99)
        first = LoopDetector(s, library_path=str(lib))
        emb1 = _CountingEmbedder()
        first.set_embedder(emb1)
        first.check(_msg("甲乙丙丁戊己庚辛壬癸子丑寅卯"))

        second = LoopDetector(s, library_path=str(lib))
        emb2 = _CountingEmbedder()
        second.set_embedder(emb2)
        verdict = second.check(_msg("abcd_efgh_ijkl_mnop_qrst"))
        assert emb2.calls == 1  # 仅当前文本 1 次；历史向量直接命中（不重复 embed）
        assert not verdict.frozen
        assert verdict.repeat_counts == {}  # 预载吸收，不计重复

    def test_reset_keeps_library_file(self, tmp_path):
        lib = tmp_path / "lib.json"
        det = LoopDetector(Settings(), library_path=str(lib))
        det.check(_msg(_ARG))
        det.reset()
        assert lib.is_file()
        assert det._history == {}

    def test_corrupted_library_ignored(self, tmp_path):
        lib = tmp_path / "lib.json"
        lib.write_text("{broken", encoding="utf-8")
        det = LoopDetector(Settings(), library_path=str(lib))  # 不抛异常
        assert det.check(_msg(_ARG)).frozen is False

    def test_max_entries_cap(self, tmp_path):
        lib = tmp_path / "lib.json"
        det = LoopDetector(
            Settings(loop_library_max_entries=2), library_path=str(lib)
        )
        for i in range(3):
            det.check(_msg(f"论点甲乙丙丁{i}号需要认真对待"))
        data = json.loads(lib.read_text(encoding="utf-8"))
        assert len(data["arguments"]) == 2  # 保留最新

    def test_disabled_by_default(self):
        det = LoopDetector(Settings())  # library_path=None：不读不写任何库
        assert det.check(_msg(_ARG)).frozen is False
        assert all(not rec.get("seeded") for rec in det._history.values())


# ---------------------------------------------------------------------------
# M4-3 _shared 上下文缓存
# ---------------------------------------------------------------------------

class _PromptCapturingLLM(ScriptedLLM):
    """在桩上追加 user 提示词捕获（断言公共层段是否进入上下文）。"""

    def __init__(self, scripts):
        super().__init__(scripts)
        self.user_prompts: list[str] = []

    def chat(self, model, messages, json_mode=False):
        self.user_prompts.append(messages[-1]["content"])
        return super().chat(model, messages, json_mode)


class _CountingFM(FileManager):
    """读盘计数代理（list_files/read_file 计次，其余透传）。"""

    def __init__(self, projects_root):
        super().__init__(projects_root=projects_root)
        self.list_calls = 0
        self.read_calls = 0

    def list_files(self, project_id, subdir):
        self.list_calls += 1
        return super().list_files(project_id, subdir)

    def read_file(self, project_id, relative_path):
        self.read_calls += 1
        return super().read_file(project_id, relative_path)


class TestSharedContextCache:
    def _setup(self, fm, shared_code=""):
        pid = fm.create_project("demo").project_id
        if shared_code:
            fm.write_shared_file(pid, "utils.py", shared_code)
        # write_shared_file 内部会读旧内容做去重（多态命中计数代理）
        # → setup 后清零，只统计被测流程的读盘
        fm.list_calls = 0
        fm.read_calls = 0
        return pid

    def test_context_cached_across_modules(self, tmp_path):
        fm = _CountingFM(tmp_path / "p")
        pid = self._setup(fm, "def helper():\n    return 1\n")
        llm = _PromptCapturingLLM(["CODE_A", "CODE_B"])
        engine = make_engine(llm, FakeExecutor(["SUCCESS", "SUCCESS"]), fm)
        engine._active_project_id = pid
        engine._write_code("m1", "r")
        engine._write_code("m2", "r")
        assert fm.list_calls == 1  # 第二个模块零重读盘（缓存命中）
        # __init__.py（write_shared_file 自动创建）+ utils.py → 各读一次
        assert fm.read_calls == 2

    def test_prompt_includes_shared_code(self, tmp_path):
        fm = _CountingFM(tmp_path / "p")
        pid = self._setup(fm, "def helper():\n    return 1\n")
        llm = _PromptCapturingLLM(["CODE_A"])
        engine = make_engine(llm, FakeExecutor(["SUCCESS"]), fm)
        engine._active_project_id = pid
        engine._write_code("m1", "r")
        prompt = llm.user_prompts[-1]
        assert "已有公共层代码" in prompt  # 此前公共层根本不进提示词（缺口修复）
        assert "def helper" in prompt

    def test_empty_shared_no_section(self, tmp_path):
        fm = _CountingFM(tmp_path / "p")
        pid = self._setup(fm)
        llm = _PromptCapturingLLM(["CODE_A"])
        engine = make_engine(llm, FakeExecutor(["SUCCESS"]), fm)
        engine._active_project_id = pid
        engine._write_code("m1", "r")
        assert "已有公共层代码" not in llm.user_prompts[-1]

    def test_shared_write_invalidates_cache(self, tmp_path):
        fm = _CountingFM(tmp_path / "p")
        pid = self._setup(fm, "def old():\n    return 0\n")
        # LLM 输出带 _shared 标记块 → _split_shared 落盘新公共块 → 缓存失效
        llm = _PromptCapturingLLM([
            "CODE_A\n# ==== shared: new_util.py ====\ndef new_util():\n    return 2\n"
            "# ==== end shared ====",
            "CODE_B",
        ])
        engine = make_engine(llm, FakeExecutor(["SUCCESS", "SUCCESS"]), fm)
        engine._active_project_id = pid
        engine._write_code("m1", "r")
        engine._write_code("m2", "r")
        assert fm.list_calls == 2  # 失效后第二模块重新读盘
        prompt2 = llm.user_prompts[-1]
        assert "def new_util" in prompt2  # 看到最新公共层
        assert "def old" in prompt2


# ---------------------------------------------------------------------------
# M4-4 命中率统计
# ---------------------------------------------------------------------------

class TestEmbeddingCacheSavedTokens:
    def test_lookup_returns_saved_tokens(self, tmp_path):
        cache = EmbeddingCache(tmp_path / "c.db", ttl_days=7)
        cache.put("model-a", "hello", [0.1, 0.2], tokens=42)
        vec, saved = cache.lookup("model-a", "hello")
        assert vec == [0.1, 0.2]
        assert saved == 42
        assert cache.saved_tokens == 42

    def test_miss_returns_zero_saved(self, tmp_path):
        cache = EmbeddingCache(tmp_path / "c.db", ttl_days=7)
        vec, saved = cache.lookup("model-a", "ghost")
        assert vec is None
        assert saved == 0

    def test_get_legacy_semantics_unchanged(self, tmp_path):
        cache = EmbeddingCache(tmp_path / "c.db", ttl_days=7)
        cache.put("model-a", "hello", [0.1], tokens=42)
        assert cache.get("model-a", "hello") == [0.1]  # 旧接口回归
        assert cache.get("model-b", "hello") is None

    def test_old_db_without_tokens_column(self, tmp_path):
        """旧库迁移：无 tokens 列 → ALTER 自动补齐，可正常查询。"""
        import sqlite3

        path = tmp_path / "old.db"
        conn = sqlite3.connect(str(path))
        conn.execute(
            "CREATE TABLE embeddings (key TEXT PRIMARY KEY, vector TEXT NOT NULL,"
            " dim INTEGER NOT NULL, created_at REAL NOT NULL)"
        )
        conn.execute("INSERT INTO embeddings VALUES (?, ?, ?, ?)", ("k", "[0.5]", 1, 0.0))
        conn.commit()
        conn.close()
        cache = EmbeddingCache(path, ttl_days=7)  # 迁移不抛异常
        assert cache.get("model-a", "hello") is None  # 键不匹配，仅验证可查询


class TestDashboardCacheStats:
    def _log(self):
        return [
            {  # chat 调用（非 embedding，不参与命中率）
                "model": "m", "input_tokens": 10, "output_tokens": 5,
                "system_hint": "需求评估专家",
            },
            {  # embedding 未命中
                "model": "e", "kind": "embedding", "input_tokens": 0,
                "output_tokens": 0, "system_hint": "",
            },
            {  # embedding 命中（节省 42）
                "model": "e", "kind": "embedding", "input_tokens": 0,
                "output_tokens": 0, "system_hint": "",
                "cache_hit": True, "saved_tokens": 42,
            },
        ]

    def test_cache_stats(self):
        dashboard = CostDashboard.from_call_log(self._log(), budget_tokens=1000)
        stats = dashboard.cache_stats()
        assert stats["embedding_calls"] == 2
        assert stats["cache_hits"] == 1
        assert stats["hit_rate"] == pytest.approx(0.5)
        assert stats["saved_tokens"] == 42

    def test_no_embedding_calls_zero_not_misleading(self):
        dashboard = CostDashboard.from_call_log([], budget_tokens=1000)
        assert dashboard.cache_stats() == {
            "embedding_calls": 0, "cache_hits": 0,
            "hit_rate": 0.0, "saved_tokens": 0,
        }
        assert "缓存" not in dashboard.text_summary()  # 无 embedding 调用不展示

    def test_text_summary_and_persist_include_cache(self, tmp_path):
        dashboard = CostDashboard.from_call_log(self._log(), budget_tokens=1000)
        assert "命中率 50%" in dashboard.text_summary()
        assert "节省 42 token" in dashboard.text_summary()
        path = dashboard.persist(tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["cache"]["saved_tokens"] == 42
        assert payload["cache"]["hit_rate"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# M6-1 节省量统计与展示（已节省 Token / 节省比例 / 缓存命中率）
# ---------------------------------------------------------------------------

class TestSavingsSummary:
    def _dashboard(self):
        return CostDashboard.from_call_log(self._log(), budget_tokens=1000)

    def _log(self):
        return [
            {  # chat 实际消耗 15
                "model": "m", "input_tokens": 10, "output_tokens": 5,
                "system_hint": "需求评估专家",
            },
            {  # embedding 命中（节省 42）
                "model": "e", "kind": "embedding", "input_tokens": 0,
                "output_tokens": 0, "system_hint": "",
                "cache_hit": True, "saved_tokens": 42,
            },
        ]

    def test_three_metrics(self):
        savings = self._dashboard().savings_summary()
        assert savings["saved_tokens"] == 42
        # 节省比例 = saved / (saved + 实际消耗) = 42 / 57
        assert savings["saved_ratio"] == pytest.approx(42 / 57)
        assert savings["cache_hit_rate"] == pytest.approx(1.0)

    def test_zero_when_no_savings(self):
        dashboard = CostDashboard.from_call_log([], budget_tokens=1000)
        assert dashboard.savings_summary() == {
            "saved_tokens": 0, "saved_ratio": 0.0,
            "cache_hit_rate": 0.0, "embedding_calls": 0, "cache_hits": 0,
        }

    def test_text_summary_savings_line(self):
        text = self._dashboard().text_summary()
        assert "节省量: 已节省 42 token" in text
        assert "节省比例 74%" in text
        assert "缓存命中率 100%" in text

    def test_persist_includes_savings(self, tmp_path):
        path = self._dashboard().persist(tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["savings"]["saved_tokens"] == 42
        assert payload["savings"]["saved_ratio"] == pytest.approx(42 / 57)

    def test_server_dashboard_dict_includes_savings(self):
        from app.server import _dashboard_dict

        payload = _dashboard_dict(self._dashboard())
        assert payload["savings"]["saved_tokens"] == 42
        assert payload["savings"]["cache_hit_rate"] == pytest.approx(1.0)

    def test_client_html_savings_contract(self):
        """client.html 单文件契约：节省量行存在且有条件渲染。"""
        from pathlib import Path

        html = Path(__file__).resolve().parent.parent.joinpath("client.html").read_text(
            encoding="utf-8"
        )
        assert 'id="c-savings"' in html
        assert 'id="c-saved"' in html
        assert "data.dashboard.savings" in html
