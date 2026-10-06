# -*- coding: utf-8 -*-
"""主旅程从需求编译，不依赖某一道赛题的专用名词。"""
from app.utils.mechanical_journey import (
    compile_click_journeys,
    find_click,
    run_compiled_journeys,
    walk_journeys,
)


def test_compiles_english_and_chinese_click_paths():
    en = (
        "### Open the board\n"
        "WHEN the visitor clicks \"Boards\"\n"
        "THEN the text \"Cells\" is visible\n"
    )
    zh = (
        "### 打开工作表\n"
        "WHEN 用户点击「工作表」\n"
        "THEN 页面出现「单元格」\n"
    )
    en_j = compile_click_journeys(en)
    zh_j = compile_click_journeys(zh)
    assert [(s.kind, s.text) for s in en_j[0].steps] == [
        ("click", "Boards"), ("see", "Cells")]
    assert [(s.kind, s.text) for s in zh_j[0].steps] == [
        ("click", "工作表"), ("see", "单元格")]
    assert compile_click_journeys("no quoted clicks here") == []


def test_walk_follows_one_link_and_rejects_duplicates():
    pages = {
        "/": (200, "<html><body><a href='/board'>Boards</a></body></html>"),
        "/board": (200, "<html><body><p>Cells</p></body></html>"),
    }

    def request(method, path):
        assert method == "GET"
        return pages[path.split("?", 1)[0]]

    journeys = compile_click_journeys(
        '### Open\nWHEN clicks "Boards"\nTHEN "Cells" is visible\n')
    assert walk_journeys(journeys, request) == []

    dup = {
        "/": (200, "<a href='/a'>Boards</a><a href='/b'>Boards</a>"),
    }
    fails = walk_journeys(journeys, lambda m, p: dup.get(p, (404, "")))
    assert fails and "2 个" in fails[0]


def test_click_target_count_is_strict():
    html = "<a href='/a'>Boards</a><button>Boards</button>"
    # 链接先匹配；两个链接才算重复。一个链接就走链接。
    action, n = find_click(html, "Boards", "/")
    assert n == 1 and action == ("GET", "/a")
    action, n = find_click("<p>Boards</p>", "Boards", "/")
    assert action is None and n == 0


def test_run_against_a_small_app(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "app_main.py").write_text(
        "from flask import Flask\n"
        "def create_app():\n"
        "    a = Flask('demo')\n"
        "    @a.route('/')\n"
        "    def home():\n"
        "        return '<html><body><a href=\"/board\">Boards</a></body></html>'\n"
        "    @a.route('/board')\n"
        "    def board():\n"
        "        return '<html><body>Cells</body></html>'\n"
        "    return a\n",
        encoding="utf-8")
    req = '### Open\nWHEN the visitor clicks "Boards"\nTHEN "Cells" is visible\n'
    status, report = run_compiled_journeys(code, req)
    assert status == "pass", report
    (code / "app_main.py").write_text(
        "from flask import Flask\n"
        "def create_app():\n"
        "    a = Flask('demo')\n"
        "    @a.route('/')\n"
        "    def home():\n"
        "        return '<html><body><p>nothing</p></body></html>'\n"
        "    return a\n",
        encoding="utf-8")
    status, report = run_compiled_journeys(code, req)
    assert status == "fail", report
    assert "Boards" in report
    status, report = run_compiled_journeys(code, "plain requirement without steps")
    assert status == "skip"


def test_fill_then_submit_posts_named_fields():
    req = (
        '### Sign in\n'
        'WHEN the visitor fills "username" with "alice"\n'
        'AND clicks "Submit"\n'
        'THEN "Welcome" is visible\n'
    )
    journeys = compile_click_journeys(req)
    assert journeys
    kinds = [s.kind for s in journeys[0].steps]
    assert "fill" in kinds and "click" in kinds
    pages = {
        "/": (200, (
            "<form method='post' action='/login'>"
            "<input name='username' placeholder='username'>"
            "<button>Submit</button></form>"
        )),
        "/login": (200, "<p>Welcome</p>"),
    }
    posted = {}

    def request(method, path, data=None):
        if method == "POST":
            posted.update(data or {})
        key = path.split("?", 1)[0]
        return pages.get(key, pages["/"]) if method == "GET" else pages.get(key, (200, "<p>Welcome</p>"))

    assert walk_journeys(journeys, request) == []
    assert posted.get("username") == "alice"
