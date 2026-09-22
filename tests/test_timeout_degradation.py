# -*- coding: utf-8 -*-
"""守护工具自身的 subprocess 熔断：降级成"一条失败信号"，不许上抛。

三处同因（2026-09-23 AST 扫描定位）：冒烟 verify / lint --list /
playwright 全量跑的 subprocess.run 都带 timeout，但旧实现裸调用——
TimeoutExpired 一路上抛会吃掉比超时大得多的东西：
① run_smoke 的超时穿过 verify_delivery 冒烟段（该段无 try），把已经
   写完的项目换成一次崩溃退出（退出码 1 = 平台不评分）；
② lint_specs 一次 npx 卡死作废整道自测闸，且"判不动"被误当"spec 坏"
   的证据；
③ run_selftests 的 playwright 超时让调用方只记一句"异常"，修复环拿不
   到"有旅程用例挂起"这条本可定向修复的信号。
"""
import subprocess
from pathlib import Path

import pytest

import app.arcbench_smoke as smoke
import app.utils.selftest_gate as sg
from tests.test_selftest_env_degradation import _stub_server

SPEC = (
    "import { test, expect } from '@playwright/test';\n"
    "test('home shows title', async ({ page }) => {\n"
    "  await page.goto('/');\n"
    "});\n"
)


# ---- run_smoke：导入即挂起的应用 ----

def test_smoke_timeout_is_a_failure_not_a_crash(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(["python", "verify.py"], 180)

    monkeypatch.setattr(smoke.subprocess, "run", boom)
    ok, report = smoke.run_smoke(tmp_path)
    assert ok is False
    assert "冒烟验证超时" in report
    # 修复提示词直接读这条失败串：必须给出可行动成因，不能只有 TIMEOUT
    assert "import 而不阻塞" in report


def test_smoke_launch_failure_is_a_failure(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(smoke.subprocess, "run", boom)
    ok, report = smoke.run_smoke(tmp_path)
    assert ok is False and "启动失败" in report


# ---- lint_specs：npx 卡死不得被当成坏 spec ----

@pytest.mark.parametrize("exc", [
    subprocess.TimeoutExpired(["npx", "playwright"], 180),
    OSError(12, "Cannot allocate memory"),
])
def test_lint_timeout_keeps_every_spec(tmp_path, monkeypatch, exc):
    monkeypatch.setattr(sg.shutil, "which", lambda _name: "/usr/bin/npx")

    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(sg.subprocess, "run", boom)
    specs = tmp_path / "selftest"
    specs.mkdir()
    for name in ("a.spec.ts", "b.spec.ts"):
        (specs / name).write_text(SPEC, encoding="utf-8")
    assert lint_survivors(specs, tmp_path) == 2
    assert (specs / "a.spec.ts").is_file() and (specs / "b.spec.ts").is_file()
    assert not (tmp_path / "selftest_rejected").exists()


def lint_survivors(specs: Path, project_dir: Path) -> int:
    return sg.lint_specs(specs, project_dir)


def test_lint_timeout_only_shields_the_stuck_spec(tmp_path, monkeypatch):
    """逐文件 --list：第一个卡死只保住它自己，后面的坏 spec 照旧剔除。"""
    monkeypatch.setattr(sg.shutil, "which", lambda _name: "/usr/bin/npx")
    calls = []

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "SyntaxError: bad spec"

    def run(*a, **k):
        calls.append(a[0][-2])
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(a[0], 180)
        return _Proc()

    monkeypatch.setattr(sg.subprocess, "run", run)
    specs = tmp_path / "selftest"
    specs.mkdir()
    (specs / "a.spec.ts").write_text(SPEC, encoding="utf-8")
    (specs / "b.spec.ts").write_text("broken <<<>>>\n", encoding="utf-8")
    assert sg.lint_specs(specs, tmp_path) == 1
    assert (specs / "a.spec.ts").is_file()
    assert (tmp_path / "selftest_rejected" / "b.spec.ts").is_file()


# ---- run_selftests：playwright 挂起要给修复环留话 ----

def _stub_playwright(monkeypatch, tmp_path, exc):
    _stub_server(monkeypatch, tmp_path)
    specs = tmp_path / "selftest"
    specs.mkdir()
    (specs / "journey.spec.ts").write_text(SPEC, encoding="utf-8")

    def run(*a, **k):
        raise exc

    monkeypatch.setattr(sg.subprocess, "run", run)
    return specs


def test_selftest_timeout_counts_as_one_failure(tmp_path, monkeypatch):
    exc = subprocess.TimeoutExpired(["npx", "playwright", "test"], 1800)
    specs = _stub_playwright(monkeypatch, tmp_path, exc)
    passed, failed, failures, tail = sg.run_selftests(tmp_path, specs)
    assert (passed, failed) == (0, 1)
    assert "自测执行超时（1800s 熔断）" in failures[0]
    assert "TIMEOUT 1800s" in tail


def test_selftest_launch_failure_counts_as_one_failure(tmp_path, monkeypatch):
    specs = _stub_playwright(monkeypatch, tmp_path, FileNotFoundError(
        2, "npx"))
    passed, failed, failures, tail = sg.run_selftests(tmp_path, specs)
    assert (passed, failed) == (0, 1)
    assert "playwright 启动失败" in failures[0]


def test_selftest_timeout_carries_compiled_failures(tmp_path, monkeypatch):
    """超时不得吃掉零 LLM 编译判分已攒下的失败（同清单进修复环）。"""
    import app.utils.acceptance_judge as aj

    specs = _stub_playwright(
        monkeypatch, tmp_path,
        subprocess.TimeoutExpired(["npx", "playwright", "test"], 1800))

    def fake_judge(requirements_dir, base_url):
        return {"passed": 3, "failures": ["REQ-2 列表为空"]}

    monkeypatch.setattr(aj, "judge_requirements", fake_judge)
    reqs = tmp_path / "requirements"
    reqs.mkdir()
    passed, failed, failures, tail = sg.run_selftests(
        tmp_path, specs, requirements_dir=reqs)
    assert (passed, failed) == (3, 2)
    assert failures[0].startswith("自测执行超时")
    assert "REQ-2 列表为空" in failures
