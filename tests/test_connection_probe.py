"""v1.1 C2 测试:连接探针 verdict 分类 + 模型自动发现 + 端点集成。

依据:v1.1-workplan C2——探针用连接自身凭据发微型真实调用(不经
ModelClient:不进任务预算、不进调用日志、不污染成本报告),verdict
分类 ok/auth_failed/model_not_found/rate_limited/network_error/error;
发现对 OpenAI 兼容 /models 拉取清单,失败回落手动输入。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.server import create_app
from app.utils import connections as conn_mod
from app.utils.connections import discover_models, probe_connection


class _FakeExc(Exception):
    """携带消息的假异常(模拟 litellm 异常文本)。"""


def _probe_with(error: Exception | None = None, content: str = "pong"):
    conn = {"id": "c1", "name": "n", "base_url": "https://api.example/v1",
            "api_key": "sk-live", "models": ["openai/probe-model"]}
    calls = {}

    def fake_completion(**kwargs):
        calls.update(kwargs)
        if error is not None:
            raise error
        return {"choices": [{"message": {"content": content},
                             "finish_reason": "stop"}], "usage": {}}

    result = probe_connection(conn, completion_fn=fake_completion)
    return result, calls


class TestProbeVerdicts:
    def test_ok_when_call_succeeds(self):
        result, calls = _probe_with()
        assert result["ok"] is True and result["verdict"] == "ok"
        assert "latency_ms" in result
        # 使用连接自身凭据(微型调用,不进任务成本口径)
        assert calls["api_key"] == "sk-live"
        assert calls["base_url"] == "https://api.example/v1"
        assert calls["max_tokens"] <= 16

    def test_auth_failed(self):
        result, _ = _probe_with(_FakeExc("Error code: 401 - Invalid API key provided"))
        assert result["verdict"] == "auth_failed" and result["ok"] is False

    def test_model_not_found(self):
        result, _ = _probe_with(_FakeExc("Error code: 404 - The model `x` does not exist"))
        assert result["verdict"] == "model_not_found"

    def test_rate_limited(self):
        result, _ = _probe_with(_FakeExc("Error code: 429 - Rate limit reached, quota exceeded"))
        assert result["verdict"] == "rate_limited"

    def test_network_error(self):
        result, _ = _probe_with(_FakeExc("Connection error: getaddrinfo failed"))
        assert result["verdict"] == "network_error"

    def test_unknown_is_error(self):
        result, _ = _probe_with(_FakeExc("some totally weird failure"))
        assert result["verdict"] == "error"

    def test_explicit_model_overrides_first(self):
        conn = {"id": "c", "name": "n", "base_url": "", "api_key": "k",
                "models": ["first-model", "second-model"]}
        seen = {}

        def fake(**kwargs):
            seen.update(kwargs)
            return {"choices": [{"message": {"content": "p"}, "finish_reason": "stop"}]}

        probe_connection(conn, model="second-model", completion_fn=fake)
        assert seen["model"] == "second-model"

    def test_no_models_is_error(self):
        result = probe_connection({"id": "c", "name": "n", "base_url": "",
                                   "api_key": "k", "models": []})
        assert result["verdict"] == "error"


class TestDiscoverModels:
    def test_parses_openai_style_listing(self):
        def fake_get(url, key):
            assert url.endswith("/models")
            assert key == "sk-live"
            return {"data": [{"id": "qwen3.8-flash"}, {"id": "deepseek-v3"},
                             {"id": None}, "junk"]}

        result = discover_models("https://api.example/v1/", "sk-live", http_get=fake_get)
        assert result["ok"] is True
        assert result["models"] == ["qwen3.8-flash", "deepseek-v3"]

    def test_failure_returns_detail(self):
        def fake_get(url, key):
            raise _FakeExc("401 unauthorized")

        result = discover_models("https://api.example/v1", "bad", http_get=fake_get)
        assert result["ok"] is False and result["models"] == []
        assert "401" in result["detail"]

    def test_missing_base_url(self):
        result = discover_models("", "k")
        assert result["ok"] is False and result["models"] == []


class TestProbeEndpoints:
    @pytest.fixture
    def client(self, tmp_path):
        settings = Settings(
            connections_path=str(tmp_path / "secrets.local.json"),
            projects_root=str(tmp_path / "projects"),
        )
        app = create_app(settings=settings)
        conn_mod.set_store(tmp_path / "secrets.local.json")
        with TestClient(app) as c:
            yield c

    def _add_connection(self, c, token):
        r = c.post("/api/connections", headers={"X-Session-Token": token},
                   json={"name": "n", "base_url": "https://x/v1",
                         "api_key": "sk-x", "models": ["openai/m"]})
        assert r.status_code == 200
        return r.json()["connection"]["id"]

    def test_probe_endpoint_passthrough_and_guard(self, client):
        c = client
        token = c.get("/api/session").json()["token"]
        assert c.post("/api/connections/nope/probe",
                      headers={"X-Session-Token": token},
                      json={}).status_code == 404
        cid = self._add_connection(c, token)

        def fake_probe(conn, model=None):
            return {"ok": True, "verdict": "ok", "latency_ms": 5,
                    "model": model or "", "detail": "连通正常"}

        orig = conn_mod.probe_connection
        conn_mod.probe_connection = fake_probe
        try:
            r = c.post(f"/api/connections/{cid}/probe",
                       headers={"X-Session-Token": token}, json={})
            assert r.status_code == 200 and r.json()["verdict"] == "ok"
            assert c.post(f"/api/connections/{cid}/probe", json={}).status_code == 403
        finally:
            conn_mod.probe_connection = orig

    def test_discover_endpoint_passthrough(self, client, monkeypatch):
        monkeypatch.setattr(
            conn_mod, "discover_models",
            lambda base, key: {"ok": True, "models": ["m1", "m2"]})
        c = client
        token = c.get("/api/session").json()["token"]
        r = c.post("/api/models/discover", headers={"X-Session-Token": token},
                   json={"base_url": "https://x/v1", "api_key": "k"})
        assert r.status_code == 200 and r.json()["models"] == ["m1", "m2"]
        assert c.post("/api/models/discover",
                      json={"base_url": "https://x/v1", "api_key": "k"}).status_code == 403
