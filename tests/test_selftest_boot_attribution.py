# -*- coding: utf-8 -*-
"""编译判分红字的死因归因（runA 交付取证）。

runA 的 .selftest_template_*/backend-boot.log 第 10/42 行留着真死因：
首页 render_template_string 引了没写过的 base.html →
jinja2.exceptions.TemplateNotFound: base.html → 500。可这条 traceback
只有健康探针超时分支会被读，探针通过后的页面级崩溃一概不认——修复环
于是只拿到「首页必须 200 且渲染真实内容」这条泛化指令，白烧一轮。
"""
import pytest

import app.utils.selftest_gate as sg

RUNA_TAIL = (
    "127.0.0.1 - - [23/Sep/2026 07:59:05] \"GET /api/health HTTP/1.1\" 200 -\n"
    "[2026-09-23 07:59:06,014] ERROR in app: Exception on / [GET]\n"
    "Traceback (most recent call last):\n"
    "  File \"/usr/local/lib/python3.11/site-packages/flask/app.py\", line 902,"
    " in dispatch_request\n"
    "    return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)\n"
    "    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n"
    "  File \"backend/link_creation/__init__.py\", line 148, in index\n"
    "    return render_template_string(_INDEX_HTML)\n"
    "           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n"
    "  File \"site-packages/flask/templating.py\", line 100, in _get_source_fast\n"
    "    raise TemplateNotFound(template)\n"
    "jinja2.exceptions.TemplateNotFound: base.html\n"
    "127.0.0.1 - - [23/Sep/2026 07:59:06] \"GET / HTTP/1.1\" 500 -\n")


# ---- _boot_exception：只认 traceback 的收尾行 ----

def test_runa_traceback_yields_exception_line(tmp_path):
    log = tmp_path / "backend-boot.log"
    log.write_text(RUNA_TAIL, encoding="utf-8")
    assert sg._boot_exception(log) == "jinja2.exceptions.TemplateNotFound: base.html"


def test_no_traceback_marker_means_no_attribution(tmp_path):
    """顶格的异常样文字不算数：没有 traceback 头就可能是在行日志里翻旧账，
    归因错了比不归因更坏（宁缺勿误）。"""
    log = tmp_path / "backend-boot.log"
    log.write_text('WARNING: this is a development server\n'
                   'KeyError: stale-line-from-an-earlier-run\n', encoding="utf-8")
    assert sg._boot_exception(log) == ""


def test_last_traceback_wins(tmp_path):
    """多轮请求各自崩溃时，报最新那一条——探针通过后的崩溃必然出自本轮。"""
    log = tmp_path / "backend-boot.log"
    log.write_text("Traceback (most recent call last):\n"
                   "    old\n"
                   "KeyError: 'first'\n"
                   "Traceback (most recent call last):\n"
                   "    new\n"
                   "TypeError: unsupported operand\n", encoding="utf-8")
    assert sg._boot_exception(log) == "TypeError: unsupported operand"


def test_indented_source_echo_not_matched(tmp_path):
    """源码回显行（含 `x: int = 5` 这类形态）缩进在 traceback 里，不得当成异常行。"""
    log = tmp_path / "backend-boot.log"
    log.write_text("Traceback (most recent call last):\n"
                   "    x: int = 5\n"
                   "  File \"a.py\", line 1, in f\n"
                   "ValueError: bad\n", encoding="utf-8")
    assert sg._boot_exception(log) == "ValueError: bad"


def test_missing_log_attribution_is_empty(tmp_path):
    assert sg._boot_exception(tmp_path / "nope.log") == ""


def test_long_exception_line_truncated(tmp_path):
    log = tmp_path / "backend-boot.log"
    log.write_text("Traceback (most recent call last):\n"
                   "RuntimeError: " + "x" * 900 + "\n", encoding="utf-8")
    got = sg._boot_exception(log)
    assert len(got) == 240 and got.startswith("RuntimeError: xxx")


# ---- run_selftests：红字带上死因，计数不动 ----

class _CrashOnPageProc:
    """子进程把 runA 形状的 traceback 写进继承的 stdout 句柄。"""

    pid = 4545

    def __init__(self, *a, **k):
        k["stdout"].write(RUNA_TAIL)
        k["stdout"].flush()

    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


@pytest.fixture
def _live_server(monkeypatch, tmp_path):
    import app.platform_export as pe
    import app.utils.acceptance_judge as aj

    def fake_export(out_dir, project_dir):
        (out_dir / "backend").mkdir(parents=True, exist_ok=True)
        (out_dir / "backend" / "main.py").write_text("pass", encoding="utf-8")
        return {"backend_files": 1, "frontend_files": 0}

    monkeypatch.setattr(pe, "export_platform_layout", fake_export)
    monkeypatch.setattr(sg, "_free_port", lambda prefer: 39997)
    monkeypatch.setattr(sg.subprocess, "Popen", _CrashOnPageProc)
    monkeypatch.setattr(sg, "_wait_health",
                        lambda url, deadline_s=60, proc=None: True)
    monkeypatch.setattr(
        aj, "judge_requirements",
        lambda requirements_dir, base_url, **kw: {
            "passed": 0, "nodes": 4, "total": 1,
            "failures": ["REQ-1.1 首页 / 必须 200 且渲染真实内容"]})
    return tmp_path


def test_compiled_red_carries_backend_exception(_live_server):
    passed, failed, failures, tail = sg.run_selftests(
        _live_server, None, requirements_dir=_live_server)
    assert (passed, failed) == (0, 1), "归因不得改判分计数"
    assert len(failures) == 1, "追加而非新增条目：不虚红"
    assert failures[0].startswith("REQ-1.1"), "定向前缀必须保留"
    assert "jinja2.exceptions.TemplateNotFound: base.html" in failures[0]


def test_no_traceback_leaves_red_untouched(_live_server, monkeypatch):
    """干净日志不编造死因：红字原样交给修复环。"""
    class _QuietProc(_CrashOnPageProc):
        def __init__(self, *a, **k):
            k["stdout"].write(" * Running on http://127.0.0.1:3411\n")
            k["stdout"].flush()

    monkeypatch.setattr(sg.subprocess, "Popen", _QuietProc)
    _, _, failures, _ = sg.run_selftests(
        _live_server, None, requirements_dir=_live_server)
    assert failures == ["REQ-1.1 首页 / 必须 200 且渲染真实内容"]


def test_all_green_gets_no_exception_noise(_live_server, monkeypatch):
    """判分全绿时即使日志里有 traceback 也不凭空造红字。"""
    import app.utils.acceptance_judge as aj

    monkeypatch.setattr(aj, "judge_requirements",
                        lambda *a, **kw: {"passed": 3, "failures": [],
                                          "nodes": 4, "total": 3})
    passed, failed, failures, _ = sg.run_selftests(
        _live_server, None, requirements_dir=_live_server)
    assert (passed, failed, failures) == (3, 0, [])
