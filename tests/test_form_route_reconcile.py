# -*- coding: utf-8 -*-
"""批次#43 回归：DOM 表单动作 × 路由表对账（写路径冒烟）。

取证（9/23 免费活服探针，40 份已知交付，零 LLM）：能装配的 24 份里 4 份有
「一点就死」的表单，且这 4 份当日冒烟全绿——2 份 action 指向路由表里不存在
的路径（浏览器提交即 404），2 份提交 500（一个把存储层指向 0 字节的空库、
种子数据在另一个 .db 里；一个查询写了表里没有的列）。
盲区成因：冒烟只做无参 GET，旅程脚本按「路由表」生成请求——表里没有的路径
它根本不会去试，而官方评测是 DOM 驱动（在页面上填字段点提交）。
"""
from __future__ import annotations

import pathlib
import sqlite3
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.arcbench_smoke import (  # noqa: E402
    FORM_TIMEOUT,
    SMOKE_TIMEOUT,
    _form_script,
    run_form_probe,
    run_smoke,
    write_gate_scripts,
)


def _write(p, s):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8", newline="\n")


def _app_src(home_body: str, extra_routes: str = "") -> str:
    """健康闸＋合规首页入口＋带定位通道的输入框全配齐：
    用例只想验表单对账这一条，别的判据必须保持绿。"""
    return (
        "from flask import Flask, request, jsonify\n"
        "def create_app():\n"
        "    app = Flask(__name__)\n"
        "    @app.route('/api/health')\n"
        "    def h():\n        return jsonify(status='ok')\n"
        "    @app.route('/')\n"
        f"    def home():\n        return {home_body!r}\n"
        + extra_routes
        + "    return app\n"
    )


def _code(root, app_src: str):
    """写出一份可被冒烟装配的最小交付目录（模块名沿用仓库既有约定）。"""
    code = root / "code"
    _write(code / "app_mod" / "__init__.py",
           "from app_mod.app_mod import *  # noqa: F401,F403\n")
    _write(code / "app_mod" / "app_mod.py", app_src)
    return code


def _run(tmp_path, app_src: str):
    return run_smoke(_code(tmp_path, app_src))


_FORM = ("<a href='/x'>X</a>"
         "<form action='{path}' method='{verb}'>"
         "<input name='title' placeholder='Title'>"
         "<input type='submit' value='Save'></form>")


# 真会写库的交付：POST 入库 + 自带 app.db（副本沙箱的反证对象）
_DB_APP_SRC = (
    "import sqlite3\n"
    "from flask import Flask, request, jsonify\n"
    "def create_app():\n"
    "    app = Flask(__name__)\n"
    "    conn = sqlite3.connect('app.db')\n"
    "    conn.execute('CREATE TABLE IF NOT EXISTS books"
    " (id INTEGER PRIMARY KEY, title TEXT)')\n"
    "    conn.commit()\n    conn.close()\n"
    "    @app.route('/api/health')\n"
    "    def h():\n        return jsonify(status='ok')\n"
    "    @app.route('/')\n"
    "    def home():\n        return \"<a href='/x'>X</a>"
    "<form action='/books' method='post'>"
    "<input name='title' placeholder='Title'></form>\"\n"
    "    @app.route('/books', methods=['POST'])\n"
    "    def add():\n"
    "        conn = sqlite3.connect('app.db')\n"
    "        conn.execute('INSERT INTO books (title) VALUES (?)',\n"
    "                       (request.form.get('title', ''),))\n"
    "        conn.commit()\n        conn.close()\n        return 'ok'\n"
    "    return app\n"
)


class TestFormActionRouteReconcile:
    def test_dead_get_action_fails_smoke(self, tmp_path):
        """GET /notes 不在路由表里：提交即 404，而 GET 冒烟看不见任何异常。"""
        ok, report = _run(tmp_path, _app_src(_FORM.format(path="/notes", verb="get")))
        assert not ok, "指向不存在路径的表单必须拦下"
        assert "路由表里没有这条" in report, report
        assert "404" in report and "/notes" in report, report

    def test_method_not_registered_reports_405(self, tmp_path):
        """/search 只注册了 GET，表单 POST 过去 = 提交即 405：判词要说清是方法缺。"""
        ok, report = _run(tmp_path, _app_src(
            _FORM.format(path="/search", verb="post"),
            "    @app.route('/search')\n"
            "    def s():\n        return 'search'\n"))
        assert not ok, report
        assert "405" in report, report

    def test_matching_action_and_method_passes(self, tmp_path):
        ok, report = _run(tmp_path, _app_src(
            _FORM.format(path="/books", verb="post"),
            "    @app.route('/books', methods=['POST'])\n"
            "    def add():\n        return 'added'\n"))
        assert ok, report

    def test_missing_action_defaults_to_page_path(self, tmp_path):
        """<form method=post> 缺 action 时浏览器提交到当前页路径——
        该页只有 GET 就是 405，不能因为 HTML 里没写 action 就当没这个表单。"""
        ok, report = _run(tmp_path, _app_src(
            "<a href='/x'>X</a><form method='post'>"
            "<input name='title' placeholder='Title'></form>"))
        assert not ok, report
        assert "405" in report, report

    def test_submit_crash_fails_smoke(self, tmp_path):
        """路由对得上但一提交就抛（交付自带的库缺表就是这个形态）。"""
        ok, report = _run(tmp_path, _app_src(
            _FORM.format(path="/books", verb="post"),
            "    @app.route('/books', methods=['POST'])\n"
            "    def add():\n        return 1 / 0\n"))
        assert not ok, report
        assert "一提交就崩" in report, report
        assert "ZeroDivisionError" in report, report

    def test_submit_500_response_fails_smoke(self, tmp_path):
        ok, report = _run(tmp_path, _app_src(
            _FORM.format(path="/books", verb="post"),
            "    @app.route('/books', methods=['POST'])\n"
            "    def add():\n        return 'boom', 500\n"))
        assert not ok, report
        assert "提交返回 500" in report, report

    def test_payload_built_from_named_fields(self, tmp_path):
        """未勾选的 checkbox 不进载荷（浏览器同口径），带 name 的文本域必进。"""
        ok, report = _run(tmp_path, _app_src(
            "<a href='/x'>X</a><form action='/subscribe' method='post'>"
            "<input type='checkbox' name='agree' placeholder='Agree'>"
            "<input type='text' name='email' placeholder='Email'></form>",
            "    @app.route('/subscribe', methods=['POST'])\n"
            "    def sub():\n        assert 'email' in request.form\n"
            "        return 'ok'\n"))
        assert ok, report


class TestFormProbeNoFalseRed:
    def test_external_and_templated_actions_skipped(self, tmp_path):
        """外链/模板拼出来的/锚点 action：静态无从判定，一律不判（假红=白烧修复轮）。

        这里直接叫探针而不是走 run_smoke：`{{ }}` 那一条会被冒烟既有的
        「未求值模板占位符」判据先拦下，跟本用例要验的跳过逻辑无关。
        """
        bodies = [
            "<form action='https://example.com/p' method='post'>"
            "<input name='t' placeholder='T'></form>",
            "<form action='{{ url_for(\"save\") }}' method='post'>"
            "<input name='t' placeholder='T'></form>",
            "<form action='#top'><input name='t' placeholder='T'></form>",
            "<form action='mailto:a@b.c'><input name='t' placeholder='T'></form>",
            "<form action='/static/js/app.js'><input name='t' placeholder='T'></form>",
            "<form action='/ok' method='put'><input name='t' placeholder='T'></form>",
        ]
        extra = ("    @app.route('/ok', methods=['POST'])\n"
                 "    def ok_():\n        return 'saved'\n")
        for i, body in enumerate(bodies):
            code = _code(tmp_path / str(i), _app_src("<a href='/x'>X</a>" + body,
                                                     extra))
            assert run_form_probe(code) == [], body[:48]

    def test_path_converter_spans_slashes(self, tmp_path):
        """`<path:rest>` 一路吃到底：/files/a/b 这类真存在的目标若按单段匹配
        会被判成「路由表里没有这条」——那是假红，白烧一轮修复。"""
        code = _code(tmp_path, _app_src(
            "<a href='/x'>X</a><form action='/files/a/b' method='post'>"
            "<input name='t' placeholder='T'></form>",
            "    @app.route('/files/<path:rest>', methods=['POST'])\n"
            "    def up(rest):\n        return 'got ' + rest\n"))
        assert run_form_probe(code) == []
        ok, report = run_smoke(code)
        assert ok, report

    def test_json_api_app_unaffected(self, tmp_path):
        """纯接口交付（页面里没有 form）零新增拦截。"""
        ok, report = _run(tmp_path, _app_src("<a href='/x'>X</a><p>ok</p>"))
        assert ok, report


class TestFastAPIFormProbe:
    def _fastapi_src(self, home_body: str, extra: str = "") -> str:
        return (
            "from fastapi import FastAPI\n"
            "from fastapi.responses import HTMLResponse\n"
            "def create_app():\n"
            "    app = FastAPI()\n"
            "    @app.get('/api/health')\n"
            "    def h():\n        return {'status': 'ok'}\n"
            "    @app.get('/')\n"
            f"    def home():\n        return HTMLResponse({home_body!r})\n"
            + extra
            + "    return app\n"
        )

    def test_fastapi_dead_action_fails_smoke(self, tmp_path):
        """双栈义务：探针的路由表读取在 Starlette 上走 app.routes 分支。"""
        ok, report = _run(tmp_path, self._fastapi_src(
            "<a href='/x'>X</a><form action='/notes' method='get'>"
            "<input name='q' placeholder='Q'></form>"))
        assert not ok, report
        assert "路由表里没有这条" in report, report

    def test_fastapi_registered_action_passes(self, tmp_path):
        ok, report = _run(tmp_path, self._fastapi_src(
            "<a href='/x'>X</a><form action='/save' method='post'>"
            "<input name='q' placeholder='Q'></form>",
            "    @app.post('/save')\n"
            "    def make():\n        return {'ok': True}\n"))
        assert ok, report


class TestProbeSandbox:
    def test_delivered_database_untouched(self, tmp_path):
        """探针要真提交，真提交会写库——必须跑在副本里：
        评测看见多出来的行同样是保真缺陷。"""
        code = tmp_path / "code"
        _write(code / "app_mod" / "__init__.py",
               "from app_mod.app_mod import *  # noqa: F401,F403\n")
        _write(code / "app_mod" / "app_mod.py", _DB_APP_SRC)
        db = code / "app.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE IF NOT EXISTS books "
                     "(id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO books (title) VALUES ('seed')")
        conn.commit()
        conn.close()
        before = db.read_bytes()

        ok, report = run_smoke(code)
        # 前提断言：应用必须真的装配起来了，否则「库没被动」是空话
        assert ok, report

        assert db.read_bytes() == before, "探针把测试数据写进了交付自带的库"
        conn = sqlite3.connect(str(db))
        rows = conn.execute("SELECT title FROM books").fetchall()
        conn.close()
        assert [r[0] for r in rows] == ["seed"]

    def test_tool_failure_is_not_an_app_defect(self, tmp_path):
        """探针自己起不来（这里连应用都没有）一律返回空列表：
        工具失效不该拦交付。"""
        code = tmp_path / "code"
        _write(code / "notes.txt", "nothing importable here")
        assert run_form_probe(code) == []
        assert run_form_probe(tmp_path / "does-not-exist") == []

    def test_probe_reuses_smoke_assembly_preamble(self):
        """两道验证共用同一套应用择优算法：前段必须逐字取自冒烟模板，
        否则闸测的就不是判分面那同一个应用。"""
        from app.arcbench_smoke import _VERIFY_TEMPLATE, _VERIFY_ASSEMBLY_PREFIX
        script = _form_script()
        assert script, "拼装标记丢失=探针静默失效"
        head = _VERIFY_TEMPLATE.split(_VERIFY_ASSEMBLY_PREFIX)[0]
        assert script.startswith(head)
        assert "@@FORMS@@" in script
        assert _VERIFY_ASSEMBLY_PREFIX not in script


class TestVerdictWiring:
    def test_form_red_names_the_page_and_the_fix(self, tmp_path):
        """判词必须可直接执行：哪一页、什么方法、哪条路径、缺什么字段、怎么改。"""
        ok, report = _run(tmp_path, _app_src(
            _FORM.format(path="/api/notes", verb="post")))
        assert not ok
        seg = report[report.index("[form]"):]
        assert "页面 /" in seg and "POST /api/notes" in seg, seg
        assert "title" in seg, seg
        assert "把 action 改成" in seg or "注册" in seg, seg

    def test_probe_skipped_when_smoke_already_red(self, tmp_path):
        """冒烟基线已红时不再跑探针（修复环已拿到判词，探针要再启一次应用）。
        这里首页是占位壳页——红字应当只有壳页，不含表单对账。"""
        ok, report = _run(tmp_path, _app_src(
            "<h1>Welcome</h1><p>No affordance here.</p>"))
        assert not ok
        assert "[form]" not in report, report


class TestSmokeGate:
    """批次#44：修复循环的复测（test_cmd）必须与判定同闸。

    锚点闸的取证就是这条教训：判词说的是锚点缺口，复测跑的却是本来就过的
    冒烟，于是三轮修复分文未收敛。表单闸同形——不复用同一个闸，等于让
    模型朝「让基线冒烟绿」收敛，而 [form] 红字它照单收进了提示词。
    """

    def _run(self, code_dir, gate):
        return subprocess.run(
            [sys.executable, str(gate), str(code_dir)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, cwd=str(pathlib.Path(code_dir).parent))

    def test_gate_red_on_dead_action(self, tmp_path):
        code = _code(tmp_path, _app_src(_FORM.format(path="/notes", verb="get")))
        p = self._run(code, write_gate_scripts())
        assert p.returncode != 0, p.stdout[-400:]
        assert "[form]" in p.stdout and "路由表里没有这条" in p.stdout, p.stdout[-400:]

    def test_gate_green_on_matching_action(self, tmp_path):
        code = _code(tmp_path, _app_src(
            _FORM.format(path="/books", verb="post"),
            "    @app.route('/books', methods=['POST'])\n"
            "    def add():\n        return 'ok'\n"))
        p = self._run(code, write_gate_scripts())
        assert p.returncode == 0, p.stdout[-400:]

    def test_gate_stops_at_base_smoke_when_it_is_red(self, tmp_path):
        """基线红就直接判红：探针段不再跑（与 run_smoke 同口径）。"""
        code = _code(tmp_path, _app_src("<h1>Hi</h1><p>Nothing to click.</p>"))
        p = self._run(code, write_gate_scripts())
        assert p.returncode != 0, p.stdout[-400:]
        assert "[form]" not in p.stdout, p.stdout[-400:]

    def test_gate_passes_when_probe_script_is_lost(self, tmp_path):
        """探针脚本没落盘＝工具失效，一律放行：闸炸了不该算交付的错。"""
        code = _code(tmp_path, _app_src(_FORM.format(path="/notes", verb="get")))
        gate = write_gate_scripts()
        (gate.parent / "arcbench_smoke_forms.py").unlink()
        p = self._run(code, gate)
        assert p.returncode == 0, p.stdout[-400:]
        assert "工具失效" in p.stdout, p.stdout[-400:]

    def test_gate_leaves_delivered_db_untouched(self, tmp_path):
        """闸自己也跑副本：修复循环每轮复测都写一次交付库的话，评测拿到的
        时候库里已经多了测试数据。"""
        code = _code(tmp_path, _DB_APP_SRC)
        db = code / "app.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE IF NOT EXISTS books "
                     "(id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO books (title) VALUES ('seed')")
        conn.commit()
        conn.close()
        before = db.read_bytes()
        p = self._run(code, write_gate_scripts())
        assert p.returncode == 0, p.stdout[-400:]
        assert db.read_bytes() == before

    def test_gate_budget_fits_fixer_timeout(self):
        """复测总预算必须留在 RepoFixer 的 test_timeout 之内：被外层熔断会
        给出「验证命令超时」这种修复者读不懂的信号。"""
        import inspect

        from app.agents.repo_fixer import RepoFixer
        limit = inspect.signature(RepoFixer.__init__).parameters[
            "test_timeout"].default
        assert (SMOKE_TIMEOUT - 10) + (FORM_TIMEOUT - 30) < limit

    def test_auto_repair_uses_the_gate(self, tmp_path, monkeypatch):
        """接线本身要有断言：默认 test_cmd 指向闸脚本，而不是裸冒烟。"""
        captured = {}

        class _FakeFixer:
            def __init__(self, llm, project_dir, test_cmd=None, **kw):
                captured["test_cmd"] = list(test_cmd or [])

            def fix(self, issue):
                import types
                return types.SimpleNamespace(ok=True, rounds=1)

        project = tmp_path / "project"
        code = _code(project, _app_src(_FORM.format(path="/notes", verb="get")))
        assert not run_smoke(code)[0], "前提：这份交付必须是被 [form] 判红的"
        monkeypatch.setattr("app.agents.repo_fixer.RepoFixer", _FakeFixer)
        monkeypatch.setattr("app.utils.model_client.ModelClient",
                            lambda settings: object())
        from app.arcbench_smoke import auto_repair
        auto_repair(project, settings=None, max_rounds=1)
        assert captured["test_cmd"], "修复循环没拿到复测命令"
        assert captured["test_cmd"][1].endswith("arcbench_smoke_gate.py"), \
            captured["test_cmd"]


def test_probe_script_compiles():
    """探针脚本自身必须是合法 Python（转义/切片手一抖就 SyntaxError）。"""
    script = _form_script()
    assert script
    compile(script, "<form_probe>", "exec")
