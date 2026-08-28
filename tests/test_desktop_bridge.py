"""desktop.py Bridge 测试：js_api 进程内桥（零 socket 架构）。"""
from __future__ import annotations

import threading

import pytest

from app.desktop import Bridge


@pytest.fixture()
def bridge():
    """真实 create_app + TestClient（无 LLM 调用，仅触轻量端点）。"""
    return Bridge()


class TestBridgeRequest:
    def test_get_health(self, bridge):
        r = bridge.request("GET", "/api/health", None)
        assert r["status"] == 200
        assert '"ok"' in r["body"] or "'ok'" in r["body"]

    def test_post_route_validation_error(self, bridge):
        """空 requirement → 422（pydantic 校验），错误经桥原样透传。"""
        r = bridge.request("POST", "/api/route", '{"requirement": ""}')
        assert r["status"] == 422

    def test_post_run_mode_invalid(self, bridge):
        r = bridge.request(
            "POST", "/api/run",
            '{"requirement": "x", "mode": "bad"}')
        assert r["status"] == 400
        assert "mode" in r["body"]

    def test_post_route_llm_error_maps_503(self, bridge):
        """LLM 异常 → 503 可读错误（进程存活语义，server 契约保持）。"""
        r = bridge.request(
            "POST", "/api/route",
            '{"requirement": "做一个待办事项应用"}')
        assert r["status"] == 503
        assert "LLM" in r["body"]

    def test_get_resumable_empty_root(self, bridge, tmp_path, monkeypatch):
        """空 projects 目录 → 空列表（JSON 数组可解析）。"""
        import json

        from app.server import create_app
        from starlette.testclient import TestClient

        app = create_app(projects_root=tmp_path / "projects")
        b = Bridge.__new__(Bridge)
        b._client = TestClient(app)
        b._lock = threading.Lock()
        r = b.request("GET", "/api/resumable", None)
        assert r["status"] == 200
        assert json.loads(r["body"]) == []

    def test_concurrent_requests_serialized(self, bridge):
        """并发调用（TestClient 非线程安全）→ 桥的锁保证不崩。"""
        results: list[dict] = []
        threads = [
            threading.Thread(
                target=lambda: results.append(
                    bridge.request("GET", "/api/health", None)))
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 8
        assert all(r["status"] == 200 for r in results)
