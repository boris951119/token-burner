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
            def __init__(self, llm, project_dir, test_cmd=None, stop_check=None,
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


class TestRepairFundAndStallGates:
    """修复开工前的预算体检 + 「修了等于没修」的指纹止损。

    彩排取证两条：shape-mini 三轮修复各自瞬时抛在同一行「任务 token 总预算
    已耗尽」上（异常被 except 吞成 note，循环照进下一轮）；keep-r1 的 R2/R3 在
    同一条 seed 断言上各自失败。两者都是零进展空转，烧的却是墙钟。
    """

    def _drive(self, monkeypatch, tmp_path, *, smoke_report, rounds=3,
               budget=100_000, used=0, journey_ok=False, reserve=0.0):
        import app.arcbench_smoke as sm
        from app.utils.budget import BudgetGuard, set_active_budget_guard

        proj = tmp_path / "proj"
        (proj / "code").mkdir(parents=True)
        guard = BudgetGuard(budget, repair_reserve_ratio=reserve)
        guard.record(used)
        set_active_budget_guard(guard)
        calls = {"smoke": 0, "repair": 0}

        def run_smoke(code_dir):
            calls["smoke"] += 1
            return (False, smoke_report) if smoke_report else (True, "ok")

        def auto_repair(*a, **k):
            calls["repair"] += 1
            return False, smoke_report

        monkeypatch.setattr(sm, "run_smoke", run_smoke)
        monkeypatch.setattr(sm, "run_all_fixers", lambda cd, ddl: {})
        monkeypatch.setattr(sm, "collect_ddl", lambda cd: [])
        monkeypatch.setattr(sm, "_anchor_missing", lambda cd, req: [])
        monkeypatch.setattr(sm, "auto_repair", auto_repair)
        monkeypatch.setattr(sm, "_llm_from", lambda s: (lambda *a, **k: "x"))
        monkeypatch.setattr(sm, "_journey_gate",
                            lambda *a, **k: (journey_ok, "journey 断言失败"))
        monkeypatch.setattr("app.utils.selftest_gate.selftest_gate",
                            lambda *a, **k: (False, "selftest 未过"))
        try:
            ok, report = sm.verify_delivery(proj, "做一件事", Settings(),
                                            max_verify_rounds=rounds)
        finally:
            set_active_budget_guard(None)
        return ok, report, calls

    def test_exhausted_budget_skips_repair_and_does_not_repeat_rounds(
            self, monkeypatch, tmp_path):
        ok, report, calls = self._drive(
            monkeypatch, tmp_path,
            smoke_report="AssertionError: expected 'Sprint goals' got []",
            budget=100_000, used=100_000)
        assert ok is False
        assert calls["repair"] == 0          # 一分钱都不再花
        assert calls["smoke"] == 1           # 也不再空转第二、三轮
        assert "SKIP LLM 修复" in report and "总闸已耗尽" in report

    def test_repair_fund_is_the_gate_not_the_hard_stop(self, monkeypatch,
                                                       tmp_path):
        """总闸还差一段，但保留额已被前置阶段吃掉 → 同样不假装在修。"""
        ok, report, calls = self._drive(
            monkeypatch, tmp_path,
            smoke_report="GET /api/links 500", budget=100_000, used=90_000,
            reserve=0.25)
        assert calls["repair"] == 0 and calls["smoke"] == 1
        assert "修复保留额已动用" in report

    def test_identical_smoke_failure_stops_after_second_round(
            self, monkeypatch, tmp_path):
        """有钱修但修不动：同一条失败第二次出现即收手，第三轮不再烧。"""
        ok, report, calls = self._drive(
            monkeypatch, tmp_path,
            smoke_report="AssertionError: expected 'Sprint goals' got []",
            rounds=5, budget=1_000_000, used=0)
        assert ok is False
        assert calls["repair"] == 2 and calls["smoke"] == 2
        assert "停止空转" in report

    def test_changing_failure_keeps_looping(self, monkeypatch, tmp_path):
        """反例守卫：每轮失败都在变（修复有效但没修完）→ 不许被止损掐掉。"""
        import app.arcbench_smoke as sm
        from app.utils.budget import BudgetGuard, set_active_budget_guard

        proj = tmp_path / "proj2"
        (proj / "code").mkdir(parents=True)
        set_active_budget_guard(BudgetGuard(1_000_000))
        words = ("锚点缺失", "路由未注册", "种子为空", "端口占用",
                 "模板未渲染", "静态资源丢失", "会话过期", "字段改名")
        reports = iter([f"AssertionError: {w}" for w in words])

        monkeypatch.setattr(sm, "run_smoke",
                            lambda cd: (False, next(reports)))
        monkeypatch.setattr(sm, "run_all_fixers", lambda cd, ddl: {})
        monkeypatch.setattr(sm, "collect_ddl", lambda cd: [])
        monkeypatch.setattr(sm, "_anchor_missing", lambda cd, req: [])
        monkeypatch.setattr(sm, "auto_repair",
                            lambda *a, **k: (False, next(reports)))
        monkeypatch.setattr(sm, "_llm_from", lambda s: (lambda *a, **k: "x"))
        monkeypatch.setattr(sm, "_journey_gate",
                            lambda *a, **k: (False, "journey"))
        monkeypatch.setattr("app.utils.selftest_gate.selftest_gate",
                            lambda *a, **k: (False, "selftest 未过"))
        try:
            ok, report = sm.verify_delivery(proj, "做一件事", Settings(),
                                            max_verify_rounds=3)
        finally:
            set_active_budget_guard(None)
        assert ok is False
        assert "停止空转" not in report       # 失败在变 → 三轮跑满

    def test_failure_sig_ignores_line_numbers(self):
        """keep-r1 的两次补丁报错只差行号（138/116），根因同一条。"""
        import app.arcbench_smoke as sm

        a = sm._failure_sig("invalid syntax (views.py, line 138)")
        b = sm._failure_sig("invalid syntax (views.py, line 116)")
        assert a == b
        assert sm._failure_sig("a") != sm._failure_sig("b")


class TestPrecheckMovedAhead:
    """v42-3 体检前移（批次#67）：官方口径那段判分（导出布局→起服→逐字
    事实）零 LLM、秒级，原先只在整个验收循环**之后**的自测闸里跑一次。
    sheet 两跑都死在循环中途（101.5% / 100.2% 断气），于是那把免费的眼睛
    一次都没睁开：首页是一页模块清单，10 小时无人知。"""

    def _drive(self, monkeypatch, tmp_path, *, precheck=(0, 0, [], ""),
               with_reqs=True, smoke_ok=True):
        import app.arcbench_smoke as sm
        from app.utils.budget import BudgetGuard, set_active_budget_guard

        proj = tmp_path / "proj"
        (proj / "code").mkdir(parents=True)
        set_active_budget_guard(BudgetGuard(1_000_000))
        order: list[str] = []
        seen: dict = {}

        def fake_precheck(project_dir, specs_dir, port_hint=None,
                          requirements_dir=None):
            order.append("precheck")
            seen["specs_dir"] = specs_dir
            seen["requirements_dir"] = requirements_dir
            return precheck

        def run_smoke(code_dir):
            order.append("smoke")
            return (True, "ok") if smoke_ok else (False, "GET / 404")

        def auto_repair(*a, **k):
            order.append("repair")
            seen["priority_note"] = k.get("priority_note", "")
            return True, "fixed"

        monkeypatch.setattr("app.utils.selftest_gate.run_selftests",
                            fake_precheck)
        monkeypatch.setattr(sm, "run_smoke", run_smoke)
        monkeypatch.setattr(sm, "run_all_fixers", lambda cd, ddl: {})
        monkeypatch.setattr(sm, "collect_ddl", lambda cd: [])
        monkeypatch.setattr(sm, "_anchor_missing", lambda cd, req: [])
        monkeypatch.setattr(sm, "auto_repair", auto_repair)
        monkeypatch.setattr(sm, "_llm_from", lambda s: (lambda *a, **k: "x"))
        monkeypatch.setattr(sm, "_journey_gate", lambda *a, **k: (True, ""))
        monkeypatch.setattr("app.utils.selftest_gate.selftest_gate",
                            lambda *a, **k: (True, "selftest ok"))
        reqs = (tmp_path / "requirements") if with_reqs else None
        try:
            ok, report = sm.verify_delivery(proj, "做一件事", Settings(),
                                            requirements_dir=reqs)
        finally:
            set_active_budget_guard(None)
        return ok, report, order, seen

    def test_runs_on_the_node_free_segment_before_any_repair(self, monkeypatch,
                                                             tmp_path):
        ok, report, order, seen = self._drive(
            monkeypatch, tmp_path,
            precheck=(3, 2, ["REQ-7 首页未见 'Sprint goals'"], "tail"))
        assert order[0] == "precheck" and order[1] == "smoke"
        assert seen["specs_dir"] is None, "前置体检不得碰 Playwright 段"
        assert seen["requirements_dir"] is not None
        assert "[precheck] 逐字事实 3/5 命中（缺 1）" in report

    def test_gaps_reach_the_repair_instructions(self, monkeypatch, tmp_path):
        """红字必须带 REQ id 出现在修复指令里——否则眼睛睁开了嘴没接上。"""
        ok, report, order, seen = self._drive(
            monkeypatch, tmp_path, smoke_ok=False,
            precheck=(3, 2, ["REQ-7 首页未见 'Sprint goals'",
                             "REQ-9 缺按钮 'Take a note'"], "tail"))
        assert "repair" in order
        note = seen["priority_note"]
        assert "官方口径体检缺口" in note
        assert "REQ-7 首页未见 'Sprint goals'" in note
        assert "REQ-9" in note

    def test_green_precheck_adds_nothing_to_the_note(self, monkeypatch,
                                                     tmp_path):
        ok, report, order, seen = self._drive(
            monkeypatch, tmp_path, smoke_ok=False, precheck=(5, 0, [], "tail"))
        assert "官方口径体检缺口" not in seen["priority_note"]
        assert "[precheck] 逐字事实 5/5 命中" in report

    def test_no_requirements_dir_means_no_precheck(self, monkeypatch, tmp_path):
        """无需求清单目录（无源可判）：零副作用，与 v41 行为一致。"""
        ok, report, order, seen = self._drive(
            monkeypatch, tmp_path, with_reqs=False)
        assert "precheck" not in order
        assert "[precheck] SKIP" in report

    def test_precheck_crash_never_voids_verification(self, monkeypatch,
                                                     tmp_path):
        """体检是眼睛不是闸：它自己摔了不得把已经能交付的产物换成 FAIL。"""
        import app.arcbench_smoke as sm

        def boom(*a, **k):
            raise RuntimeError("判分器内部故障")

        monkeypatch.setattr("app.utils.selftest_gate.run_selftests", boom)
        proj = tmp_path / "proj"
        (proj / "code").mkdir(parents=True)
        monkeypatch.setattr(sm, "run_smoke", lambda cd: (True, "ok"))
        monkeypatch.setattr(sm, "_anchor_missing", lambda cd, req: [])
        monkeypatch.setattr(sm, "_llm_from", lambda s: (lambda *a, **k: "x"))
        monkeypatch.setattr(sm, "_journey_gate", lambda *a, **k: (True, ""))
        monkeypatch.setattr("app.utils.selftest_gate.selftest_gate",
                            lambda *a, **k: (True, "ok"))
        ok, report = sm.verify_delivery(proj, "做一件事", Settings(),
                                        requirements_dir=tmp_path / "reqs")
        assert ok is True
        assert "异常降级" in report


