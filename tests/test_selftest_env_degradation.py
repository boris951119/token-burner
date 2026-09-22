# -*- coding: utf-8 -*-
"""自测闸环境退化（9/23 Linux 全真演练取证）：交付容器无 node。

旧实现两处亏损，同因不同层：
① specs 生成先烧 LLM token，跑它却需要 node——缺 node 时生成完才在
   lint/运行处抛 FileNotFoundError，被上层 except 静默降级；
② 连带的 node-free 段（导出布局→起服→健康探针→零 LLM 编译判分）
   一起报废，而"布局违约""起服死亡"两大死因从来不依赖 node。
"""
from pathlib import Path

import pytest

import app.utils.selftest_gate as sg

NO_NODE = "环境无 npx（node 未安装）"


@pytest.fixture(autouse=True)
def _reset_probe():
    sg._node_probe = None
    yield
    sg._node_probe = None


def test_probe_reports_missing_node(monkeypatch):
    monkeypatch.setattr(sg.shutil, "which", lambda _name: None)
    assert "npx" in sg.node_unavailable_reason()


def test_probe_is_cached(monkeypatch):
    calls = []

    def fake_run(*a, **k):
        calls.append(1)
        raise RuntimeError("boom")

    monkeypatch.setattr(sg.shutil, "which", lambda _name: "/usr/bin/npx")
    monkeypatch.setattr(sg.subprocess, "run", fake_run)
    first = sg.node_unavailable_reason()
    assert "playwright 探测失败" in first
    assert sg.node_unavailable_reason() == first
    assert len(calls) == 1, "探测必须进程内只跑一次"


def test_gate_skips_generation_but_still_judges(tmp_path, monkeypatch):
    """无 node：不花一分 token 生成 specs，但 node-free 判分段照跑。"""
    seen = {}

    def boom(*a, **k):
        raise AssertionError("无 node 环境不得进入 specs 生成（烧 token）")

    def fake_run_selftests(project_dir, specs_dir, requirements_dir=None):
        seen["specs_dir"] = specs_dir
        return 5, 0, [], "tail"

    monkeypatch.setenv("ARCBENCH_SELFTEST", "on")  # conftest 默认 off
    monkeypatch.setattr(sg, "node_unavailable_reason", lambda: NO_NODE)
    monkeypatch.setattr(sg, "ensure_selftests", boom)
    monkeypatch.setattr(sg, "run_selftests", fake_run_selftests)
    ok, report = sg.selftest_gate(tmp_path, "需求原文", settings=None)
    assert ok is True, "判分全过即放行（与 node 无关）"
    assert seen["specs_dir"] is None


def test_generation_failure_no_longer_voids_the_gate(tmp_path, monkeypatch):
    """specs 全批生成失败：旧实现直接 return 报废整闸；新实现仍跑
    判分段（此处零信号 → FAIL 但不跳过起服检查）。"""
    seen = {}

    def fake_run_selftests(project_dir, specs_dir, requirements_dir=None):
        seen["specs_dir"] = specs_dir
        return 0, 0, [], ""

    monkeypatch.setenv("ARCBENCH_SELFTEST", "on")
    monkeypatch.setattr(sg, "node_unavailable_reason", lambda: "")
    monkeypatch.setattr(sg, "ensure_selftests", lambda *a, **k: None)
    monkeypatch.setattr(sg, "run_selftests", fake_run_selftests)
    ok, report = sg.selftest_gate(tmp_path, "需求", settings=None)
    assert ok is False
    assert seen["specs_dir"] is None
    assert "零信号" in report


def test_env_off_switch_still_first(tmp_path, monkeypatch):
    """ARCBENCH_SELFTEST=off 的关闭语义优先于环境探测（测试环境约定）。"""
    monkeypatch.setenv("ARCBENCH_SELFTEST", "off")
    monkeypatch.setattr(sg, "node_unavailable_reason",
                        lambda: (_ for _ in ()).throw(AssertionError))
    ok, report = sg.selftest_gate(tmp_path, "需求", settings=None)
    assert ok is False and "关闭" in report


# ---- run_selftests 的无 Playwright 分支：起服+判分段与 node 无关 ----

class _FakeProc:
    pid = 4242

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def _stub_server(monkeypatch, tmp_path):
    import app.platform_export as pe

    def fake_export(out_dir, project_dir):
        (out_dir / "backend").mkdir(parents=True, exist_ok=True)
        (out_dir / "backend" / "main.py").write_text("pass", encoding="utf-8")
        return {"backend_files": 1, "frontend_files": 0}

    monkeypatch.setattr(pe, "export_platform_layout", fake_export)
    monkeypatch.setattr(sg, "_free_port", lambda prefer: 39999)
    monkeypatch.setattr(sg.subprocess, "Popen",
                        lambda *a, **k: _FakeProc())
    monkeypatch.setattr(sg, "_wait_health", lambda url, deadline_s=90: True)


def test_run_selftests_without_specs_still_starts_server(tmp_path, monkeypatch):
    """无 specs（环境缺 node）：起服/健康探针/编译判分段照常产出信号。"""
    _stub_server(monkeypatch, tmp_path)
    passed, failed, failures, tail = sg.run_selftests(tmp_path, None)
    assert (passed, failed, failures) == (0, 0, [])
    assert "SKIP" in tail


def test_empty_specs_dir_is_zero_signal_not_a_pass(tmp_path, monkeypatch):
    """specs 目录存在但被 lint 全数剔除：零信号必须记 FAIL，
    不得被无 Playwright 分支的"降级放行"掩盖（9/20 真空真值回归）。"""
    _stub_server(monkeypatch, tmp_path)
    specs = tmp_path / "selftest"
    specs.mkdir()
    passed, failed, failures, tail = sg.run_selftests(tmp_path, specs)
    assert failed == 1 and "零收集" in failures[0]


def test_boot_death_is_counted_and_carries_traceback(tmp_path, monkeypatch):
    """起服即死（平台 0 分头号死因）：计数必须为 1（否则闸口按零信号
    报废、修复环拿不到），且后端 traceback 必须随失败串进入修复指令
    （旧实现 stdout/stderr 进 DEVNULL，只剩一句无信息量的超时）。"""
    import app.platform_export as pe

    def fake_export(out_dir, project_dir):
        (out_dir / "backend").mkdir(parents=True, exist_ok=True)
        (out_dir / "backend" / "main.py").write_text("pass", encoding="utf-8")
        return {"backend_files": 1, "frontend_files": 0}

    class _DyingProc:
        pid = 4343

        def __init__(self, *a, **k):
            k["stdout"].write("ModuleNotFoundError: no module named 'notes'")

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(pe, "export_platform_layout", fake_export)
    monkeypatch.setattr(sg, "_free_port", lambda prefer: 39998)
    monkeypatch.setattr(sg.subprocess, "Popen", _DyingProc)
    monkeypatch.setattr(sg, "_wait_health", lambda url, deadline_s=90: False)
    passed, failed, failures, tail = sg.run_selftests(tmp_path, None)
    assert (passed, failed) == (0, 1)
    assert "ModuleNotFoundError" in failures[0], "死因必须进修复指令"


def test_relative_project_dir_still_launches_absolute(tmp_path, monkeypatch,
                                                     tmp_path_factory):
    """project_dir 相对路径下，起服脚本路径曾被 cwd 二次拼接
    （`backend/<相对 project_dir>/backend/main.py`）→ 健康探针必然超时，
    而失败原因看起来像"应用起不来"——假红会白白烧掉修复轮。"""
    import app.platform_export as pe

    captured = {}

    class _NoopProc:
        pid = 4444

        def __init__(self, argv, *a, **k):
            captured["argv"] = list(argv)
            k["stdout"].write("booted")

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    def fake_export(out_dir, project_dir):
        (out_dir / "backend").mkdir(parents=True, exist_ok=True)
        (out_dir / "backend" / "main.py").write_text("pass", encoding="utf-8")
        return {"backend_files": 1, "frontend_files": 0}

    root = tmp_path_factory.mktemp("relroot")
    monkeypatch.chdir(root)
    (root / "proj").mkdir()
    monkeypatch.setattr(pe, "export_platform_layout", fake_export)
    monkeypatch.setattr(sg, "_free_port", lambda prefer: 39997)
    monkeypatch.setattr(sg.subprocess, "Popen", _NoopProc)
    monkeypatch.setattr(sg, "_wait_health", lambda url, deadline_s=90: True)
    sg.run_selftests(Path("proj"), None)
    assert Path(captured["argv"][1]).is_absolute(), captured["argv"]

