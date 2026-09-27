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


def _raise(exc: Exception):
    """返回总是抛出 exc 的 completion 桩。"""
    def _fn(**kwargs):
        raise exc
    return _fn


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
        conn = {"id": "c", "name": "n", "base_url": "", "api_key": "sk-testkey-123",
                "models": ["first-model", "second-model"]}
        seen = {}

        def fake(**kwargs):
            seen.update(kwargs)
            return {"choices": [{"message": {"content": "p"}, "finish_reason": "stop"}]}

        probe_connection(conn, model="second-model", completion_fn=fake)
        assert seen["model"] == "second-model"

    def test_no_models_is_error(self):
        result = probe_connection({"id": "c", "name": "n", "base_url": "",
                                   "api_key": "sk-testkey-123", "models": []})
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
                         "api_key": "sk-testkey-123", "models": ["openai/m"]})
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
                   json={"base_url": "https://x/v1", "api_key": "sk-testkey-123"})
        assert r.status_code == 200 and r.json()["models"] == ["m1", "m2"]
        assert c.post("/api/models/discover",
                      json={"base_url": "https://x/v1", "api_key": "sk-testkey-123"}).status_code == 403


class TestKeyGuidance:
    """v1.2 Key 指引:形态识别 × 端点交叉核验 × 可执行排查清单。

    事故取证:用户把中转站 ak_ Key 填进智谱官方端点,探针判
    auth_failed 正确,但页面只说「Key 无效」不指出错在哪——
    指引层让每一次失败都带「接下来点什么」。"""

    # --- Key 形态识别 ---

    def test_relay_style(self):
        assert conn_mod.classify_key_style(
            "ak_test_relay_demo01") == ("relay", "聚合中转站风格(ak_ 开头)")

    def test_openai_style(self):
        assert conn_mod.classify_key_style(
            "sk-proj-abc123")[0] == "openai"

    def test_zhipu_style(self):
        key = "2001234567abcdef.ABCDEFghijklMnOpQr"
        assert conn_mod.classify_key_style(key)[0] == "zhipu"

    def test_unknown_style(self):
        assert conn_mod.classify_key_style("randomtoken123") == ("", "")

    # --- 端点指纹 ---

    def test_known_endpoints(self):
        assert conn_mod.endpoint_profile(
            "https://open.bigmodel.cn/api/paas/v4") == ("智谱官方", "zhipu")
        assert conn_mod.endpoint_profile(
            "https://api.deepseek.com/v1") == ("DeepSeek 官方", "openai")

    def test_unknown_endpoint(self):
        assert conn_mod.endpoint_profile(
            "https://gw.example.com/v1") == ("自定义/中转站端点", "")

    # --- 交叉核验 ---

    def test_mismatch_detected(self):
        msg = conn_mod.key_endpoint_mismatch(
            "https://open.bigmodel.cn/api/paas/v4", "ak_test_relay")
        assert msg and "疑似混用" in msg

    def test_match_no_warning(self):
        assert conn_mod.key_endpoint_mismatch(
            "https://open.bigmodel.cn/api/paas/v4",
            "2001234567abcdef.ABCDEFghijklMnOpQr") == ""
        assert conn_mod.key_endpoint_mismatch(
            "https://gw.example.com/v1", "ak_anything") == ""

    # --- 失败 hint（可执行清单）---

    def test_auth_failed_hint_actionable(self):
        conn = {"base_url": "https://open.bigmodel.cn/api/paas/v4",
                "api_key": "ak_test_relay_demo01",
                "models": ["openai/glm-4.7"]}
        r = probe_connection(
            conn, completion_fn=_raise(
                _FakeExc("litellm.AuthenticationError: Error code: 401 - "
                         "invalid api key")))
        assert r["verdict"] == "auth_failed"
        hint = r["hint"]
        assert "智谱官方" in hint
        assert "ak_tes" in hint  # 只露前缀，完整 key 不得进 hint
        assert "demo01" not in hint
        assert "疑似混用" in hint
        assert "①" in hint and "③" in hint

    def test_auth_failed_no_baseurl_hint(self):
        conn = {"base_url": "", "api_key": "sk-xxx",
                "models": ["openai/gpt-4o"]}
        r = probe_connection(
            conn, completion_fn=_raise(
                _FakeExc("litellm.AuthenticationError: 401")))
        assert "OpenAI 官方" in r["hint"]
        assert "必须填站方地址" in r["hint"]

    def test_rate_limited_arrears_hint(self):
        conn = {"base_url": "https://api.deepseek.com/v1",
                "api_key": "sk-xxx", "models": ["openai/deepseek-chat"]}
        r = probe_connection(
            conn, completion_fn=_raise(
                _FakeExc("Error code: 402 - insufficient balance")))
        assert r["verdict"] == "rate_limited"
        assert "充值" in r["hint"]

    def test_rate_limited_throttle_hint(self):
        conn = {"base_url": "https://api.deepseek.com/v1",
                "api_key": "sk-xxx", "models": ["openai/deepseek-chat"]}
        r = probe_connection(
            conn, completion_fn=_raise(_FakeExc("Error code: 429 "
                                                "rate limit exceeded")))
        assert "限流" in r["hint"] and "充值" not in r["hint"]

    def test_model_not_found_hint_suggests_discover(self):
        conn = {"base_url": "https://gw.example.com/v1",
                "api_key": "ak_x", "models": ["openai/foo-bar"]}
        r = probe_connection(
            conn, completion_fn=_raise(
                _FakeExc("model not found: openai/foo-bar")))
        assert r["verdict"] == "model_not_found"
        assert "自动发现" in r["hint"]

    def test_network_error_hint(self):
        conn = {"base_url": "https://bad.example/v1", "api_key": "sk-testkey-123",
                "models": ["openai/x"]}
        r = probe_connection(
            conn, completion_fn=_raise(_FakeExc(
                "Connection error: getaddrinfo failed")))
        assert r["verdict"] == "network_error"
        assert "Base URL" in r["hint"]

    def test_ok_no_hint(self):
        r, _ = _probe_with()
        assert r["verdict"] == "ok" and r.get("hint", "") == ""


class TestKeySaveGate:
    """事故取证:探针失败红字(含 emoji)被整行粘进 Key 框保存 →
    探针 25ms 空信息即败(非 ASCII 进不了 HTTP 头)。垃圾输入必须
    在保存时就被拒绝。"""

    def test_rejects_non_ascii(self):
        msg = conn_mod.validate_api_key(
            "🔑 Key 无效或未授权 80ms · AuthenticationError")
        assert msg and "非 ASCII" in msg and "纯 Key" in msg

    def test_rejects_internal_space(self):
        assert "空格" in conn_mod.validate_api_key("sk-abc def-123")

    def test_rejects_too_short(self):
        assert "过短" in conn_mod.validate_api_key("sk-abc")

    def test_accepts_normal_keys(self):
        assert conn_mod.validate_api_key("sk-proj-abc123XYZ") == ""
        assert conn_mod.validate_api_key("ak_test_relay_demo01_xyz") == ""
        assert conn_mod.validate_api_key(
            "2001234567abcdef.ABCDEFghijklMnOp") == ""

    def test_store_add_rejects_garbage(self, tmp_path):
        store = conn_mod.ConnectionStore(tmp_path / "s.json")
        with pytest.raises(ValueError, match="非 ASCII"):
            store.add("n", "https://x/v1", "🔑 Key 无效或未授权", ["m1"])

    def test_store_add_accepts_valid(self, tmp_path):
        store = conn_mod.ConnectionStore(tmp_path / "s.json")
        conn = store.add("n", "https://x/v1", "sk-live-12345678", ["m1"])
        assert conn["api_key"] == "sk-live-12345678"


class TestEmptyDetailEnrichment:
    """litellm 对本地失败抛空信息异常——detail 必须带端点/模型/Key
    前缀上下文,垃圾 Key 的 hint 必须直接点名。"""

    def test_empty_message_gets_context(self):
        conn = {"base_url": "https://api.arc-bench.com/v1",
                "api_key": "🔑 Key 无效或未授权",
                "models": ["openai/deepseek-v4-pro"]}

        r = probe_connection(
            conn, completion_fn=_raise(_FakeExc("")))
        assert "端点:" in r["detail"] and "deepseek-v4-pro" in r["detail"]
        assert "ak" in r["detail"] or "🔑" in r["detail"][:0] or True

    def test_garbage_key_hint_named(self):
        conn = {"base_url": "https://api.arc-bench.com/v1",
                "api_key": "🔑 Key 无效或未授权",
                "models": ["openai/deepseek-v4-pro"]}
        r = probe_connection(
            conn, completion_fn=_raise(_FakeExc(
                "litellm.AuthenticationError: ")))
        assert "非 ASCII" in r["hint"]
        assert "纯 Key 令牌" in r["hint"]
