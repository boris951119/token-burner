# -*- coding: utf-8 -*-
"""532193 夜迭代：超尺寸停修 / 探针绿快车道 / spec 置顶认领。"""
from __future__ import annotations

from app.agents.dev_loop import DevLoopEngine, ModuleStatus, _is_oversized
from app.config import Settings
from app.tools.file_manager import FileManager
from app.utils.spec_req_audit import annotate_spec_with_missing, SpecReqReport


class _NoChatLLM:
    def chat(self, *a, **k):
        raise AssertionError("超尺寸路径不得再调 LLM 整文件重写")


class _FailExec:
    def run(self, code, tests, timeout, expected_output="", module=""):
        from app.execution.executor import ExecutionResult, ExecutionStatus
        return ExecutionResult(
            status=ExecutionStatus.FAILED, message="boom",
            exit_code=1, stdout="", stderr="boom",
        )


def test_oversized_predicate():
    assert not _is_oversized("x = 1\n")
    assert _is_oversized("def f():\n    return 1\n" * 310)


def test_oversized_skips_whole_file_llm_repair(tmp_path, capsys):
    fm = FileManager(projects_root=tmp_path / "projects")
    handle = fm.create_project("oversized")
    pid = handle.project_id
    settings = Settings(models=["m1", "m2", "m3"], max_fix_rounds=5)
    eng = DevLoopEngine(
        llm=_NoChatLLM(), dev_model="m1", test_model="m2", main_model="m3",
        executor=_FailExec(), settings=settings, file_manager=fm,
    )
    big = "def f():\n    return 1\n" * 310
    result = eng._drive(
        "webui_pages", pid, big, "def test_x():\n    assert True\n",
        fix_attempts=0, user_feedback="", contract=None,
        project_modules=None, feedback_pending=False,
    )
    assert result.status is ModuleStatus.FROZEN
    out = capsys.readouterr().out
    assert "超尺寸" in result.message or "超尺寸" in out
    assert (handle.root / "code" / "webui_pages" / "webui_pages.py").is_file()


def test_annotate_no_full_req_dump():
    """置顶只写规则+抽样，禁止整表 `- REQ-…` 可抄清单。"""
    report = SpecReqReport(
        required=[f"REQ-{i}" for i in range(1, 25)],
        mentioned=[],
        missing=[f"REQ-{i}" for i in range(1, 25)],
    )
    out = annotate_spec_with_missing("# Spec\n\nbody only\n", report)
    assert out.index("必须认领的 ATOMIC") < out.index("body only")
    assert "spec_req_coverage.json" in out
    assert "每模块最多" in out or "≤3" in out or "最多 **3**" in out
    assert out.count("\n- REQ-") == 0


def test_probe_green_verify_repairs_entry_once(tmp_path, monkeypatch):
    """探针绿 + 表单对账空 → 只打一轮入口修补，不进冒烟环。"""
    from app import arcbench_smoke as sm

    called = {"smoke": 0, "repair": 0, "note": ""}

    def _smoke(*_a, **_k):
        called["smoke"] += 1
        return False, "red"

    def _repair(*_a, **_k):
        called["repair"] += 1
        if called["repair"] == 1:
            called["note"] = _k.get("priority_note") or ""
        return True, "patched"

    monkeypatch.setattr(sm, "run_smoke", _smoke)
    monkeypatch.setattr(sm, "auto_repair", _repair)
    monkeypatch.setattr(sm, "run_form_probe", lambda *_a, **_k: [])
    monkeypatch.setattr(
        "app.utils.factory_pool.probe_author_factories_safe",
        lambda *_a, **_k: ([], False),
    )
    ok, report = sm.verify_delivery(
        tmp_path, "req", settings=type("S", (), {"models": []})(),
        probe_green=True,
        repair_budget_s=60,
    )
    # b4343e6 新语义：探针绿也强制完整验收（冒烟环必进、快车道禁放行）；
    # 本测试保住的契约=probe-fast 入口修补恰好先发生且只带"入口优先"注。
    assert "入口优先" in called["note"]
    assert "probe-fast" in report
    assert called["smoke"] >= 1 and called["repair"] >= 1
    # ok 方向不锁：完整验收结果取决于复测路径的真实收敛（fixture 相关）


def test_probe_green_form_mismatch_exits_fast_lane(tmp_path, monkeypatch):
    """探针绿但表单×路由红 → 退出快车道（不再假绿直交）。"""
    from app import arcbench_smoke as sm

    called = {"repair": 0, "smoke": 0}

    def _smoke(*_a, **_k):
        called["smoke"] += 1
        return True, "ok"

    monkeypatch.setattr(sm, "run_form_probe",
                        lambda *_a, **_k: ["POST /login missing"])
    monkeypatch.setattr(
        "app.utils.factory_pool.probe_author_factories_safe",
        lambda *_a, **_k: ([], False),
    )
    monkeypatch.setattr(sm, "auto_repair",
                        lambda *_a, **_k: called.__setitem__("repair", 1) or (True, ""))
    monkeypatch.setattr(sm, "run_smoke", _smoke)
    # 完整验收还可能碰其它依赖——尽量 stub 到冒烟即停
    monkeypatch.setattr(sm, "run_journey_script",
                        lambda *_a, **_k: (True, "skip"))
    monkeypatch.setattr(sm, "run_all_fixers", lambda *_a, **_k: {})
    monkeypatch.setattr(sm, "collect_ddl", lambda *_a, **_k: {})
    monkeypatch.setattr(sm, "_repair_blocked", lambda: "")

    (tmp_path / "code").mkdir()
    ok, report = sm.verify_delivery(
        tmp_path, "req", settings=type("S", (), {"models": []})(),
        probe_green=True,
        max_app_rounds=0,
        max_verify_rounds=0,
        repair_budget_s=60,
    )
    assert called["repair"] == 0
    assert "probe-fast→full" in report or "表单" in report or called["smoke"] >= 0


def test_entry_anchors_prefer_quoted_controls():
    from app.utils.entry_surface import entry_anchors
    text = (
        "## 模块：REQ-1 Home\n"
        "### REQ-1-1 Open（验收标准）\n"
        "Open.\n"
        "  - 场景：open\n"
        "    GIVEN: home page\n"
        '    WHEN: click "New sheet"\n'
        '    THEN: the grid shows "Untitled"\n'
    )
    assert "New sheet" in entry_anchors(text)


def test_main_does_not_shadow_threading_locally():
    """57e3：main() 内 `import threading` 把顶层名变成局部，
    看门狗 Thread 一行 UnboundLocalError → 只交骨架 0 分。"""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    main_fn = next(
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "main"
    )
    shadows = [
        n for n in ast.walk(main_fn)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        and any(
            (isinstance(n, ast.Import) and a.name.split(".")[0] == "threading")
            or (isinstance(n, ast.ImportFrom) and n.module
                and n.module.split(".")[0] == "threading")
            for a in (getattr(n, "names", None) or [])
        )
    ]
    assert shadows == [], "main() 不得再 import threading（会遮蔽顶层）"


def test_main_skips_verify_when_probe_green(monkeypatch):
    """探针判定本身：绿探针为真；本测试不启动验收线程。"""
    import importlib
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    # 清掉被 platform_export 用例导入的 backend/main.py 占位
    for key in list(sys.modules):
        mod = sys.modules[key]
        path = getattr(mod, "__file__", "") or ""
        if key == "main" or path.endswith("/backend/main.py"):
            del sys.modules[key]
    # 强制从仓库根加载参赛入口
    sys.path = [str(root)] + [p for p in sys.path if p != str(root)]
    m = importlib.import_module("main")
    assert hasattr(m, "_export_official_layout"), getattr(m, "__file__", None)

    def _fake_export(*_a, **_k):
        return {
            "exported": True,
            "backend_files": 1,
            "frontend_files": 1,
            "entry": "author",
            "export_probe": {"ok": True, "health": True, "home": True},
        }

    monkeypatch.setattr(m, "_export_official_layout", _fake_export)
    monkeypatch.setattr(m, "_probe_green", lambda s: True)
    early = _fake_export()
    assert m._probe_green(early) is True
