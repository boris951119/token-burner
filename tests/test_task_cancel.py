"""M12-1 任务取消与僵尸清理（TDD 先行）。

规格（v0.5.md M12-1，原 M8-6）：
- DELETE /api/tasks/{id}：pending 立即取消（job 不执行）；
  running 协作式取消（复用 BudgetGuard 检查点，下一检查点中止，线程释放）；
- 已终态 → 409；未知 task_id → 404；
- 服务重启后 sessions/ 遗留 pending/running → 僵尸标记 cancelled；
- 取消后 LLM 调用停止（线程释放的可观测代理指标）。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.server import create_app
from app.task_manager import TaskManager
from app.tools.file_manager import FileManager

from app.utils.budget import BudgetGuard  # noqa: F401 —— 实现引入后供桩使用


# ---------------------------------------------------------------------------
# TaskManager 层：pending 立即取消 / running 协作式取消
# ---------------------------------------------------------------------------

class TestCancelPending:
    def test_pending_cancel_skips_job(self, tmp_path):
        """排队任务取消：立即终态，worker 轮到它时跳过 job。"""
        tm = TaskManager(projects_root=tmp_path / "projects", max_workers=1)
        release = threading.Event()
        ran: list[str] = []

        def blocker_factory(task_id):
            def job():
                ran.append("blocker")
                release.wait(timeout=5)
            return job

        def second_factory(task_id):
            def job():
                ran.append("second")
            return job

        tid1 = tm.submit(kind="run", job_factory=blocker_factory, requirement="占位")
        tid2 = tm.submit(kind="run", job_factory=second_factory, requirement="排队任务")

        # 等 task1 进入 running（worker 被占住 → task2 必然 pending）
        deadline = time.time() + 5
        while time.time() < deadline:
            if (tm.get(tid1) or {}).get("status") == "running":
                break
            time.sleep(0.02)
        assert (tm.get(tid2) or {}).get("status") == "pending"

        action, state = tm.cancel(tid2)
        assert action == "immediate"
        assert state["status"] == "cancelled"

        release.set()
        deadline = time.time() + 5
        while time.time() < deadline:
            if (tm.get(tid2) or {}).get("status") == "cancelled":
                break
            time.sleep(0.02)
        # task2 从未执行（worker 轮到它时直接跳过）
        time.sleep(0.1)
        assert ran == ["blocker"]


class TestCancelRunning:
    def test_running_cancel_at_checkpoint(self, tmp_path):
        """运行中任务：下一 BudgetGuard 检查点抛 TaskCancelledError → cancelled。"""
        tm = TaskManager(projects_root=tmp_path / "projects", max_workers=2)

        def factory(task_id):
            def job():
                flag = tm.cancel_flag(task_id)
                guard = BudgetGuard(budget_tokens=100_000)
                guard.attach_cancel_check(flag.is_set)
                calls = 0
                while calls < 100:
                    guard.ensure_allowed()      # 取消检查点（每轮循环一次）
                    guard.record(10)
                    calls += 1
                    time.sleep(0.05)
                return {"kind": "done", "calls": calls}
            return job

        tid = tm.submit(kind="run", job_factory=factory, requirement="长任务")
        deadline = time.time() + 5
        while time.time() < deadline:
            if (tm.get(tid) or {}).get("status") == "running":
                break
            time.sleep(0.02)

        action, state = tm.cancel(tid)
        assert action == "cooperative"
        assert state["status"] == "running"   # 协作式：状态仍 running，等检查点

        deadline = time.time() + 5
        while time.time() < deadline:
            if (tm.get(tid) or {}).get("status") == "cancelled":
                break
            time.sleep(0.02)
        assert tm.get(tid)["status"] == "cancelled"
        assert tm.get(tid)["result"] is None

    def test_unknown_task_returns_none(self, tmp_path):
        tm = TaskManager(projects_root=tmp_path / "projects")
        assert tm.cancel("nonexistent") is None

    def test_terminal_task_reports_already_terminal(self, tmp_path):
        tm = TaskManager(projects_root=tmp_path / "projects", max_workers=1)
        tid = tm.submit(
            kind="run",
            job_factory=lambda t: (lambda: {"kind": "done"}),
            requirement="秒完成",
        )
        deadline = time.time() + 5
        while time.time() < deadline:
            if (tm.get(tid) or {}).get("status") == "succeeded":
                break
            time.sleep(0.02)
        action, state = tm.cancel(tid)
        assert action == "already_terminal"
        assert state["status"] == "succeeded"


# ---------------------------------------------------------------------------
# 僵尸清理：重启后磁盘遗留 pending/running → cancelled
# ---------------------------------------------------------------------------

class TestZombieSweep:
    @pytest.fixture
    def client(self, tmp_path):
        app = create_app(
            settings=Settings(),
            projects_root=tmp_path / "projects",
            llm_factory=_SlowLLMFactory(),
            executor=_SkippedExecutorFactory(),
        )
        return TestClient(app), tmp_path

    def _make_zombie(self, tmp_path: Path, task_id: str, status: str) -> None:
        fm = FileManager(projects_root=tmp_path / "projects")
        pid = fm.create_project("僵尸项目").project_id
        root = fm.get_project(pid).root
        (root / "sessions").mkdir(parents=True, exist_ok=True)
        (root / "sessions" / "task_state.json").write_text(json.dumps({
            "task_id": task_id, "kind": "run", "status": status,
            "project_id": pid, "project_dir": str(root),
            "tokens_used": 123, "stage": "模块开发",
        }, ensure_ascii=False), encoding="utf-8")

    def test_running_state_marked_cancelled_on_startup(self, tmp_path):
        # 僵尸文件先落盘（模拟上次服务崩溃遗留），create_app 启动时清扫
        self._make_zombie(tmp_path, "zombie-running", "running")
        app = create_app(
            settings=Settings(),
            projects_root=tmp_path / "projects",
            llm_factory=_SlowLLMFactory(),
            executor=_SkippedExecutorFactory(),
        )
        data = TestClient(app).get("/api/tasks/zombie-running").json()
        assert data["status"] == "cancelled"
        assert "重启" in data["error"] or "僵尸" in data["error"]

    def test_pending_state_marked_cancelled_on_startup(self, tmp_path):
        self._make_zombie(tmp_path, "zombie-pending", "pending")
        app = create_app(
            settings=Settings(),
            projects_root=tmp_path / "projects",
            llm_factory=_SlowLLMFactory(),
            executor=_SkippedExecutorFactory(),
        )
        data = TestClient(app).get("/api/tasks/zombie-pending").json()
        assert data["status"] == "cancelled"

    def test_terminal_state_untouched(self, client, tmp_path):
        fm = FileManager(projects_root=tmp_path / "projects")
        pid = fm.create_project("正常项目").project_id
        root = fm.get_project(pid).root
        (root / "sessions").mkdir(parents=True, exist_ok=True)
        (root / "sessions" / "task_state.json").write_text(json.dumps({
            "task_id": "done-1", "kind": "run", "status": "succeeded",
            "project_id": pid, "project_dir": str(root),
        }, ensure_ascii=False), encoding="utf-8")
        tc, _ = client
        data = tc.get("/api/tasks/done-1").json()
        assert data["status"] == "succeeded"


# ---------------------------------------------------------------------------
# API 层：DELETE /api/tasks/{id}
# ---------------------------------------------------------------------------

class _SlowScriptLLM:
    """慢速剧本桩：team_flow 剧本 + 每调用 0.15s（留出取消窗口）。"""

    def __init__(self):
        self.scripts = [
            json.dumps({"task_type": "编程", "difficulty_score": 7,
                        "reason": "多模块", "estimated_files": 7}, ensure_ascii=False),
            "初始方案", _pos_review(), _pos_review(), "最终 spec",
            json.dumps({"modules": [{"name": "user", "responsibility": "用户",
                                     "dependencies": [], "priority": 1}]}, ensure_ascii=False),
            json.dumps({"imports": [], "exports": ["core_fn"],
                        "public_api": ["core_fn"], "dependencies": []}, ensure_ascii=False),
            "def core_fn():\n    return 1\n", "def test_core_fn():\n    assert core_fn() == 1\n",
        ]
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
        time.sleep(0.15)
        entry = {"model": model, "kind": "chat", "input_tokens": 10,
                 "output_tokens": 5, "content_chars": len(content)}
        self.call_log.append(entry)
        if self.on_call is not None:
            self.on_call(entry)
        return LLMResponse(model=model, content=content,
                           input_tokens=10, output_tokens=5)


def _pos_review() -> str:
    return json.dumps({"scores": {"feasibility": 9, "security": 9, "maintainability": 9},
                       "strengths": [], "weaknesses": [], "risks": []}, ensure_ascii=False)


class _SlowLLMFactory:
    def __init__(self):
        self._last: _SlowScriptLLM | None = None

    def create(self):
        self._last = _SlowScriptLLM()
        return self._last


class _SkippedExecutorFactory:
    def __call__(self, *args, **kwargs):
        return self

    def run(self, code, tests, timeout, expected_output="", module=""):
        from app.execution.executor import ExecutionResult, ExecutionStatus
        return ExecutionResult(status=ExecutionStatus.SKIPPED)


def _wait_terminal(tc: TestClient, task_id: str, timeout_s: float = 15) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = tc.get(f"/api/tasks/{task_id}").json()
        if data["status"] in ("succeeded", "failed", "cancelled"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"任务 {task_id} 超时未到终态")


class TestCancelApi:
    @pytest.fixture
    def env(self, tmp_path):
        factory = _SlowLLMFactory()
        app = create_app(
            settings=Settings(),
            projects_root=tmp_path / "projects",
            llm_factory=factory,
            executor=_SkippedExecutorFactory(),
        )
        return TestClient(app), factory

    def test_delete_running_task_cooperative(self, env):
        tc, factory = env
        r = tc.post("/api/tasks", json={
            "kind": "run", "requirement": "开发一个用户管理系统，支持注册登录与数据持久化",
            "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"], "mode": "safe",
        })
        tid = r.json()["task_id"]
        # 等任务真正跑起来（tokens 事件已产生 → guard 已挂接）
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            data = tc.get(f"/api/tasks/{tid}").json()
            if data["status"] == "running" and data["tokens_used"] > 0:
                break
            time.sleep(0.05)
        assert data["tokens_used"] > 0

        resp = tc.delete(f"/api/tasks/{tid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "cooperative"
        assert body["status"] == "cancelling"

        final = _wait_terminal(tc, tid)
        assert final["status"] == "cancelled"

        # 线程释放：取消后 LLM 调用停止（观测窗口内不再增长）
        llm = factory._last
        assert llm is not None
        calls_at_cancel = llm.calls
        time.sleep(1.0)
        assert llm.calls <= calls_at_cancel + 1   # 至多多检查点前一次

    def test_delete_unknown_task_404(self, env):
        tc, _ = env
        resp = tc.delete("/api/tasks/nonexistent")
        assert resp.status_code == 404

    def test_delete_terminal_task_409(self, env):
        tc, _ = env
        r = tc.post("/api/tasks", json={
            "kind": "run", "requirement": "写一个判断回文字符串的 Python 函数",
            "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"], "mode": "safe",
        })
        tid = r.json()["task_id"]
        final = _wait_terminal(tc, tid)
        assert final["status"] == "succeeded"
        resp = tc.delete(f"/api/tasks/{tid}")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# 前端契约：client.html 取消按钮与 DELETE 端点引用
# ---------------------------------------------------------------------------

class TestClientCancelContract:
    _ROOT = Path(__file__).resolve().parent.parent

    def test_cancel_button_and_endpoint_exist(self):
        html = (self._ROOT / "client.html").read_text(encoding="utf-8")
        assert "cancelTask" in html
        assert "DELETE" in html and "/api/tasks/${taskId}" in html
