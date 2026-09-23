# -*- coding: utf-8 -*-
"""判分工作区必须随包走（批次#32）。

死因（2026-09-23 包清单核对）：GRADE_DIR 写死在 scripts/official_grade，
而 scripts/ 从来不在提交包里（build_submission 白名单只认 app/ 等根条目）。
官方容器里那是一条不存在的路径 → node_unavailable_reason() 的 cwd 抛
FileNotFoundError → 最强的一层行为验收在真实判分时结构性缺席，且本地
1600 例测试全绿（它们跑的是开发目录）。
"""
from pathlib import Path

import pytest

import app.utils.selftest_gate as sg
from scripts.build_submission import ALLOW_ROOT, _denied


class _R:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


@pytest.fixture(autouse=True)
def _reset_probes(tmp_path, monkeypatch):
    sg._node_probe = None
    sg._npm_root_cache = None
    monkeypatch.setattr(sg, "GRADE_DIR", tmp_path / "grade")
    (tmp_path / "grade").mkdir()
    yield
    sg._node_probe = None
    sg._npm_root_cache = None


def _fake_run(calls, *, npm_install=None):
    def run(cmd, *a, **k):
        calls.append([str(c) for c in cmd])
        joined = " ".join(str(c) for c in cmd)
        if "playwright --version" in joined:
            return _R(0, "Version 1.57.0")
        if "root -g" in joined:
            return _R(0, "")
        if "install" in joined and npm_install is not None:
            npm_install()
            return _R(0 if not isinstance(npm_install, Exception) else 1)
        return _R(0)
    return run


def _make_module(base: Path) -> Path:
    d = base / "@playwright" / "test"
    d.parent.mkdir(parents=True, exist_ok=True)
    d.mkdir()
    return base


# ---------- 目录解析：开发目录优先，随包目录兜底 ----------

def test_dev_dir_wins_when_present(tmp_path, monkeypatch):
    dev = tmp_path / "dev-grade"
    dev.mkdir()
    (dev / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sg, "_DEV_GRADE_DIR", dev)
    assert sg._resolve_grade_dir() == dev


def test_falls_back_to_bundled_workspace(tmp_path, monkeypatch):
    """开发目录不在（=提交包里的形态）时必须落到 app/ 内部的工作区。"""
    monkeypatch.setattr(sg, "_DEV_GRADE_DIR", tmp_path / "nope")
    assert sg._resolve_grade_dir() == sg._BUNDLED_GRADE_DIR


def test_bundled_workspace_is_ship_shape():
    """随包工作区两件套必须在位，且过得了打包器的禁令。"""
    ws = sg._BUNDLED_GRADE_DIR
    assert (ws / "package.json").is_file()
    assert (ws / "playwright.config.ts").is_file()
    for f in ("package.json", "playwright.config.ts"):
        rel = ws.joinpath(f).relative_to(sg.Path(__file__).resolve().parents[1]).as_posix()
        assert rel.split("/")[0] in ALLOW_ROOT, rel
        assert _denied(rel) is None, rel


def test_bundled_config_reads_same_knobs_as_gate():
    """两住所的 config 必须读同一批环境变量：漏一个 knob，自测轮就拿
    不到目标地址/报告路径，而这类错只有真跑才看得见。"""
    cfg = (sg._BUNDLED_GRADE_DIR / "playwright.config.ts").read_text(encoding="utf-8")
    for knob in ("PLAYWRIGHT_TEST_DIR", "PLAYWRIGHT_ACTION_TIMEOUT",
                 "PLAYWRIGHT_NAVIGATION_TIMEOUT", "GRADE_REPORT",
                 "TARGET_URL", "PLAYWRIGHT_OUTPUT_DIR"):
        assert knob in cfg, knob
    assert "process.env.PLAYWRIGHT_ACTION_TIMEOUT || 0" in cfg
    assert "workers: 1" in cfg and "retries: 0" in cfg


def test_bundled_workspace_carries_no_official_task_names():
    """合规红线同样适用于随包素材。"""
    blob = ""
    for f in ("package.json", "playwright.config.ts"):
        blob += (sg._BUNDLED_GRADE_DIR / f).read_text(encoding="utf-8").lower()
    for w in ("bookstack", "keep", "stackoverflow", "take a note",
              "arc-bench", "agentic-requirement-compiler", "code-philia"):
        assert w not in blob, w


# ---------- 模块就位：三级兜底 ----------

def test_probe_ready_when_module_already_installed(monkeypatch):
    calls = []
    monkeypatch.setattr(sg.shutil, "which", lambda n: "/usr/bin/" + n)
    monkeypatch.setattr(sg.subprocess, "run", _fake_run(calls))
    _make_module(sg.GRADE_DIR / "node_modules")
    assert sg.node_unavailable_reason() == ""
    assert len(calls) == 1, "本地已装时一格网络都不该碰"


def test_probe_links_global_install_without_network(tmp_path, monkeypatch):
    """随包工作区里没有 node_modules，但镜像全局装了 playwright：
    软链过去即可，一次 npm 都不必跑。"""
    calls = []
    global_root = _make_module(tmp_path / "lib" / "node_modules")
    monkeypatch.setattr(sg.shutil, "which", lambda n: "/usr/local/bin/" + n)
    monkeypatch.setattr(sg.subprocess, "run", _fake_run(calls))
    monkeypatch.setattr(sg, "_global_module_roots", lambda _npx: [global_root])
    assert sg.node_unavailable_reason() == ""
    assert len(calls) == 1, "命中推算出的全局根时不必问 npm root -g"
    assert (sg.GRADE_DIR / "node_modules" / "@playwright" / "test").is_dir()


def test_probe_asks_npm_when_paths_miss(tmp_path, monkeypatch):
    """homebrew/nvm 布局各异——推算全空时 npm root -g 是权威答案。"""
    calls = []
    root = _make_module(tmp_path / "npm" / "globals")
    monkeypatch.setattr(sg.shutil, "which", lambda n: "/usr/local/bin/" + n)
    monkeypatch.setattr(sg, "_global_module_roots", lambda _npx: [])
    monkeypatch.setattr(sg.subprocess, "run", _fake_run(calls))
    monkeypatch.setattr(sg, "_npm_global_root", lambda: str(root))
    assert sg.node_unavailable_reason() == ""
    assert (sg.GRADE_DIR / "node_modules").is_dir()


def test_probe_installs_deps_once(tmp_path, monkeypatch):
    """前两级全空（干净容器）：npm install 兜底，成功即绿。"""
    calls = []
    nm = sg.GRADE_DIR / "node_modules"

    def install():
        _make_module(nm)

    monkeypatch.setattr(sg.shutil, "which", lambda n: "/usr/local/bin/" + n)
    monkeypatch.setattr(sg, "_global_module_roots", lambda _npx: [])
    monkeypatch.setattr(sg.subprocess, "run", _fake_run(calls, npm_install=install))
    assert sg.node_unavailable_reason() == ""
    installs = [c for c in calls if "install" in " ".join(c)]
    assert len(installs) == 1
    blob = " ".join(installs[0])
    assert "--no-save" in blob
    assert "@playwright/test@1.57.0" in blob, "必须钉到 CLI 报出的版本（浏览器同版本）"
    sg.node_unavailable_reason()
    assert sum(1 for c in calls if "install" in " ".join(c)) == 1, "只兜一次"


def test_probe_reports_failed_install(tmp_path, monkeypatch):
    """装不上必须说清楚是哪一档死的：一句「playwright 探测失败」会把
    随包工作区缺失与镜像无 node 混成同一种噪音。"""
    calls = []
    monkeypatch.setattr(sg.shutil, "which", lambda n: "/usr/local/bin/" + n)
    monkeypatch.setattr(sg, "_global_module_roots", lambda _npx: [])
    monkeypatch.setattr(sg.subprocess, "run", _fake_run(calls, npm_install=lambda: None))
    reason = sg.node_unavailable_reason()
    assert "@playwright/test" in reason
    assert "npm" not in reason or "安装失败" in reason


def test_probe_without_npm_reports_module_gap(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(sg.shutil,
                        "which",
                        lambda n: None if n.startswith("npm") else "/usr/local/bin/npx")
    monkeypatch.setattr(sg.subprocess, "run", _fake_run(calls))
    monkeypatch.setattr(sg, "_global_module_roots", lambda _npx: [])
    reason = sg.node_unavailable_reason()
    assert "@playwright/test" in reason and "无 npm" in reason


def test_npm_root_query_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(sg.shutil, "which", lambda n: "/usr/local/bin/" + n)
    monkeypatch.setattr(sg.subprocess, "run", _fake_run(calls))
    assert sg._npm_global_root() == ""
    assert sg._npm_global_root() == ""
    assert len([c for c in calls if "root -g" in " ".join(c)]) == 1
