# -*- coding: utf-8 -*-
"""验收阶段韧性测试（平台首单取证：auto_repair 修复中 pro 超时×3
无备胎，RuntimeError 崩穿 main → 官方环境 exit 1）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings


@pytest.fixture
def fake_mc(monkeypatch):
    """假 ModelClient：按模型名决定成败，记录调用序。"""
    class _R:
        content = "ok"

    class _MC:
        def __init__(self, settings):
            self.calls: list[str] = []

        def chat(self, model, messages):
            import app.arcbench_smoke as sm

            self.calls.append(model)
            if model in sm._TEST_FAIL_MODELS:
                raise RuntimeError(f"degraded: {model}")
            return _R()

    import app.arcbench_smoke as sm
    sm._TEST_FAIL_MODELS = set()
    monkeypatch.setattr(
        "app.utils.model_client.ModelClient", _MC)
    return sm


class TestLlmFromFallback:
    def test_main_fails_fallback_catches(self, fake_mc, monkeypatch):
        sm = fake_mc
        sm._TEST_FAIL_MODELS = {"openai/glm-5.3"}
        settings = Settings(models=["openai/glm-5.3",
                                    "openai/deepseek-v4-pro",
                                    "openai/minimax-m3"])
        llm = sm._llm_from(settings)
        assert llm("s", "u") == "ok"

    def test_all_chain_failed_raises(self, fake_mc):
        sm = fake_mc
        sm._TEST_FAIL_MODELS = {"openai/glm-5.3", "openai/deepseek-v4-pro",
                                "openai/minimax-m3"}
        settings = Settings(models=["openai/glm-5.3",
                                    "openai/deepseek-v4-pro",
                                    "openai/minimax-m3"])
        llm = sm._llm_from(settings)
        with pytest.raises(RuntimeError, match="全链失败"):
            llm("s", "u")


class TestVerifyGracefulDegradation:
    def _prep(self, tmp_path):
        code = tmp_path / "projects" / "p" / "code"
        code.mkdir(parents=True)
        return tmp_path / "projects" / "p"

    def test_journey_gate_crash_degrades_to_fail(self, tmp_path, monkeypatch):
        """旅程闸门内部崩溃（如 LLM 全灭）必须优雅 FAIL，不崩穿。"""
        import app.arcbench_smoke as sm

        project = self._prep(tmp_path)
        monkeypatch.setattr(sm, "run_smoke", lambda c, p=None: (True, "ok"))
        monkeypatch.setattr(
            sm, "_llm_from", lambda s: (lambda s_, u_: "ok"))
        def _boom(*a, **k):
            raise RuntimeError("验收 LLM 全链失败")
        monkeypatch.setattr(sm, "_journey_gate", _boom)

        ok, report = sm.verify_delivery(project, "需求", Settings())
        assert ok is False
        assert "FAIL" in report or "失败" in report

    def test_auto_repair_crash_degrades_to_fail(self, tmp_path, monkeypatch):
        import app.arcbench_smoke as sm

        project = self._prep(tmp_path)
        monkeypatch.setattr(sm, "run_smoke", lambda c, p=None: (False, "health 500"))
        def _boom(*a, **k):
            raise RuntimeError("验收 LLM 全链失败")
        monkeypatch.setattr(sm, "auto_repair", _boom)

        ok, report = sm.verify_delivery(project, "需求", Settings())
        assert ok is False
        assert "全链失败" in report or "FAIL" in report


class TestEmptyContentGuard:
    """gen-4 取证：修复计划 LLM 返回空内容（"输入文本为空"）——
    空响应必须视为该模型失败，接力备胎。"""

    def test_empty_content_falls_to_next_model(self, monkeypatch):
        import app.arcbench_smoke as sm

        class _R:
            content = ""

        class _MC:
            def __init__(self, settings):
                self.calls = []

            def chat(self, model, messages):
                self.calls.append(model)
                if model == "openai/glm-5.3":
                    return _R()          # 空内容
                return type("R2", (), {"content": "真实方案"})()

        monkeypatch.setattr("app.utils.model_client.ModelClient", _MC)
        settings = Settings(models=["openai/glm-5.3",
                                    "openai/deepseek-v4-pro",
                                    "openai/minimax-m3"])
        llm = sm._llm_from(settings)
        out = llm("s", "u")
        assert out == "真实方案"
