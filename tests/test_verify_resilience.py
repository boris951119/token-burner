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


class TestAutoRepairLlmCallable:
    """keep7 取证：auto_repair 的 llm 曾被内层同名函数遮蔽且漏 return，
    RepoFixer 拿到 None→空文本→rounds=0，修复通道整体静默失效。
    回归断言：传给 RepoFixer 的 llm 必须返回非空字符串，
    且 fix() 返回后 auto_repair 如实报告轮次。"""

    def test_llm_callable_returns_nonempty_and_rounds_reported(
            self, tmp_path, monkeypatch):
        import types

        import app.arcbench_smoke as sm

        class _R:
            content = "修复方案内容"

        class _MC:
            def __init__(self, settings):
                self.calls = []

            def chat(self, model, messages):
                self.calls.append(model)
                return _R()

        monkeypatch.setattr("app.utils.model_client.ModelClient", _MC)

        smoke_calls = {"n": 0}

        def fake_run_smoke(code_dir):
            smoke_calls["n"] += 1
            if smoke_calls["n"] == 1:
                return False, "GET / -> 404（入口路由缺失？）"
            return True, "all ok"

        monkeypatch.setattr(sm, "run_smoke", fake_run_smoke)

        captured = {}

        class _FakeRepoFixer:
            def __init__(self, llm, project_dir, test_cmd=None,
                         max_rounds=3):
                captured["llm"] = llm

            def fix(self, issue):
                captured["issue"] = issue
                out = captured["llm"]("system", "user")  # 旧 bug 处拿到 None
                assert out and out.strip(), \
                    "llm 可调用必须返回非空内容（keep7 回归）"
                return types.SimpleNamespace(ok=True, rounds=2)

        monkeypatch.setattr("app.agents.repo_fixer.RepoFixer",
                            _FakeRepoFixer)

        (tmp_path / "code").mkdir()
        settings = Settings(models=["openai/glm-5.3",
                                    "openai/deepseek-v4-pro",
                                    "openai/minimax-m3"])
        ok, report = sm.auto_repair(tmp_path, settings, max_rounds=3)
        assert ok, report
        assert "修复方案内容" == captured["llm"]("s", "u")
        assert "2 轮" in report, f"轮次必须如实报告: {report}"


class TestMechFixBeforeLlm:
    """用户指令「修复不能靠概率」：冒烟 FAIL 后零 LLM 机械修复必须
    先于 LLM 修复出牌；机械修好则跳过 LLM 通道。"""

    def _settings(self):
        return Settings(models=["openai/glm-5.3",
                                "openai/deepseek-v4-pro",
                                "openai/minimax-m3"])

    def test_mech_fix_success_skips_llm(self, tmp_path, monkeypatch):
        import app.arcbench_smoke as sm

        (tmp_path / "code").mkdir()
        order = []

        smoke_calls = {"n": 0}

        def fake_run_smoke(code_dir):
            smoke_calls["n"] += 1
            if smoke_calls["n"] == 1:
                return False, "from auth import register  # 漂移"
            return True, "机械修复后通过"

        monkeypatch.setattr(sm, "run_smoke", fake_run_smoke)
        monkeypatch.setattr(
            sm, "run_all_fixers",
            lambda code_dir, ddl: (order.append("mech"),
                                   {"import路径漂移": ["x"]})[1])
        monkeypatch.setattr(
            sm, "collect_ddl", lambda code_dir: (order.append("ddl"), {})[1])

        def fail_auto_repair(*a, **k):
            order.append("llm")
            raise AssertionError("机械修复已通过冒烟，LLM 通道不应出牌")

        monkeypatch.setattr(sm, "auto_repair", fail_auto_repair)
        monkeypatch.setattr(sm, "_beat", lambda *a, **k: None)
        monkeypatch.setattr(sm, "_llm_from",
                            lambda settings: (lambda s, u: "ok"))
        monkeypatch.setattr(
            sm, "_journey_gate",
            lambda *a, **k: (True, "journey ok"))

        ok, report = sm.verify_delivery(tmp_path, "需求", self._settings())
        assert ok, report
        assert order == ["ddl", "mech"], f"机械修复必须先出牌: {order}"
        assert "mech-fix" in report

    def test_mech_fix_empty_falls_to_llm(self, tmp_path, monkeypatch):
        import app.arcbench_smoke as sm

        (tmp_path / "code").mkdir()
        order = []
        monkeypatch.setattr(sm, "run_smoke",
                            lambda code_dir: (False, "smoke fail"))
        monkeypatch.setattr(sm, "run_all_fixers",
                            lambda code_dir, ddl: {})
        monkeypatch.setattr(sm, "collect_ddl", lambda code_dir: {})
        monkeypatch.setattr(
            sm, "auto_repair",
            lambda *a, **k: (order.append("llm"), (True, "LLM 修好"))[1])
        monkeypatch.setattr(sm, "_beat", lambda *a, **k: None)
        monkeypatch.setattr(sm, "_llm_from",
                            lambda settings: (lambda s, u: "ok"))
        monkeypatch.setattr(
            sm, "_journey_gate",
            lambda *a, **k: (True, "journey ok"))

        ok, report = sm.verify_delivery(tmp_path, "需求", self._settings())
        assert ok, report
        assert order == ["llm"], "机械修复无发现时必须落到 LLM 通道"
