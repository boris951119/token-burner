"""异步任务 API 测试（M8-3 提交+轮询 / M8-4 SSE 进度事件流）。

验收口径（v0.4.md M8-3/M8-4）：
- POST /api/tasks 立即返回 task_id（任务在后台线程池执行，并发 ≥4）；
- GET /api/tasks/{id} 可查询状态/当前阶段/已耗 token；
- TaskState 落盘项目 sessions/task_state.json——服务重启后可查询；
- GET /api/tasks/{id}/events 首帧全量快照 + 实时事件 + done 终帧；
- 旧同步 API（/run、/resume、/feedback）行为不变。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.orchestrator import Route, RoutingResult
from app.server import create_app
from app.task_manager import TaskManager, TaskStatus
from app.utils.model_client import ModelClientFactory


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEY", "sk-test")


def _resp(content: str):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def _make_completion(sleep: float = 0.0, stats: dict | None = None):
    """按 system 提示词确定性分流的无状态桩（并发安全）。"""
    lock = threading.Lock()

    def completion(**kw):
        system = kw["messages"][0]["content"]
        if stats is not None:
            with lock:
                stats["cur"] = stats.get("cur", 0) + 1
                stats["max"] = max(stats.get("max", 0), stats["cur"])
        if sleep:
            time.sleep(sleep)
        if stats is not None:
            with lock:
                stats["cur"] -= 1
        if "需求评估专家" in system:
            return _resp(json.dumps(
                {"task_type": "编程", "difficulty_score": 4,
                 "difficulty_level": "中等", "estimated_files": 3,
                 "reason": "空白带"}, ensure_ascii=False))
        if "你是助理" in system:  # 直答（DIRECT_OUTPUT 回答调用）
            return _resp("好的，这是结果。")
        if "评审" in system:
            return _resp(json.dumps(
                {"scores": {"feasibility": 9}, "strengths": [],
                 "weaknesses": [], "risks": []}, ensure_ascii=False))
        if "收敛" in system:
            return _resp("# SPEC\n单模块规格")
        if "初始" in system:
            return _resp("# 初始方案")
        if "开发副 LLM" in system:
            return _resp("def run():\n    return 1\n")
        if "测试副 LLM" in system:
            return _resp("def test_run():\n    assert True\n")
        raise AssertionError(f"未识别的调用环节: {system[:50]!r}")

    return completion


def _make_app(tmp_path, sleep: float = 0.0, stats: dict | None = None, executor=None):
    factory = ModelClientFactory(Settings(), completion_fn=_make_completion(sleep, stats))
    return create_app(settings=Settings(), projects_root=tmp_path / "projects",
                      llm_factory=factory, executor=executor)


class _SkippedExecutor:
    """auto 模式测试桩：不真实执行（与 SafeExecutor 语义一致）。"""

    def run(self, code, tests, timeout, expected_output="", module=""):
        from app.execution.executor import ExecutionResult, ExecutionStatus
        return ExecutionResult(status=ExecutionStatus.SKIPPED)


def _direct_route_payload() -> dict:
    route = RoutingResult(
        route=Route.DIRECT_OUTPUT, task_type="基础",
        difficulty_score=2, difficulty_level="简单", reason="测试直答",
    )
    data = asdict(route)
    data["route"] = route.route.value
    return data


def _poll(client: TestClient, task_id: str, timeout: float = 30.0) -> dict:
    """轮询任务至终态（M8-3 提交+轮询契约）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/tasks/{task_id}").json()
        if data["status"] in [s.value for s in TaskStatus.terminal()]:
            return data
        time.sleep(0.05)
    raise AssertionError(f"任务 {timeout}s 内未达终态: {data}")


# ---------------------------------------------------------------------------
# TaskManager 单元
# ---------------------------------------------------------------------------

class TestTaskManagerUnit:
    def test_submit_completes_with_result(self, tmp_path):
        mgr = TaskManager(projects_root=tmp_path)
        task_id = mgr.submit("run", lambda tid: lambda: {"kind": "direct_answer"})
        assert len(task_id) == 12
        deadline = time.monotonic() + 5
        while mgr.get(task_id)["status"] != "succeeded":
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert mgr.get(task_id)["result"] == {"kind": "direct_answer"}

    def test_failure_captures_error_and_done_event(self, tmp_path):
        mgr = TaskManager(projects_root=tmp_path)
        q = mgr.subscribe  # noqa: F841 —— 实际订阅在 job_factory 拿到 id 之后

        def bad_job_factory(task_id: str):
            def job():
                raise ValueError("boom")
            return job

        task_id = mgr.submit("run", bad_job_factory)
        data = _poll_task_manager(mgr, task_id)
        assert data["status"] == "failed"
        assert "boom" in data["error"]

    def test_events_update_state_broadcast_and_persist(self, tmp_path):
        mgr = TaskManager(projects_root=tmp_path)
        # submit 的 job_factory 在 submit 时同步调用，其返回的 callable 才是
        # 线程池执行的 job。原写法 factory 直接返回 dict → worker 内 job()
        # TypeError → done(FAILED) 帧与主线程事件竞速插队（高负载必现）。
        # 正确语义：job 阻塞到主线程发完 4 个事件再结束，done 必然最后。
        release = threading.Event()

        def _factory(tid):
            def _job():
                release.wait(timeout=10)
                return {"kind": "team_flow"}
            return _job

        task_id = mgr.submit("run", _factory)
        q = mgr.subscribe(task_id)
        try:
            mgr.on_pipeline_event(task_id, "tokens", {"tokens": 15})
            mgr.on_pipeline_event(task_id, "stage", {"stage": "模块开发"})
            mgr.on_pipeline_event(task_id, "project", {
                "project_id": "p1", "project_dir": str(tmp_path / "p1"),
            })
            mgr.on_pipeline_event(task_id, "module_done", {"module": "m", "status": "SUCCESS"})
            # 状态更新
            data = mgr.get(task_id)
            assert data["tokens_used"] == 15
            assert data["stage"] == "模块开发"
            assert data["project_id"] == "p1"
            # 广播（顺序帧）
            kinds = [q.get(timeout=2)["type"] for _ in range(4)]
            assert kinds == ["tokens", "stage", "project", "module_done"]
            # 落盘（项目就绪后）
            persisted = json.loads(
                (tmp_path / "p1" / "sessions" / "task_state.json")
                .read_text(encoding="utf-8")
            )
            assert persisted["task_id"] == task_id
            assert persisted["tokens_used"] == 15
        finally:
            release.set()
            mgr.unsubscribe(task_id, q)

    def test_get_loads_from_disk_after_restart(self, tmp_path):
        # 第一个管理器写入落盘态 → 新管理器（模拟重启）从磁盘恢复查询
        mgr = TaskManager(projects_root=tmp_path)
        task_id = mgr.submit("run", lambda tid: lambda: {"ok": True})
        _poll_task_manager(mgr, task_id)
        mgr.on_pipeline_event(task_id, "project", {
            "project_id": "p1", "project_dir": str(tmp_path / "p1"),
        })
        restarted = TaskManager(projects_root=tmp_path)
        data = restarted.get(task_id)
        assert data is not None
        assert data["status"] == "succeeded"

    def test_get_unknown_returns_none(self, tmp_path):
        assert TaskManager(projects_root=tmp_path).get("nope") is None


def _poll_task_manager(mgr: TaskManager, task_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = mgr.get(task_id)
        if data["status"] in [s.value for s in TaskStatus.terminal()]:
            return data
        time.sleep(0.02)
    raise AssertionError("任务未达终态")


# ---------------------------------------------------------------------------
# M8-3 提交 + 轮询端到端
# ---------------------------------------------------------------------------

class TestAsyncTaskAPI:
    def test_submit_run_direct_answer_polls_to_success(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        r = client.post("/api/tasks", json={
            "kind": "run", "requirement": "帮我写一句话",
            "route": _direct_route_payload(),
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "pending"
        data = _poll(client, body["task_id"])
        assert data["status"] == "succeeded", f"任务失败: {data['error']}"
        assert data["result"]["kind"] == "direct_answer"
        assert data["result"]["answer"] == "好的，这是结果。"
        assert data["tokens_used"] == 15

    def test_submit_returns_before_task_completes(self, tmp_path):
        client = TestClient(_make_app(tmp_path, sleep=1.0))
        started = time.monotonic()
        r = client.post("/api/tasks", json={
            "kind": "run", "requirement": "慢任务",
            "route": _direct_route_payload(),
        })
        elapsed = time.monotonic() - started
        assert r.status_code == 200
        assert elapsed < 0.8, f"提交未立即返回（{elapsed:.2f}s）"
        _poll(client, r.json()["task_id"])  # 收尾（避免线程悬挂）

    def test_unknown_task_404(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        assert client.get("/api/tasks/does-not-exist").status_code == 404

    def test_invalid_kind_400(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        r = client.post("/api/tasks", json={"kind": "wat"})
        assert r.status_code == 400

    def test_feedback_task_via_async_channel(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        # 先同步跑一个 team_flow（safe 模式交付 → 模块 AWAITING_FEEDBACK）
        r = client.post("/api/run", json={"requirement": "写一个用户模块"})
        assert r.status_code == 200
        project_id = r.json()["project_id"]
        # 异步单轮反馈「成功」→ 模块确认完成
        r = client.post("/api/tasks", json={
            "kind": "feedback", "project_id": project_id, "message": "成功",
        })
        assert r.status_code == 200
        data = _poll(client, r.json()["task_id"])
        assert data["status"] == "succeeded"
        assert "完成" in data["result"]["deliverable_summary"]

    def test_thread_pool_concurrency_four(self, tmp_path):
        stats: dict = {}
        client = TestClient(_make_app(tmp_path, sleep=0.4, stats=stats))
        ids = []
        for _ in range(4):  # 并发度 4：4 个慢任务应同时在跑
            r = client.post("/api/tasks", json={
                "kind": "run", "requirement": "直答任务",
                "route": _direct_route_payload(),
            })
            ids.append(r.json()["task_id"])
        for task_id in ids:
            assert _poll(client, task_id)["status"] == "succeeded"
        assert stats["max"] == 4, f"并发度未达 4（max={stats['max']}）"

    # ------------------------------------------------------------------
    # M1-1/1-2 插件前置：启动配置端点 + auto 模式显式确认语义
    # ------------------------------------------------------------------

    def test_config_endpoint_serves_panel(self, tmp_path):
        # M1-2：面板经 /api/config 取预设模型与预算（警示文案数据源）
        client = TestClient(_make_app(tmp_path))
        r = client.get("/api/config")
        assert r.status_code == 200
        data = r.json()
        settings = Settings()
        assert data["models"] == settings.models
        assert data["budget_tokens"] == settings.task_token_budget("safe")
        assert data["auto_budget_tokens"] == settings.task_token_budget("auto")
        assert data["auto_budget_multiplier"] == settings.auto_mode_budget_multiplier

    def test_auto_mode_explicit_api_selection_confirmed(self, tmp_path):
        # 3.6.3 修复：API 请求显式选择 auto 即视为确认——
        # 此前 auto_mode_confirmed 从未传入，TeamBuilder 预算闸门必拒
        client = TestClient(_make_app(tmp_path, executor=_SkippedExecutor()))
        r = client.post("/api/tasks", json={
            "kind": "run", "requirement": "写一个用户模块", "mode": "auto",
        })
        assert r.status_code == 200
        data = _poll(client, r.json()["task_id"])
        assert data["status"] == "succeeded", f"任务失败: {data['error']}"
        assert data["result"]["kind"] == "team_flow"
        # auto 模式预算倍数生效（11.0：×auto_budget_multiplier）
        settings = Settings()
        assert data["result"]["dashboard"]["budget_tokens"] == \
            settings.task_token_budget("auto")


# ---------------------------------------------------------------------------
# 生成代码只读端点（M1-4：插件 diff 预览与应用）
# ---------------------------------------------------------------------------

class TestProjectFileEndpoints:
    def _completed_project(self, client: TestClient) -> str:
        r = client.post("/api/run", json={"requirement": "写一个用户模块"})
        assert r.status_code == 200
        return r.json()["project_id"]

    def test_files_list_and_single_content(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        project_id = self._completed_project(client)
        # 单模块直出路径：模块名固定 main
        files = client.get(f"/api/project/{project_id}/files").json()["files"]
        assert "code/main/main.py" in files
        assert "tests/main/test_main.py" in files
        content = client.get(
            f"/api/project/{project_id}/file",
            params={"path": "code/main/main.py"},
        ).json()
        assert "def run" in content["content"]

    def test_file_endpoint_rejects_non_code_paths(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        project_id = self._completed_project(client)
        # sessions/logs 等内部目录不暴露（M1-4 只开放生成物）
        r = client.get(
            f"/api/project/{project_id}/file",
            params={"path": "sessions/team_config.json"},
        )
        assert r.status_code == 400

    def test_file_missing_404(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        project_id = self._completed_project(client)
        r = client.get(
            f"/api/project/{project_id}/file",
            params={"path": "code/main/nope.py"},
        )
        assert r.status_code == 404

    def test_files_unknown_project_404(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        assert client.get("/api/project/nope/files").status_code == 404


# ---------------------------------------------------------------------------
# M8-4 SSE 事件流
# ---------------------------------------------------------------------------

class TestSSEEvents:
    def test_stream_snapshot_events_done(self, tmp_path):
        client = TestClient(_make_app(tmp_path, sleep=0.15))
        task_id = client.post("/api/tasks", json={
            "kind": "run", "requirement": "写一个用户模块",
        }).json()["task_id"]

        events: list[dict] = []
        with client.stream("GET", f"/api/tasks/{task_id}/events") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: "):]))
                    if events[-1].get("type") == "done":
                        break
        types = [e["type"] for e in events]
        assert types[0] == "snapshot"
        assert types[-1] == "done"
        assert "tokens" in types          # token 更新事件有推送
        assert "stage" in types           # 阶段切换事件有推送
        assert events[-1]["result"]["kind"] == "team_flow"

    def test_stream_after_completion_serves_snapshot_and_done(self, tmp_path):
        # 订阅晚于终态（竞态）：首帧快照 + done 帧后关流，不悬挂
        client = TestClient(_make_app(tmp_path, sleep=0.0))
        task_id = client.post("/api/tasks", json={
            "kind": "run", "requirement": "直答",
            "route": _direct_route_payload(),
        }).json()["task_id"]
        _poll(client, task_id)

        events: list[dict] = []
        with client.stream("GET", f"/api/tasks/{task_id}/events") as resp:
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: "):]))
                    if events[-1].get("type") == "done":
                        break
        assert [e["type"] for e in events] == ["snapshot", "done"]
