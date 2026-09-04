"""并发地基测试（M8-1 ModelClient 任务级隔离 / M8-2 项目级锁）。

M8 现状问题回归锚点：
- 旧架构：ModelClient 单例共享（budget_guard / call_log 挂实例）+
  全局 task_lock → 服务并发能力 = 1，多任务预算串数；
- 新架构：每任务经 ModelClientFactory 独立实例（预算/日志天然
  隔离）；/resume、/feedback 项目级锁串行，不同项目并行。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.orchestrator import Route, RoutingResult
from app.pipeline import Pipeline
from app.server import create_app
from app.tools.file_manager import FileManager
from app.utils.locks import ProjectLockManager
from app.utils.model_client import ModelClientFactory


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    # 团队流程用三模型（gpt-4o/deepseek/claude），密钥检查全部放行
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEY", "sk-test")


def _resp(content: str):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


# ---------------------------------------------------------------------------
# M8-1 ModelClientFactory
# ---------------------------------------------------------------------------

class TestModelClientFactory:
    def test_creates_independent_instances(self):
        factory = ModelClientFactory(Settings())
        a, b = factory.create(), factory.create()
        assert a is not b
        assert a.call_log is not b.call_log
        assert a.budget_guard is None and b.budget_guard is None

    def test_budget_and_log_isolated_between_instances(self):
        factory = ModelClientFactory(Settings(), completion_fn=lambda **kw: _resp("hi"))
        a, b = factory.create(), factory.create()
        a.chat("gpt-4o", [{"role": "user", "content": "x"}])
        assert len(a.call_log) == 1
        assert b.call_log == []
        assert a.total_tokens_used == 15 and b.total_tokens_used == 0

    def test_stub_passed_through_to_every_instance(self):
        calls: list[dict] = []

        def stub(**kw):
            calls.append(kw)
            return _resp("ok")

        factory = ModelClientFactory(Settings(), completion_fn=stub)
        factory.create().chat("gpt-4o", [{"role": "user", "content": "1"}])
        factory.create().chat("gpt-4o", [{"role": "user", "content": "2"}])
        assert len(calls) == 2


# ---------------------------------------------------------------------------
# M8-2 ProjectLockManager
# ---------------------------------------------------------------------------

class TestProjectLockManager:
    def test_same_project_serializes(self):
        mgr = ProjectLockManager()
        release = threading.Event()
        acquired_second = threading.Event()

        def holder():
            with mgr.acquire("p1"):
                release.wait(timeout=5)

        t = threading.Thread(target=holder)
        t.start()
        time.sleep(0.05)  # 等 holder 进入临界区
        assert mgr.is_locked("p1")

        def waiter():
            with mgr.acquire("p1"):
                acquired_second.set()

        t2 = threading.Thread(target=waiter)
        t2.start()
        time.sleep(0.1)
        assert not acquired_second.is_set(), "同一项目的第二个进入者未被阻塞"
        release.set()
        assert acquired_second.wait(timeout=5), "持锁释放后等待者未获准进入"
        t.join(timeout=5)
        t2.join(timeout=5)

    def test_different_projects_parallel(self):
        mgr = ProjectLockManager()
        gate = threading.Event()

        def holder():
            with mgr.acquire("p1"):
                gate.wait(timeout=5)

        t = threading.Thread(target=holder)
        t.start()
        time.sleep(0.05)
        # p1 被后台线程持有时，p2 能立即进入临界区（未阻塞即证明并行）
        with mgr.acquire("p2"):
            assert mgr.is_locked("p1")  # p1 确实仍被持有
        gate.set()
        t.join(timeout=5)

    def test_lock_released_on_exception(self):
        mgr = ProjectLockManager()
        with pytest.raises(RuntimeError):
            with mgr.acquire("p1"):
                raise RuntimeError("任务失败")
        assert not mgr.is_locked("p1")


# ---------------------------------------------------------------------------
# Pipeline × factory：每任务独立客户端（M8-1 行为面）
# ---------------------------------------------------------------------------

class TestPipelineFactory:
    def _pipeline(self, factory, projects_root: Path) -> Pipeline:
        return Pipeline(
            llm=None, llm_factory=factory, executor=None,
            settings=Settings(),
            file_manager=FileManager(projects_root=projects_root),
        )

    def _direct_route(self) -> RoutingResult:
        return RoutingResult(
            route=Route.DIRECT_OUTPUT, task_type="基础",
            difficulty_score=2, difficulty_level="简单", reason="r",
        )

    def test_factory_creates_per_task_client(self, tmp_path):
        factory = ModelClientFactory(Settings(), completion_fn=lambda **kw: _resp("答案"))
        pipeline = self._pipeline(factory, tmp_path / "projects")
        assert pipeline.llm is None  # 构造时不持有客户端
        result = pipeline.run("帮我写一句话", route=self._direct_route())
        assert result.kind == "direct_answer"
        assert pipeline.llm is not None  # run 开始时解析为任务级实例
        assert result.answer == "答案"

    def test_task_client_log_excludes_foreign_usage(self, tmp_path):
        # 工厂预创建的客户端先消耗 15 token → 任务的客户端实例独立，
        # 旁路用量既不进入任务的调用日志，也不与其串数
        factory = ModelClientFactory(Settings(), completion_fn=lambda **kw: _resp("答案"))
        bystander = factory.create()
        bystander.chat("gpt-4o", [{"role": "user", "content": "别的任务"}])

        pipeline = self._pipeline(factory, tmp_path / "projects")
        result = pipeline.run("帮我写一句话", route=self._direct_route())
        assert result.kind == "direct_answer"
        # 任务级客户端仅含本任务 1 次调用（15 token）
        assert len(pipeline.llm.call_log) == 1
        assert pipeline.llm.total_tokens_used == 15
        # 旁路客户端用量保持独立（未串数）
        assert bystander.total_tokens_used == 15

    def test_llm_or_factory_required(self, tmp_path):
        with pytest.raises(ValueError, match="llm_factory"):
            Pipeline(llm=None, executor=None, settings=Settings(),
                     file_manager=FileManager(projects_root=tmp_path))


# ---------------------------------------------------------------------------
# server 端到端：两任务并行（旧全局锁下 max_concurrent 恒为 1）
# ---------------------------------------------------------------------------

class TestServerConcurrency:
    def test_two_runs_execute_in_parallel(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # 无状态桩：按 system 提示词确定性响应（并发下脚本序列会互相错位）。
        # 难度 4 → 空白带 TEAM_FLOW、单模块直出（不触发拆分/接口调用），
        # 全流程 8 次调用：评估/初始方案/双评审/收敛/写码/写测试/
        # M14-7 逻辑审查（safe 缺省 + logic_review_enabled 缺省开）。
        stats = {"cur": 0, "max": 0}
        stats_lock = threading.Lock()
        requirements = ("帮我写一段自我介绍", "帮我把这句话翻译成英文")

        def completion(**kw):
            system = kw["messages"][0]["content"]
            with stats_lock:
                stats["cur"] += 1
                stats["max"] = max(stats["max"], stats["cur"])
            time.sleep(0.3)  # 拉宽并发窗口
            with stats_lock:
                stats["cur"] -= 1
            if "需求评估专家" in system:
                return _resp(json.dumps(
                    {"task_type": "编程", "difficulty_score": 4,
                     "difficulty_level": "中等", "estimated_files": 3,
                     "reason": "空白带"}, ensure_ascii=False))
            if "评审" in system:
                return _resp(json.dumps(
                    {"scores": {"feasibility": 9}, "strengths": [],
                     "weaknesses": [], "risks": []}, ensure_ascii=False))
            if "收敛" in system:
                return _resp("# SPEC\n单模块规格")
            if "初始" in system:
                return _resp("# 初始方案")
            if "代码审查员" in system:
                # M14-7：safe 模式逻辑审查（须在「测试副 LLM」前匹配，
                # 该提示词头部亦含此字样）
                return _resp(json.dumps(
                    {"verdict": "pass", "issues": [], "warnings": []},
                    ensure_ascii=False))
            if "开发副 LLM" in system:
                return _resp("def run():\n    return 1\n")
            if "测试副 LLM" in system:
                return _resp("def test_run():\n    assert True\n")
            raise AssertionError(f"未识别的调用环节: {system[:50]!r}")

        factory = ModelClientFactory(Settings(), completion_fn=completion)
        app = create_app(settings=Settings(), projects_root=tmp_path / "projects",
                         llm_factory=factory)
        results: list[dict] = []

        def submit(client: TestClient, requirement: str):
            r = client.post("/api/run", json={"requirement": requirement})
            assert r.status_code == 200, r.text
            results.append(r.json())

        c1, c2 = TestClient(app), TestClient(app)  # 每线程独立 portal
        t1 = threading.Thread(target=submit, args=(c1, requirements[0]))
        t2 = threading.Thread(target=submit, args=(c2, requirements[1]))
        t1.start(); t2.start(); t1.join(timeout=60); t2.join(timeout=60)

        assert len(results) == 2
        # 并行性证据：两请求至少有一次同时在 LLM 调用中
        # （旧全局 task_lock 下该值恒为 1）
        assert stats["max"] >= 2, f"请求未并行执行（max_concurrent={stats['max']}）"
        # 预算隔离证据：各自看板只含本任务 8 次调用（8 × 15 token，
        # 含 M14-7 逻辑审查）
        for r in results:
            assert r["kind"] == "team_flow"
            assert r["dashboard"]["total_tokens"] == 120
        # 项目目录互不相同
        dirs = {r["project_dir"] for r in results}
        assert len(dirs) == 2
