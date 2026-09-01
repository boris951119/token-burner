"""V3 批次测试：M12-2 镜像预热 / M12-3 Docker 检测引导 / M12-4 预算透传。

规格：
- M12-2（原 M2-6）：预热 python/node 镜像，已存在跳过 pull（缓存校验），
  报告每镜像与总耗时；POST /api/prewarm；
- M12-3（原 M2-7）：GET /api/docker/status 返回可用性与降级说明；
- M12-4（原 M1-8）：TaskSubmitRequest 可选 budget_tokens 透传管线
  （覆盖 team 缺省预算，用于插件设置页的预算配置项）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.execution.prewarm import prewarm_images
from app.server import create_app


# ---------------------------------------------------------------------------
# M12-2：镜像预热（注入假 runner，无 Docker 依赖）
# ---------------------------------------------------------------------------

class _FakeRunner:
    """按命令前缀返回预设结果（记录全部调用）。"""

    def __init__(self, inspect_missing: set[str] | None = None, pull_fail: set[str] | None = None):
        self.calls: list[list[str]] = []
        self.inspect_missing = inspect_missing or set()
        self.pull_fail = pull_fail or set()

    def __call__(self, cmd: list[str], timeout: int = 30):
        self.calls.append(list(cmd))
        if cmd[1] == "image" and cmd[2] == "inspect":
            image = cmd[3]
            ok = image not in self.inspect_missing
            return _Proc(0 if ok else 1, "", "" if ok else "not found")
        if cmd[1] == "pull":
            image = cmd[2]
            if image in self.pull_fail:
                return _Proc(1, "", "network unreachable")
            return _Proc(0, image, "")
        return _Proc(0, "", "")


class _Proc:
    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestPrewarm:
    def test_both_images_cached_skips_pull(self, tmp_path):
        runner = _FakeRunner()  # inspect 全部命中 → 不 pull
        settings = Settings()
        r = prewarm_images(settings, runner=runner)
        assert r["ok"] is True
        assert [i["cached"] for i in r["images"]] == [True, True]
        assert r["images"][0]["image"] == settings.docker_image
        assert r["images"][1]["image"] == settings.docker_node_image
        assert not any(c[1] == "pull" for c in runner.calls)   # 零 pull

    def test_missing_image_pulled(self, tmp_path):
        settings = Settings()
        runner = _FakeRunner(inspect_missing={settings.docker_node_image})
        r = prewarm_images(settings, runner=runner)
        assert r["ok"] is True
        node = [i for i in r["images"] if i["image"] == settings.docker_node_image][0]
        assert node["cached"] is False and node["ok"] is True
        pulls = [c for c in runner.calls if c[1] == "pull"]
        assert [c[2] for c in pulls] == [settings.docker_node_image]

    def test_pull_failure_reported(self, tmp_path):
        settings = Settings()
        runner = _FakeRunner(
            inspect_missing={settings.docker_image},
            pull_fail={settings.docker_image},
        )
        r = prewarm_images(settings, runner=runner)
        py = [i for i in r["images"] if i["image"] == settings.docker_image][0]
        assert py["ok"] is False and "network" in py["error"]
        assert r["ok"] is False
        assert r["total_ms"] >= sum(i["elapsed_ms"] for i in r["images"])

    def test_second_run_is_cache_hit_under_5s(self, tmp_path):
        """验收口径：预热后二次启动仅剩 inspect（缓存命中，毫秒级 <5s）。"""
        settings = Settings()
        runner = _FakeRunner()
        prewarm_images(settings, runner=runner)
        r2 = prewarm_images(settings, runner=runner)
        assert r2["ok"] is True
        assert r2["total_ms"] < 5000
        assert all(i["cached"] for i in r2["images"])


# ---------------------------------------------------------------------------
# M12-3 / M12-2 API：docker 状态 + prewarm 端点
# ---------------------------------------------------------------------------

class TestDockerAndPrewarmApi:
    def test_docker_status_endpoint(self, tmp_path, monkeypatch):
        """三态：配置关闭 / Docker 可用 / Docker 不可用（降级指引）。"""
        from app.execution import docker_executor as de

        # ① 配置关闭 → 进程模式，无 Docker 探测
        app = create_app(
            settings=Settings(docker_executor_enabled=False),
            projects_root=tmp_path / "projects",
            llm_factory=None,
            executor=None,
        )
        tc = TestClient(app)
        data = tc.get("/api/docker/status").json()
        assert data["available"] is False
        assert data["mode_effective"] == "process"

        # ② 配置开启 + Docker 可用 → 容器级隔离
        app2 = create_app(
            settings=Settings(docker_executor_enabled=True),
            projects_root=tmp_path / "projects",
            llm_factory=None,
            executor=None,
        )
        monkeypatch.setattr(de.DockerExecutor, "available", lambda: True)
        data2 = TestClient(app2).get("/api/docker/status").json()
        assert data2["available"] is True
        assert data2["mode_effective"] == "docker"

        # ③ 配置开启 + Docker 不可用 → 降级 + 安装指引
        monkeypatch.setattr(de.DockerExecutor, "available", lambda: False)
        data3 = TestClient(app2).get("/api/docker/status").json()
        assert data3["available"] is False
        assert data3["mode_effective"] == "process"
        assert "Docker" in data3["hint"] and "降级" in data3["hint"]

    def test_prewarm_endpoint(self, tmp_path, monkeypatch):
        # 注入假 runner 到端点使用的预热函数（探测环境无 Docker 也不失败）
        from app import server as server_module
        runner = _FakeRunner()
        monkeypatch.setattr(server_module, "_prewarm_runner", lambda: runner)
        app = create_app(
            settings=Settings(),
            projects_root=tmp_path / "projects",
            llm_factory=None,
            executor=None,
        )
        tc = TestClient(app)
        resp = tc.post("/api/prewarm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert [i["cached"] for i in data["images"]] == [True, True]


# ---------------------------------------------------------------------------
# M12-3 前端契约：client.html Docker 横幅与预热入口（落盘验证）
# ---------------------------------------------------------------------------

class TestClientBannerContract:
    _ROOT = Path(__file__).resolve().parent.parent

    def test_docker_banner_contract(self):
        html = (self._ROOT / "client.html").read_text(encoding="utf-8")
        assert 'id="docker-banner"' in html            # 横幅容器
        assert 'id="docker-banner-text"' in html       # 指引文案
        assert 'id="btn-prewarm"' in html              # M12-2 预热入口
        assert "checkDockerStatus" in html             # 连接后探测
        assert "/api/docker/status" in html            # 状态端点引用
        assert "/api/prewarm" in html                  # 预热端点引用
        assert "renderDockerBanner" in html            # 渲染函数


# ---------------------------------------------------------------------------
# M12-4：任务级预算透传（插件设置页 → API → BudgetGuard）
# ---------------------------------------------------------------------------

def _resp(content: str):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


def _assessment(score: int) -> str:
    return json.dumps({"task_type": "编程", "difficulty_score": score,
                       "reason": "t", "estimated_files": 2}, ensure_ascii=False)


def _review() -> str:
    return json.dumps({"scores": {"feasibility": 9, "security": 9, "maintainability": 9},
                       "strengths": [], "weaknesses": [], "risks": []}, ensure_ascii=False)


_TEAM_SCRIPTS = [
    json.dumps({"task_type": "编程", "difficulty_score": 7, "reason": "t",
                "estimated_files": 7}, ensure_ascii=False),
    "初始方案", _review(), _review(), "最终 spec",
    json.dumps({"modules": [{"name": "user", "responsibility": "用户",
                             "dependencies": [], "priority": 1}]}, ensure_ascii=False),
    json.dumps({"imports": [], "exports": ["core_fn"], "public_api": ["core_fn"],
                "dependencies": []}, ensure_ascii=False),
    "def core_fn():\n    return 1\n", "def test_core_fn():\n    assert core_fn() == 1\n",
]


class _TeamScriptLLM:
    """完整团队流程剧本桩（含 budget_guard / on_call 契约，供预算断言观测）。"""

    def __init__(self):
        self.scripts = list(_TEAM_SCRIPTS)
        self.call_log: list[dict] = []
        self.budget_guard = None
        self.on_call = None

    def chat(self, model, messages, json_mode=False, **kw):
        from app.utils.model_client import LLMResponse
        content = self.scripts.pop(0) if self.scripts else "ok"
        entry = {"model": model, "kind": "chat", "input_tokens": 10,
                 "output_tokens": 5, "content_chars": len(content)}
        self.call_log.append(entry)
        if self.on_call is not None:
            self.on_call(entry)
        return LLMResponse(model=model, content=content,
                           input_tokens=10, output_tokens=5)


class _TeamFactory:
    def __init__(self):
        self.last: _TeamScriptLLM | None = None

    def create(self):
        self.last = _TeamScriptLLM()
        return self.last


class TestBudgetPassthrough:
    def test_budget_tokens_override_reaches_guard(self, tmp_path):
        """team_flow 任务：budget_tokens 覆盖 team 缺省预算（guard 可观测）。"""
        from app.execution.executor import ExecutionResult, ExecutionStatus

        class _Skipped:
            def __call__(self, *a, **kw):
                return self

            def run(self, code, tests, timeout, expected_output="", module=""):
                return ExecutionResult(status=ExecutionStatus.SKIPPED)

        factory = _TeamFactory()
        app = create_app(
            settings=Settings(),
            projects_root=tmp_path / "projects",
            llm_factory=factory,
            executor=_Skipped(),
        )
        tc = TestClient(app)
        r = tc.post("/api/tasks", json={
            "kind": "run",
            "requirement": "开发一个用户管理系统，支持注册登录与数据持久化",
            "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
            "mode": "safe",
            "budget_tokens": 12345,
        })
        assert r.status_code == 200, r.text
        tid = r.json()["task_id"]
        deadline = time.time() + 15
        while time.time() < deadline:
            data = tc.get(f"/api/tasks/{tid}").json()
            if data["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.05)
        assert data["status"] == "succeeded", data.get("error")
        # M12-4：预算覆盖经落盘看板可观测（guard 在任务结束已被管线卸载）
        report = json.loads(
            (Path(data["result"]["project_dir"]) / "logs" / "cost_report.json")
            .read_text(encoding="utf-8")
        )
        assert report["budget_tokens"] == 12345   # 覆盖 team 缺省预算

    def test_budget_tokens_invalid_rejected(self, tmp_path):
        app = create_app(
            settings=Settings(),
            projects_root=tmp_path / "projects",
            llm_factory=None,
            executor=None,
        )
        tc = TestClient(app)
        resp = tc.post("/api/tasks", json={
            "kind": "run", "requirement": "开发一个系统",
            "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
            "mode": "safe", "budget_tokens": 0,
        })
        assert resp.status_code == 400
