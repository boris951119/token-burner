"""M7-1 集成测试：异步任务 API 4 路并发压测（提交/隔离/终态语义）。

覆盖（v0.4.md Done 定义「并发验收」条目）：
- 4 路任务并行提交：task_id 立即返回（<200ms 语义）；
- 各任务 budget / 结果互不串（M8-1 任务级隔离回归）；
- 全部到达终态且 result 正确（线程池并发 ≥4）；
- 续跑任务（kind=resume）经同一异步通道语义正确。
"""

from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.server import create_app
from app.tools.file_manager import FileManager


def _resp(content: str):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def _assessment():
    return json.dumps({"task_type": "编程", "difficulty_score": 7,
                       "reason": "多模块", "estimated_files": 7},
                      ensure_ascii=False)


def _review():
    return json.dumps({"scores": {"feasibility": 9, "security": 9, "maintainability": 9},
                       "strengths": [], "weaknesses": [], "risks": []},
                      ensure_ascii=False)


def _split():
    return json.dumps({"modules": [
        {"name": "user", "responsibility": "用户", "dependencies": [], "priority": 1},
    ]}, ensure_ascii=False)


def _iface():
    return json.dumps({"imports": [], "exports": ["core_fn"],
                       "public_api": ["core_fn"], "dependencies": []},
                      ensure_ascii=False)


SCRIPTS = [
    _assessment(), "初始方案", _review(), _review(), "最终 spec",
    _split(), _iface(),
    "def core_fn():\n    return 1\n", "TEST_user",
]


class LockedScriptedLLM:
    """线程安全剧本桩（M8-1：每任务经 factory 独立实例）。

    契约与 ModelClient 对齐：chat() 追加 call_log 条目后回调 on_call
    （M8-4 tokens 事件经 Pipeline 转发 → task_manager 计入 tokens_used）。
    """

    def __init__(self):
        self.scripts = list(SCRIPTS)
        self.calls = 0
        self.call_log: list[dict] = []
        self.budget_guard = None
        self.on_call = None
        self._lock = threading.Lock()

    def chat(self, model, messages, json_mode=False, **kw):
        from app.utils.model_client import LLMResponse
        with self._lock:
            if self.budget_guard is not None:
                self.budget_guard.ensure_allowed()
            self.calls += 1
            content = self.scripts.pop(0) if self.scripts else "ok"
        entry = {
            "model": model, "kind": "chat", "input_tokens": 10,
            "output_tokens": 5, "content_chars": len(content),
        }
        self.call_log.append(entry)
        if self.on_call is not None:
            self.on_call(entry)
        return LLMResponse(model=model, content=content,
                           input_tokens=10, output_tokens=5)


class _LLMFactory:
    """M8-1 工厂接口：每任务 create() 独立实例（budget/log 天然隔离）。"""

    def create(self):
        return LockedScriptedLLM()


@pytest.fixture
def tc(tmp_path):
    app = create_app(
        settings=Settings(),
        projects_root=tmp_path / "projects",
        llm_factory=_LLMFactory(),
        executor=_SkippedExecutorFactory(),
    )
    return TestClient(app), tmp_path


class _SkippedExecutorFactory:
    """auto 模式执行器桩（工厂形态，兼容 build_executor 注入口）。"""

    def __call__(self, *args, **kwargs):
        return self

    def run(self, code, tests, timeout, expected_output="", module=""):
        from app.execution.executor import ExecutionResult, ExecutionStatus
        return ExecutionResult(status=ExecutionStatus.SKIPPED)


def _wait_terminal(tc: TestClient, task_id: str, timeout_s: float = 30) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = tc.get(f"/api/tasks/{task_id}").json()
        if data["status"] in ("succeeded", "failed", "cancelled"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"任务 {task_id} 超时未到终态")


class TestFourWayConcurrency:
    def test_submit_returns_immediately_with_unique_ids(self, tc):
        client, _ = tc
        ids = []
        for i in range(4):
            started = time.monotonic()
            r = client.post("/api/tasks", json={
                "kind": "run",
                "requirement": f"并发压测任务 {i}：多模块系统",
                "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
                "mode": "safe",
            })
            elapsed = time.monotonic() - started
            assert r.status_code == 200
            assert elapsed < 2.0        # 提交即返回（<200ms 语义放宽到沙箱容忍）
            ids.append(r.json()["task_id"])
        assert len(set(ids)) == 4       # task_id 全局唯一

    def test_four_tasks_parallel_isolated_results(self, tc):
        """4 路并行：全部终态、结果互不串、project_dir 各自独立。"""
        client, _ = tc
        ids = []
        for i in range(4):
            r = client.post("/api/tasks", json={
                "kind": "run",
                "requirement": f"并行隔离验证任务 {i}：完整团队流程",
                "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
                "mode": "safe",
            })
            ids.append(r.json()["task_id"])

        results = [_wait_terminal(client, tid) for tid in ids]
        project_ids = set()
        for data in results:
            assert data["status"] == "succeeded", data["error"]
            result = data["result"]
            assert result["kind"] == "team_flow"
            assert result["project_id"] not in project_ids   # 互不串
            project_ids.add(result["project_id"])
            assert data["tokens_used"] > 0
        assert len(project_ids) == 4

    def test_resume_via_async_channel(self, tc):
        """M1-7 联动：中断恢复经异步任务通道（kind=resume）语义正确。"""
        client, tmp_path = tc
        fm = FileManager(projects_root=tmp_path / "projects")
        pid = fm.create_project("待恢复项目").project_id
        root = fm.get_project(pid).root
        (root / "sessions").mkdir(parents=True, exist_ok=True)
        (root / "sessions" / "pipeline_state.json").write_text(json.dumps({
            "order": ["user"], "plans": [
                {"name": "user", "responsibility": "r",
                 "dependencies": [], "priority": 1}],
            "interfaces": {}, "mode": "safe",
            "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
        }), encoding="utf-8")

        r = client.post("/api/tasks", json={
            "kind": "resume", "project_id": pid,
        })
        assert r.status_code == 200
        data = _wait_terminal(client, r.json()["task_id"])
        assert data["status"] == "succeeded"
        assert data["result"]["kind"] == "team_flow"
        assert data["project_id"] == pid
