"""v1.1 C1 连接注册表测试:CRUD/掩码/热加载解析/端点防护/不泄密。

依据:v1.1-workplan C1——前端「API 接口配置」的后端真身:
- 密钥只写不读(GET 永远掩码);密钥仅落 secrets.local.json(不入库);
- ModelClient 调用前按模型名解析连接凭据,命中注入 api_key/base_url,
  未命中回落环境变量(热加载,免重启);
- 写端点需同源会话令牌 + Host 白名单(防 localhost CSRF/DNS rebinding)。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.server import create_app
from app.utils import connections as conn_mod
from app.utils.connections import ConnectionStore, mask_key, registry_models


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "secrets.local.json"


@pytest.fixture
def store(store_path):
    return ConnectionStore(store_path)


class TestConnectionStore:
    def test_add_and_get(self, store):
        conn = store.add("aliyun", "https://x/v1", "sk-abc123456789", ["openai/qwen"])
        got = store.get(conn["id"])
        assert got["api_key"] == "sk-abc123456789"  # store 层内部可见(仅服务端)
        assert got["models"] == ["openai/qwen"]

    def test_add_validation(self, store):
        with pytest.raises(ValueError):
            store.add("", "https://x", "k", ["m"])
        with pytest.raises(ValueError):
            store.add("n", "https://x", "", ["m"])
        with pytest.raises(ValueError):
            store.add("n", "https://x", "k", [" ", ""])

    def test_delete(self, store):
        conn = store.add("n", "", "k", ["m"])
        assert store.delete(conn["id"]) is True
        assert store.delete(conn["id"]) is False
        assert store.all() == []

    def test_corrupted_file_falls_back_empty(self, store_path):
        store_path.write_text("not-json{", encoding="utf-8")
        store = ConnectionStore(store_path)
        assert store.all() == []

    def test_find_by_model(self, store):
        store.add("a", "https://a", "k1", ["openai/qwen3.8-flash", "openai/qwen3.6-flash"])
        store.add("b", "https://b", "k2", ["openai/deepseek-v3"])
        assert store.find_by_model("openai/deepseek-v3")["name"] == "b"
        assert store.find_by_model("openai/nonexistent") is None

    def test_registry_models_union_keeps_order(self, store):
        store.add("a", "", "k", ["z-model", "a-model"])
        assert registry_models(["preset-1", "a-model"], store) == [
            "preset-1", "a-model", "z-model"]

    def test_mask_key(self):
        assert mask_key("sk-abc123456789") == "sk-ab****6789"
        assert mask_key("short") == "****"


class TestNoKeyLeak:
    def test_masked_view_never_contains_raw_key(self, store):
        conn = store.add("aliyun", "https://x/v1", "sk-SUPER-SECRET-VALUE", ["openai/qwen"])
        masked = conn_mod.masked(conn)
        dumped = json.dumps(masked, ensure_ascii=False)
        assert "sk-SUPER-SECRET-VALUE" not in dumped
        assert "****" in masked["api_key"]

    def test_persisted_file_holds_key_for_server(self, store, store_path):
        store.add("n", "https://x", "sk-raw-key-999", ["m"])
        raw = store_path.read_text(encoding="utf-8")
        assert "sk-raw-key-999" in raw  # 密钥在本地密钥库中(服务端可用,gitignore 覆盖)
        assert json.loads(raw)["connections"][0]["api_key"] == "sk-raw-key-999"


class TestModelClientResolution:
    def test_connection_creds_injected_into_call(self, tmp_path):
        path = tmp_path / "secrets.local.json"
        conn_mod.set_store(path)
        ConnectionStore(path).add(
            "aliyun", "https://maas.example/v1", "sk-live-key", ["openai/probe-model"])

        captured = {}

        def fake_completion(**kwargs):
            captured.update(kwargs)
            return {"choices": [{"message": {"content": "ok"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

        from app.utils.model_client import ModelClient
        client = ModelClient(Settings(models=["openai/probe-model"]),
                             completion_fn=fake_completion)
        resp = client.chat("openai/probe-model", [{"role": "user", "content": "hi"}])
        assert resp.content == "ok"
        assert captured["api_key"] == "sk-live-key"
        assert captured["base_url"] == "https://maas.example/v1"
        conn_mod.set_store(tmp_path / "none.json")  # 还原单例,防跨测试污染

    def test_no_connection_falls_back_to_env_check(self, tmp_path):
        conn_mod.set_store(tmp_path / "secrets.local.json")  # 空表

        def fake_completion(**kwargs):
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {}}

        from app.utils.model_client import ModelClient, MissingApiKeyError
        client = ModelClient(Settings(), completion_fn=fake_completion)
        # anthropic/ 前缀命中 MODEL_ENV_KEYS 且环境无密钥 → 快速失败(旧行为保留)
        with pytest.raises(MissingApiKeyError):
            client.chat("claude-3-5-sonnet", [{"role": "user", "content": "hi"}])
        conn_mod.set_store(tmp_path / "none.json")


@pytest.fixture
def client(tmp_path):
    """create_app + 连接库指向 tmp;返回 (TestClient, 连接库路径)。"""
    settings = Settings(
        connections_path=str(tmp_path / "secrets.local.json"),
        projects_root=str(tmp_path / "projects"),
    )
    app = create_app(settings=settings)
    conn_mod.set_store(tmp_path / "secrets.local.json")
    with TestClient(app) as c:
        yield c, tmp_path / "secrets.local.json"


class TestConnectionEndpoints:
    def test_session_and_crud_roundtrip(self, client):
        c, _ = client
        token = c.get("/api/session").json()["token"]
        r = c.post("/api/connections", headers={"X-Session-Token": token},
                   json={"name": "aliyun", "base_url": "https://maas/v1",
                         "api_key": "sk-live-abcdef123",
                         "models": ["openai/qwen3.8-flash"]})
        assert r.status_code == 200
        body = r.json()
        assert body["connection"]["api_key"].endswith("****") or "****" in body["connection"]["api_key"]
        assert "sk-live-abcdef123" not in r.text  # 响应体不泄密
        assert "openai/qwen3.8-flash" in body["available_models"]

        listed = c.get("/api/connections").json()
        assert listed["connections"][0]["api_key"] == body["connection"]["api_key"]

        cid = body["connection"]["id"]
        assert c.delete(f"/api/connections/{cid}",
                        headers={"X-Session-Token": token}).status_code == 200
        assert c.get("/api/connections").json()["connections"] == []

    def test_write_requires_session_token(self, client):
        c, _ = client
        assert c.post("/api/connections", json={
            "name": "n", "api_key": "k", "models": ["m"]}).status_code == 403
        assert c.delete("/api/connections/whatever").status_code == 403

    def test_delete_missing_returns_404(self, client):
        c, _ = client
        token = c.get("/api/session").json()["token"]
        assert c.delete("/api/connections/nonexistent",
                        headers={"X-Session-Token": token}).status_code == 404

    def test_config_reflects_connection_models(self, client):
        c, _ = client
        token = c.get("/api/session").json()["token"]
        before = set(c.get("/api/config").json()["models"])
        c.post("/api/connections", headers={"X-Session-Token": token},
               json={"name": "n", "api_key": "k", "models": ["openai/brand-new"]})
        after = set(c.get("/api/config").json()["models"])
        assert "openai/brand-new" in after and "openai/brand-new" not in before

    def test_bad_request_400(self, client):
        c, _ = client
        token = c.get("/api/session").json()["token"]
        # 空模型清单被 Pydantic 模式层拦下(422)
        assert c.post("/api/connections", headers={"X-Session-Token": token},
                      json={"name": "n", "api_key": "k", "models": []}).status_code == 422
        # 仅空白的名称穿过模式层,由注册表校验升 400
        r = c.post("/api/connections", headers={"X-Session-Token": token},
                   json={"name": "   ", "api_key": "k", "models": ["m"]})
        assert r.status_code == 400
