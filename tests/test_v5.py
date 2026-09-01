"""V5 批次测试：M10-5 联网调研（可配置供应商 + 失败回退资料注入）。"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.agents.web_research import (
    fetch_web_material,
    parse_ddg_results,
    render_material,
)


# ---------------------------------------------------------------------------
# fetch_web_material：开关 / 供应商分发 / 降级链路
# ---------------------------------------------------------------------------

class TestFetchWebMaterial:
    def test_disabled_returns_empty_without_search(self):
        calls = []
        s = Settings()  # researcher_web_enabled 缺省 False
        r = fetch_web_material("fastapi", s, search_fn=lambda q, st: calls.append(q))
        assert r == ""
        assert calls == []          # 开关关：零网络行为

    def test_success_renders_material(self):
        s = Settings(
            researcher_enabled=True,
            researcher_web_enabled=True,
            research_web_provider="duckduckgo",
        )

        def fake_search(q, st):
            return [{"title": "FastAPI Docs", "url": "https://example.com",
                     "snippet": "modern web framework"}]

        r = fetch_web_material("fastapi", s, search_fn=fake_search)
        assert "FastAPI Docs" in r
        assert "https://example.com" in r
        assert "modern web framework" in r

    def test_search_exception_falls_back_to_empty(self):
        s = Settings(
            researcher_enabled=True,
            researcher_web_enabled=True,
            research_web_provider="duckduckgo",
        )

        def boom(q, st):
            raise RuntimeError("network unreachable")

        assert fetch_web_material("q", s, search_fn=boom) == ""

    def test_empty_results_falls_back(self):
        s = Settings(
            researcher_enabled=True,
            researcher_web_enabled=True,
            research_web_provider="duckduckgo",
        )
        assert fetch_web_material("q", s, search_fn=lambda q, st: []) == ""

    def test_tavily_missing_key_falls_back(self, monkeypatch):
        """tavily 无 key → 空结果 → 回退（真实降级场景，替代未知 provider 用例）。"""
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        s = Settings(
            researcher_enabled=True,
            researcher_web_enabled=True,
            research_web_provider="tavily",
        )
        assert fetch_web_material("q", s) == ""


# ---------------------------------------------------------------------------
# 供应商解析器（确定性程序行为，零网络）
# ---------------------------------------------------------------------------

class TestDdgParser:
    _PAGE = """
    <div class="result">
      <a class="result__a" href="https://example.com/a">Fast<b>API</b> &amp; Co</a>
      <a class="result__snippet" href="#">a &lt;modern&gt; framework</a>
    </div>
    <div class="result">
      <a class="result__a" href="https://example.com/b">Second</a>
      <a class="result__snippet" href="#">second snippet</a>
    </div>
    """

    def test_parses_title_url_snippet(self):
        rs = parse_ddg_results(self._PAGE, 5)
        assert len(rs) == 2
        assert rs[0]["title"] == "FastAPI & Co"       # 去标签 + unescape
        assert rs[0]["url"] == "https://example.com/a"
        assert rs[0]["snippet"] == "a <modern> framework"

    def test_limit(self):
        assert len(parse_ddg_results(self._PAGE, 1)) == 1


class TestTavily:
    def test_missing_key_returns_empty(self, monkeypatch):
        from app.agents.web_research import search_tavily
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        s = Settings(researcher_web_enabled=True, research_web_provider="tavily")
        assert search_tavily("q", s) == []


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

class TestWebConfigValidation:
    def test_invalid_provider_rejected(self):
        with pytest.raises(ValueError, match="research_web_provider"):
            Settings(researcher_web_enabled=True, research_web_provider="google")

    def test_provider_empty_ok_when_disabled(self):
        Settings()  # 缺省：开关关 + provider 空，合法

    def test_max_results_range(self):
        with pytest.raises(ValueError, match="research_web_max_results"):
            Settings(research_web_max_results=0)


# ---------------------------------------------------------------------------
# 端到端：联网资料到达 Researcher 生成环节；失败回退不阻塞任务
# （复用 V3 的 team 剧本桩，桩 LLM 记录 messages 以观测资料内容）
# ---------------------------------------------------------------------------

import json as _json  # noqa: E402
import time as _time  # noqa: E402

from pathlib import Path  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import test_v3 as v3  # noqa: E402
from app.server import create_app  # noqa: E402


class _RecordingLLM(v3._TeamScriptLLM):
    """在剧本桩基础上记录 chat messages（观测 web 资料是否到达）。

    research=on 且联网成功时 Researcher 在评估后插入一次 brief 生成
    调用——剧本头部需补其输出（ResearchBrief JSON，sources/versions
    非空才过校验）；联网失败时 Researcher 空资料早退零消耗，不插入。
    """

    def __init__(self, with_brief: bool):
        super().__init__()
        if with_brief:
            brief = _json.dumps({
                "sources": ["https://example.com/docs"],
                "versions": ["hyperscan 5.4"],
                "examples": ["scan() 示例"],
                "pitfalls": ["需要 root 权限"],
            }, ensure_ascii=False)
            # Researcher 在评估（#0 难度 JSON）之后、方案讨论之前插入
            self.scripts = [self.scripts[0], brief, *self.scripts[1:]]
        self.user_messages: list[str] = []

    def chat(self, model, messages, json_mode=False, **kw):
        for m in messages:
            if m.get("role") == "user":
                self.user_messages.append(str(m.get("content", "")))
        return super().chat(model, messages, json_mode=json_mode, **kw)


def _run_team_task(tmp_path, monkeypatch, web_material: str) -> _RecordingLLM:
    """提交 research=on 的 team 任务并等待完成，返回记录型 LLM 实例。"""
    from app.pipeline import fetch_web_material as _fw

    monkeypatch.setattr(
        "app.pipeline.fetch_web_material",
        lambda q, s, **kw: web_material,
    )
    factory = v3._TeamFactory()

    class _RecFactory:
        def create(self):
            llm = _RecordingLLM(with_brief=bool(web_material))
            factory.last = llm
            return llm

    class _Skipped:
        def __call__(self, *a, **kw):
            return self

        def run(self, code, tests, timeout, expected_output="", module=""):
            from app.execution.executor import ExecutionResult, ExecutionStatus
            return ExecutionResult(status=ExecutionStatus.SKIPPED)

    app = create_app(
        settings=Settings(
            researcher_enabled=True,
            researcher_web_enabled=True,          # M10-5：联网通道开
            research_web_provider="duckduckgo",   # search_fn 注入，无真实网络
            research_cache_enabled=False,         # 隔离共享缓存（.research_cache.db）
        ),
        projects_root=tmp_path / "projects",
        llm_factory=_RecFactory(),
        executor=_Skipped(),
    )
    tc = TestClient(app)
    r = tc.post("/api/tasks", json={
        "kind": "run",
        "requirement": "开发一个基于 hyperscan 的陌生框架任务系统",
        "models": ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet"],
        "mode": "safe",
        "research": "on",
    })
    assert r.status_code == 200, r.text
    tid = r.json()["task_id"]
    deadline = _time.time() + 15
    while _time.time() < deadline:
        data = tc.get(f"/api/tasks/{tid}").json()
        if data["status"] in ("succeeded", "failed"):
            break
        _time.sleep(0.05)
    assert data["status"] == "succeeded", data.get("error")
    assert factory.last is not None
    return factory.last


class TestPipelineWebIntegration:
    def test_web_material_reaches_researcher(
        self, tmp_path, monkeypatch
    ):
        llm = _run_team_task(
            tmp_path, monkeypatch, "WEB_MATERIAL_MARKER hyperscan docs"
        )
        joined = "\n".join(llm.user_messages)
        assert "WEB_MATERIAL_MARKER" in joined   # 联网资料到达生成环节

    def test_web_failure_falls_back_and_task_succeeds(
        self, tmp_path, monkeypatch
    ):
        llm = _run_team_task(tmp_path, monkeypatch, "")   # 联网失败 → 空串
        joined = "\n".join(llm.user_messages)
        assert "WEB_MATERIAL_MARKER" not in joined
        # 任务仍成功（回退资料注入模式；无用户资料时 researcher 记 last_error）
