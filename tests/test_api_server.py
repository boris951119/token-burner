"""API server 测试（TDD 先行）。

契约与 client.html 中约定的接口一一对应：
  GET  /api/health                        → 探活
  POST /api/route      {requirement}      → 评估结果
  POST /api/run        {requirement, models?, mode?, spec_confirm?,
                        confirmed_as_coding?, route?} → 完整执行
  GET  /api/resumable                     → 可恢复项目列表
  POST /api/resume      {project_id}      → 续跑
  POST /api/project/{id}/feedback {message} → 单轮反馈
  GET  /api/project/{id}/dashboard        → 成本看板（磁盘）

设计约定：
- /api/route 与 /api/run 分离：route 结果可回传 run（route 字段），
  复用评估（问题 5 修复在服务端不回退）；
- 反馈闭环经 resume 通道（磁盘重建，进程重启不丢）；
- 任务级互斥锁：共享 LLM 客户端的 budget_guard 不并发竞争。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.server import create_app
from app.tools.file_manager import FileManager


def _resp(content: str):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


class ScriptedLLM:
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = 0
        self.call_log = []
        self.budget_guard = None

    def chat(self, model, messages, json_mode=False, **kw):
        from app.utils.model_client import LLMResponse
        if self.budget_guard is not None:
            self.budget_guard.ensure_allowed()
        self.calls += 1
        content = self.scripts.pop(0) if self.scripts else "ok"
        self.call_log.append({
            "model": model, "kind": "chat", "json_mode": json_mode,
            "input_tokens": 10, "output_tokens": 5,
            "content_chars": len(content),
            "system_hint": messages[0]["content"] if messages else "",
        })
        return LLMResponse(model=model, content=content,
                           input_tokens=10, output_tokens=5)


class SkippedExecutor:
    def run(self, code, tests, timeout, expected_output="", module=""):
        from app.execution.executor import ExecutionResult, ExecutionStatus
        return ExecutionResult(status=ExecutionStatus.SKIPPED)


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


TEAM_SCRIPTS = [
    _assessment(), "初始方案", _review(), _review(), "最终 spec",
    _split(), _iface(),
    "def core_fn():\n    return 1\n", "TEST_user",
]


@pytest.fixture
def client(tmp_path):
    llm = ScriptedLLM(TEAM_SCRIPTS * 10)   # 剧本充足（多请求复用）
    app = create_app(llm=llm, settings=Settings(),
                     projects_root=tmp_path / "projects",
                     executor=SkippedExecutor())
    return TestClient(app), llm, tmp_path


class TestHealth:
    def test_health(self, client):
        tc, _, _ = client
        r = tc.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True}


class TestRobustness:
    def test_llm_error_returns_503_not_crash(self, tmp_path):
        # LLM 异常（如密钥缺失）→ 503 JSON，进程存活（后续请求仍可服务）
        class BrokenLLM:
            def __init__(self):
                self.call_log = []
                self.budget_guard = None

            def chat(self, *a, **kw):
                raise RuntimeError("模型「gpt-4o」需要环境变量 OPENAI_API_KEY")

        app = create_app(llm=BrokenLLM(), settings=Settings(),
                         projects_root=tmp_path / "projects")
        tc = TestClient(app, raise_server_exceptions=False)
        r = tc.post("/api/route", json={"requirement": "x"})
        assert r.status_code == 503
        assert "OPENAI_API_KEY" in r.json()["detail"]
        # 进程存活：health 仍可服务
        assert tc.get("/api/health").json() == {"ok": True}


class TestRoute:
    def test_route_returns_assessment(self, client):
        tc, llm, _ = client
        r = tc.post("/api/route", json={"requirement": "双因素认证系统"})
        assert r.status_code == 200
        data = r.json()
        assert data["task_type"] == "编程"
        assert data["difficulty_score"] == 7
        assert data["route"] == "team_flow"
        assert data["estimated_files"] == 7

    def test_route_result_roundtrips_into_run(self, client):
        # route → run 传回：不重复评估（问题 5）
        tc, llm, _ = client
        calls_before = llm.calls
        route = tc.post("/api/route", json={"requirement": "系统"}).json()
        calls_after_route = llm.calls
        r = tc.post("/api/run", json={
            "requirement": "系统",
            "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
            "mode": "safe", "spec_confirm": "确认",
            "route": route,
        })
        assert r.status_code == 200
        # 评估只发生一次（route 阶段）；run 阶段直接进讨论
        assert llm.calls == calls_after_route + 8  # 无评估调用


class TestRun:
    def test_team_flow_run(self, client):
        tc, llm, _ = client
        r = tc.post("/api/run", json={
            "requirement": "单模块系统",
            "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
            "mode": "safe", "spec_confirm": "确认",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["kind"] == "team_flow"
        assert data["project_id"]
        assert "user" in data["deliverable_summary"]
        assert data["dashboard"]["total_tokens"] > 0

    def test_direct_answer_run(self, client):
        tc, llm, _ = client
        # 需要直答剧本：评估（基础）+ 回答
        llm.scripts.insert(0, '{"task_type": "基础", "difficulty_score": 1, "reason": "简单"}')
        llm.scripts.insert(1, "直答内容")
        r = tc.post("/api/run", json={"requirement": "你好"})
        assert r.status_code == 200
        data = r.json()
        assert data["kind"] == "direct_answer"
        assert data["answer"] == "直答内容"

    def test_invalid_model_count_rejected(self, client):
        tc, _, _ = client
        r = tc.post("/api/run", json={
            "requirement": "x", "models": ["gpt-4o"], "mode": "safe",
        })
        assert r.status_code == 400  # 三模型互异（服务端显式校验）


class TestFeedbackLoop:
    def test_feedback_completes_awaiting_module(self, client):
        # run（safe）→ 模块 AWAITING_FEEDBACK → 单轮反馈「成功」→ 完成
        tc, llm, _ = client
        run = tc.post("/api/run", json={
            "requirement": "单模块系统",
            "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
            "mode": "safe", "spec_confirm": "确认",
        }).json()
        pid = run["project_id"]
        calls_before = llm.calls

        fb = tc.post(f"/api/project/{pid}/feedback",
                     json={"message": "运行成功，无报错"})
        assert fb.status_code == 200
        data = fb.json()
        assert data["kind"] == "team_flow"
        assert llm.calls == calls_before  # 成功反馈零 LLM 调用
        assert "完成" in data["deliverable_summary"]

    def test_feedback_error_triggers_fix_round(self, client):
        # 报错反馈 → 修复一轮（消耗 1 次修复调用）
        tc, llm, _ = client
        run = tc.post("/api/run", json={
            "requirement": "单模块系统",
            "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
            "mode": "safe", "spec_confirm": "确认",
        }).json()
        pid = run["project_id"]
        calls_before = llm.calls
        # 精确设定修复产物（过静态门禁 → SKIPPED → 等待新反馈）
        llm.scripts[:] = ["def core_fn():\n    return 2\n"]
        fb = tc.post(f"/api/project/{pid}/feedback",
                     json={"message": "RuntimeError: boom"})
        assert fb.status_code == 200
        assert llm.calls == calls_before + 1  # 修复一轮
        data = fb.json()
        assert "待用户反馈" in data["deliverable_summary"] or "user" in data["deliverable_summary"]


class TestDashboard:
    def test_dashboard_from_disk(self, client):
        tc, llm, _ = client
        run = tc.post("/api/run", json={
            "requirement": "单模块系统",
            "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
            "mode": "safe", "spec_confirm": "确认",
        }).json()
        r = tc.get(f"/api/project/{run['project_id']}/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert data["budget_tokens"] == 200_000
        assert data["total_tokens"] > 0
        assert "by_model" in data and "by_stage" in data

    def test_dashboard_unknown_project_404(self, client):
        tc, _, _ = client
        assert tc.get("/api/project/no-such/dashboard").status_code == 404


class TestResumable:
    def test_resumable_empty_then_listed(self, client):
        tc, llm, tmp_path = client
        assert tc.get("/api/resumable").json() == []

        # 人为制造中断项目（state + interruption 落盘）
        fm = FileManager(projects_root=tmp_path / "projects")
        pid = fm.create_project("中断任务").project_id
        root = fm.get_project(pid).root
        (root / "sessions").mkdir(parents=True, exist_ok=True)
        (root / "sessions" / "pipeline_state.json").write_text(
            json.dumps({"order": ["user"], "plans": [
                {"name": "user", "responsibility": "r",
                 "dependencies": [], "priority": 1}],
                "interfaces": {}, "mode": "safe",
                "models": ["a", "b", "c"]}), encoding="utf-8")
        (root / "sessions" / "interruption.md").write_text("中断\n", encoding="utf-8")

        data = tc.get("/api/resumable").json()
        assert len(data) == 1
        # 目录名 = project_id + 时间戳（FileManager 惯例，前缀扫描可解析）
        assert data[0]["project_id"].startswith(pid)
        assert data[0]["interrupted"] is True

    def test_resume_endpoint(self, client):
        tc, llm, tmp_path = client
        fm = FileManager(projects_root=tmp_path / "projects")
        pid = fm.create_project("待恢复").project_id
        root = fm.get_project(pid).root
        (root / "sessions").mkdir(parents=True, exist_ok=True)
        (root / "sessions" / "pipeline_state.json").write_text(
            json.dumps({"order": ["user"], "plans": [
                {"name": "user", "responsibility": "r",
                 "dependencies": [], "priority": 1}],
                "interfaces": {}, "mode": "safe",
                "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"]}),
            encoding="utf-8")
        r = tc.post("/api/resume", json={"project_id": pid})
        assert r.status_code == 200
        assert r.json()["kind"] == "team_flow"

    def test_resume_unknown_project_404(self, client):
        tc, _, _ = client
        r = tc.post("/api/resume", json={"project_id": "nope"})
        assert r.status_code == 404


class TestProjects:
    """M5-2 历史项目列表（GET /api/projects，只读聚合）。"""

    def test_empty_projects_root(self, client):
        tc, _, _ = client
        assert tc.get("/api/projects").json() == []

    def test_lists_project_with_metadata(self, client):
        tc, _, tmp_path = client
        fm = FileManager(projects_root=tmp_path / "projects")
        pid = fm.create_project("通讯录管理工具").project_id
        root = fm.get_project(pid).root
        (root / "sessions").mkdir(parents=True, exist_ok=True)
        (root / "logs").mkdir(parents=True, exist_ok=True)
        (root / "sessions" / "task_state.json").write_text(json.dumps({
            "task_id": "t1", "requirement": "开发通讯录管理命令行工具",
        }, ensure_ascii=False), encoding="utf-8")
        (root / "sessions" / "pipeline_state.json").write_text(json.dumps({
            "order": ["user"], "mode": "auto",
        }), encoding="utf-8")
        (root / "logs" / "cost_report.json").write_text(json.dumps({
            "total_tokens": 46352,
        }), encoding="utf-8")

        data = tc.get("/api/projects").json()
        assert len(data) == 1
        item = data[0]
        assert item["project_id"].startswith(pid)
        assert item["requirement"] == "开发通讯录管理命令行工具"
        assert item["mode"] == "auto"
        assert item["tokens"] == 46352
        assert item["has_state"] is True
        assert item["interrupted"] is False
        assert item["updated"]  # mtime 时间串非空

    def test_corrupt_metadata_falls_back_gracefully(self, client):
        # 元数据损坏 → 字段回落默认，项目条目不消失
        tc, _, tmp_path = client
        fm = FileManager(projects_root=tmp_path / "projects")
        pid = fm.create_project("损坏元数据项目").project_id
        root = fm.get_project(pid).root
        (root / "sessions").mkdir(parents=True, exist_ok=True)
        (root / "sessions" / "task_state.json").write_text("{broken", encoding="utf-8")
        (root / "sessions" / "pipeline_state.json").write_text("{also", encoding="utf-8")

        data = tc.get("/api/projects").json()
        assert len(data) == 1
        item = data[0]
        assert item["project_id"].startswith(pid)
        assert item["requirement"] == ""      # 回落（空串，前端显示目录名）
        assert item["mode"] == "safe"         # 回落缺省
        assert item["tokens"] == 0
        assert item["has_state"] is True      # 文件存在即标记（内容损坏不影响）

    def test_interruption_flagged(self, client):
        tc, _, tmp_path = client
        fm = FileManager(projects_root=tmp_path / "projects")
        pid = fm.create_project("被中断的项目").project_id
        root = fm.get_project(pid).root
        (root / "sessions").mkdir(parents=True, exist_ok=True)
        (root / "sessions" / "interruption.md").write_text("中断\n", encoding="utf-8")

        data = tc.get("/api/projects").json()
        assert len(data) == 1
        assert data[0]["interrupted"] is True


class TestProjectsRootConfig:
    """M5-2 产出目录配置：config.projects_root 三端统一生效。"""

    def test_settings_projects_root_drives_file_manager(self, tmp_path):
        # config.json 的 projects_root → 产出落自定义目录（未显式注入时生效）
        custom = tmp_path / "custom-output"
        llm = ScriptedLLM(TEAM_SCRIPTS * 10)
        app = create_app(
            llm=llm, settings=Settings(projects_root=str(custom)),
            executor=SkippedExecutor(),      # projects_root 不注入 → 走 settings
        )
        assert app.state.file_manager.projects_root == custom
        tc = TestClient(app)
        run = tc.post("/api/run", json={
            "requirement": "单模块系统",
            "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
            "mode": "safe", "spec_confirm": "确认",
        }).json()
        assert run["project_dir"].startswith(str(custom))
        assert custom.is_dir()               # 产物真实落在自定义目录

    def test_explicit_injection_overrides_settings(self, tmp_path):
        # 三层优先：显式注入（测试）> config.projects_root > cwd/projects
        injected = tmp_path / "injected"
        explicit = tmp_path / "explicit"
        app = create_app(
            settings=Settings(projects_root=str(injected)),
            projects_root=explicit,
        )
        assert app.state.file_manager.projects_root == explicit

    def test_config_endpoint_exposes_projects_root(self, tmp_path):
        custom = tmp_path / "custom-output"
        llm = ScriptedLLM(TEAM_SCRIPTS * 10)
        app = create_app(
            llm=llm, settings=Settings(projects_root=str(custom)),
            executor=SkippedExecutor(),
        )
        data = TestClient(app).get("/api/config").json()
        assert data["projects_root"] == str(custom)
