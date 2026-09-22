# -*- coding: utf-8 -*-
"""HTTP 编译清单判分器：通道覆盖 + 修复环兼容性（stdlib 服务器，零外网）。"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.acceptance_compile import NodeChecklist
from app.utils.acceptance_judge import judge_checklists

PAGES = {
    "/": ('<html><body><a href="/list">L</a><a href="/x.css">c</a>'
          '<p>Welcome to 笔记站</p></body></html>'),
    # 「press "Take a note"」在需求里是一条硬通道（评测按 button 定位），
    # 夹具应用因此必须真的有个按钮，只有 placeholder 就是缺陷而非替代通道。
    "/list": ('<html><body><p>Sprint goals</p>'
              '<button>Take a note</button>'
              '<input placeholder="Take a note">'
              '<label>Email address</label>'
              '<script>var s="Sprint goals 不该算数"</script>'
              '</body></html>'),
}


class _H(BaseHTTPRequestHandler):
    def do_GET(s):  # noqa: N805
        body = s.server.pages.get(s.path, "").encode()
        code = s.server.codes.get(s.path, 200)
        s.send_response(code)
        s.send_header("Content-Type", "text/html; charset=utf-8")
        s.end_headers()
        s.wfile.write(body)

    def log_message(s, *a):  # noqa: N805
        pass


def _serve(pages: dict, codes: dict | None = None):
    srv = HTTPServer(("127.0.0.1", 0), _H)
    srv.pages = pages
    srv.codes = codes or {}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture(scope="module")
def base_url():
    srv = _serve(PAGES)
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _ck(**kw):
    base = dict(req_id="REQ-2.1", req_name="n", module_id="REQ-2",
                language="latin", home_visible=True)
    base.update(kw)
    return NodeChecklist(**base)


def test_channels_and_failures(base_url):
    ck = [_ck(seed_entities=["Sprint goals", "Welcome to 笔记站", "Ghost"],
              control_labels=["Take a note", "Email address", "Nope"])]
    r = judge_checklists(ck, base_url)
    assert r["passed"] == 4 and r["failed"] == 2
    # 失败串必须以 REQ id 开头（grade_repair_loop re.match 兼容）
    assert all(f.startswith("REQ-2.1 ") for f in r["failures"])
    assert any("Ghost" in f for f in r["failures"])
    assert any("Nope" in f for f in r["failures"])


def test_script_only_fact_is_out_of_scope_not_green(base_url):
    """页内脚本正文是第三条通道：既不让 JS 常量**判绿**（那是伪装成 UI），
    也不再判红——客户端渲染的文案浏览器出得来像素，静态判分没资格说
    「未出现」（9/23 三组对照取证）。"""
    r = judge_checklists([_ck(seed_entities=["不该算数"])], base_url)
    assert r["failed"] == 0 and r["passed"] == 0
    assert r["client_side"] == 1 and "客户端渲染" in r["note"]


def test_non_home_nodes_skipped(base_url):
    r = judge_checklists([_ck(home_visible=False,
                              seed_entities=["Anything"])], base_url)
    assert r == {"passed": 0, "failed": 0, "total": 0, "failures": []}


def test_dead_server_degrades_all_fail_not_crash():
    ck = [_ck(seed_entities=["X"], control_labels=["Y"])]
    # 端口 1 必然拒连：判分器不得抛异常，且必须记红
    r = judge_checklists(ck, "http://127.0.0.1:1", timeout=1.0)
    assert r["failed"] == 1 and len(r["failures"]) == 1
    # 语料为空时不摊成 N 条幻影失败：一个根因一句话，修复环才有的可修
    assert "无可见文本" in r["failures"][0]


def test_requirements_e2e(base_url, tmp_path):
    (tmp_path / "requirements.yaml").write_text(
        "id: ROOT\ntype: FOLDER\nchildren:\n"
        "  - id: REQ-2\ntype: FOLDER\n    children:\n"
        "      - id: REQ-2.1\n        type: ATOMIC\n"
        "        name: Listing\n        description: >\n"
        "          Seed data: note \"Sprint goals\". The home page shows it.\n"
        "        scenarios:\n          - name: s\n            steps:\n"
        "              - keyword: GIVEN\n"
        "                content: the app is open on the home page\n"
        "              - keyword: WHEN\n"
        "                content: 'press \"Take a note\"'\n"
        "              - keyword: THEN\n"
        "                content: editor opens\n", encoding="utf-8")
    from app.utils.acceptance_judge import judge_requirements

    r = judge_requirements(tmp_path, base_url)
    assert r["total"] >= 2 and r["failed"] == 0, r["failures"]
    # 可点通道必须真的判过（not 静默跳过）：夹具的 WHEN 是 press "Take a note"
    assert "1/1 条「点击 X」类控件确为可点元素" in r.get("note", "")


# ---- 判分语料近乎为空：平台侧唯一的闸不得摊派幻影失败 ----
# 官方交付容器无 node → Playwright 段整体 SKIP，编译清单判分是唯一的
# 质量闸。此时若入口页抓不到可见文本，逐条事实记红 = N 条修不好的幻影
# 失败直灌修复环（每轮 1800s 验证 + 真金 token），而根因只有一条。

SPA = {"/": ('<!doctype html><html><body><div id="root"></div>'
             '<script>ReactDOM.render(x, document.getElementById("root"))'
             '</script></body></html>')}


def test_client_rendered_shell_is_skipped_not_phantom_red():
    srv = _serve(SPA)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    ck = [_ck(seed_entities=["Sprint goals", "Welcome"],
              control_labels=["Take a note"])]
    r = judge_checklists(ck, url)
    srv.shutdown()
    assert r["failures"] == [] and r["failed"] == 0
    assert "客户端渲染" in r["skipped"], r


BLANK = {"/": "<html><body><!-- 空壳 --></body></html>"}


def test_blank_home_page_fails_once_with_root_cause():
    srv = _serve(BLANK)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    ck = [_ck(seed_entities=["Sprint goals", "Welcome"],
              control_labels=["Take a note"])]
    r = judge_checklists(ck, url)
    srv.shutdown()
    assert r["failed"] == 1 and len(r["failures"]) == 1
    assert "无可见文本" in r["failures"][0]


def test_500_home_page_fails_once_not_per_fact():
    # 9 条事实若逐条判红 = 9 条幻影失败；空语料必须先归因成一条
    srv = _serve({"/": ""}, codes={"/": 500})
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    ck = [_ck(seed_entities=[f"entity {i}" for i in range(9)])]
    r = judge_checklists(ck, url)
    srv.shutdown()
    assert r["failed"] == 1 and r["passed"] == 0


def test_rich_page_is_unaffected_by_thin_guard(base_url):
    # 门槛只吃空壳：正常首页（PAGES 语料 > 阈值）照旧逐条判
    ck = [_ck(seed_entities=["Sprint goals", "Ghost"])]
    r = judge_checklists(ck, base_url)
    assert r["passed"] == 1 and r["failed"] == 1
    assert r["failures"][0].startswith("REQ-2.1 ")


# ---- 不可见文案不算可见（9/23 keep 交付实证）---------------------------
# 那份交付的首页只渲染中文导航，英文文案全塞在一个
# <div class='hidden-anchors' style='display:none'> 里。旧判分器只剥
# <script>，于是隐藏块照样进语料 → 本地 8 条事实判绿、官方按可见性断言
# 全红。判分器必须与编译 spec 的 isVisible() 同口径，否则这道闸可以被
# 一行 CSS 骗过，而且等于把生成端往「塞隐藏文案」的方向惯。

STUFFED = {"/": (
    '<html><body><h1>我的笔记</h1>'
    '<p>全部笔记 提醒事项 归档笔记 回收站 置顶笔记 普通笔记 侧边栏导航</p>'
    '<div class="hidden-anchors" style="display:none">'
    '<ul><li>Reminders</li><li>Trash</li></ul>Pinned note tail</div>'
    '<div hidden><span>Archive</span>hidden-tail</div>'
    '<template>Pin note</template><!-- Search Settings -->'
    '<input type="hidden" value="Title">'
    '<input type="search" placeholder="Take a note">'
    '<span class="sr-only">Create Note</span>'
    '</body></html>')}


def test_invisible_stuffing_is_not_visible_text():
    srv = _serve(STUFFED)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    ck = [_ck(seed_entities=["Reminders", "Trash", "Archive", "Pin note",
                             "Search Settings", "Title",
                             "hidden-tail", "Pinned note tail"],
              control_labels=["Take a note", "Create Note"])]
    r = judge_checklists(ck, url)
    srv.shutdown()
    assert r["failed"] == 8, r["failures"]
    # 两条必须放行：placeholder 是渲染出来的（属性通道），sr-only 在
    # Playwright 口径里算可见（1px 裁剪仍有盒子）——误剔会把好应用判红
    assert r["passed"] == 2, r["failures"]


def test_visible_form_controls_survive_stripping(base_url):
    # 回归：自闭合 void 标签（<input>）在剔除遍历里必须原样保留，
    # 否则 placeholder 通道整体失明、真应用被判幻影失败
    ck = [_ck(control_labels=["Take a note"])]
    r = judge_checklists(ck, base_url)
    assert r["passed"] == 1 and r["failed"] == 0


# ---- 客户端渲染应用：整体阈值降级不够，必须逐条取证（9/23 三组对照）----
# 三组对照实测：服务端渲染正确应用、内联脚本注水的客户端渲染应用、fetch 拉
# JSON 的客户端渲染应用。后两组的静态可见文本 80/99 字符——越过了 _THIN_CORPUS
# 那道 40 字符的整体降级门（只要有一条静态导航栏就越过），于是需求文案
# 3/3 全判红、零真信号：修复环两轮 1800s 验证 + 真金 token 全烧在修不好的
# 指令上。按单条事实取证后：脚本里有这份文案 → 射程外；源码里根本没有 →
# 照旧判红（keep#2 那类「换语言/塞隐藏位」的造假属于后者，不受影响）。

SPA_INLINE = {"/": (
    '<html><body>'
    '<nav><a href="/">Shelf Tracker home</a> &middot; '
    '<a href="/about">About this shelf tracker</a></nav>'
    '<div id="app"></div>'
    '<script>const books = ["Dune", "Project Hail Mary"];'
    'document.getElementById("app").innerHTML ='
    " '<h1>My Shelf</h1><button>Add Book</button>'"
    " + books.map(b => '<li>' + b + '</li>').join('');</script>"
    '</body></html>')}


def test_inline_script_copy_is_out_of_scope_not_phantom_red():
    srv = _serve(SPA_INLINE)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    ck = [_ck(seed_entities=["My Shelf", "Dune", "Project Hail Mary"],
              control_labels=["Add Book", "Ghost Phrase"])]
    r = judge_checklists(ck, url)
    srv.shutdown()
    assert r["failed"] == 1, r["failures"]        # 只有源码里查无此文的判红
    assert "Ghost Phrase" in r["failures"][0]
    assert r["passed"] == 0                       # 射程外不等于判绿
    assert r["client_side"] == 4
    assert "客户端渲染" in r["note"]


SPA_API = {
    "/": ('<html><body>'
          '<nav><a href="/">Shelf Tracker home</a> &middot; '
          '<a href="/about">About this shelf tracker</a></nav>'
          '<main id="app"><p>Loading the shelf&hellip;</p></main>'
          '<script>fetch("/api/state").then(r => r.json()).then(s => {'
          'document.getElementById("app").innerHTML = s.title;});</script>'
          '</body></html>'),
    "/api/state": '{"title": "My Shelf"}',
}


def test_fetch_driven_copy_stays_red_as_known_limit():
    """已知射程边界并钉住：判分器不读 API 响应，文案在页面源码里不存在
    即判红。宁可留这一条假红，也不给「源码里没有」开绿灯——那是 keep#2
    造假的同一扇门。"""
    srv = _serve(SPA_API)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    r = judge_checklists([_ck(seed_entities=["My Shelf"])], url)
    srv.shutdown()
    assert r["failed"] == 1 and r.get("client_side") == 0


# ---- 整墙查无此文 → 一条结构性根因（run6 Linux 真交付取证）--------------
# 那次的产物活着、/api/health 绿，但入口之外没有任何 HTML 页面：70 条
# 逐字事实里只有 1 条在场。逐条判红 = 修复环拿到 20 条互不相干的抄写
# 指令，而真死因只有一句话（界面未实现）。归并必须同时满足「查无此文
# 占多数」与「入口之外渲染不出第二个页面」，否则会掩盖局部缺口。

SHELL_ONLY = {
    "/": ('<html><body><h1>Reading Desk</h1>'
          '<p>This page shows your shelves and the books inside them.'
          '</p><a href="/api/notes">notes api</a></body></html>'),
    "/api/notes": '{"ok": true, "items": []}',
}


def test_api_only_shell_merges_into_one_structural_root_cause():
    srv = _serve(SHELL_ONLY)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    ck = [_ck(seed_entities=[f"shelf label {i}" for i in range(12)])]
    r = judge_checklists(ck, url)
    srv.shutdown()
    assert r["failed"] == 1 and r["passed"] == 0 and r["total"] == 12, r
    f0 = r["failures"][0]
    assert "12/12" in f0 and "界面未实现" in f0
    # 归并指令必须自带定位证据：几个 HTML 页、链到哪、哪些链打不开
    assert "HTML 页面 1 个" in f0 and "站内链接 1 条" in f0
    assert "/api/notes" in f0
    assert "归并" in r["note"] and "不可见位置" in r["note"]


HIDDEN12 = {"/": (
    '<html><body><h1>Reading Desk</h1>'
    '<p>This page shows your shelves and the books inside them, all in one '
    'place for daily reading.</p>'
    '<div style="display:none">'
    + "".join(f"<span>anchor phrase {i}</span>" for i in range(12))
    + "</div></body></html>")}


def test_hidden_stuffing_is_never_merged_away():
    """raw 源码通道回归：12 条文案全塞在 display:none 里时，「查无此文」的
    归并规则若把源码误当空，就会给这堵假墙发一条「界面未实现」——那正是
    keep#2 造想要的免罪符。每条都得单独判红并点名隐藏位置。"""
    srv = _serve(HIDDEN12)
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    ck = [_ck(seed_entities=[f"anchor phrase {i}" for i in range(12)])]
    r = judge_checklists(ck, url)
    srv.shutdown()
    assert r["failed"] == 12 and r["passed"] == 0, r
    assert all("不可见位置" in f for f in r["failures"]), r["failures"][0]
    assert not any("界面未实现" in f for f in r["failures"])
    assert "note" not in r


# ---- 可点击控件通道（9/23 退役产物快照取证）-----------------------------
# 「文案在页面上」判绿之后依旧 0 分的那一类：需求写的是「点击 X」，评测
# 按 getByRole('button'/'link', {name}) 硬定位，正文文字与标题一概不算。

_FILLER = "<p>" + "zz body copy for a real page. " * 3 + "</p>"


def _url_for(body: str):
    """夹具页必须越过 _THIN_CORPUS：语料过薄时判分器走「首页无可见文本」
    根因通道，逐条判分根本不启动。"""
    srv = _serve({"/": "<html><body>" + body + _FILLER + "</body></html>"})
    return f"http://127.0.0.1:{srv.server_address[1]}"


class TestClickControlChannel:
    def test_plain_text_control_is_red(self):
        r = judge_checklists(
            [_ck(control_labels=["Take a note"], click_controls=["Take a note"],
                 seed_entities=[],
                 behavior_expectations=[])],
            _url_for('<h2>Take a note</h2><input placeholder="Take a note...">'))
        assert r["failed"] == 1
        assert "可点击控件" in r["failures"][0]
        assert r["failures"][0].startswith("REQ-2.1 ")
        assert "2" not in str(r["passed"]) or r["passed"] == 1

    def test_real_button_is_green(self):
        r = judge_checklists(
            [_ck(control_labels=["Take a note"], click_controls=["Take a note"])],
            _url_for('<button>Take a note</button>'))
        assert r["failed"] == 0, r["failures"]
        assert "1/1" in r.get("note", "")

    def test_every_official_channel_counts(self):
        """button / a[href] / role=menuitem / 勾选框的 label / submit 值——
        都是评测认的可点通道，漏认一条就是一条幻红。"""
        body = ('<button>Alpha</button><a href="/x">Beta</a>'
                '<span role="menuitem">Gamma</span>'
                '<label for="c1">Delta</label><input id="c1" type="checkbox">'
                '<label>Epsilon<input type="radio" name="r"></label>'
                '<input type="submit" value="Zeta">')
        labs = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]
        r = judge_checklists(
            [_ck(control_labels=labs, click_controls=labs)], _url_for(body))
        assert r["failed"] == 0, r["failures"]
        assert "6/6" in r.get("note", "")

    def test_decorative_label_is_not_a_channel(self):
        """<label> 包的是文本框时，点击它并不构成 button/link——
        「Take a note」正是这样被伪装成控件的。"""
        r = judge_checklists(
            [_ck(control_labels=["Take a note"], click_controls=["Take a note"])],
            _url_for('<label>Take a note<input type="text"></label>'))
        assert r["failed"] == 1 and "可点击控件" in r["failures"][0]

    def test_absent_control_not_double_judged(self):
        """主通道已经判「未出现」的，可点通道不得再补一条同因指令。"""
        r = judge_checklists(
            [_ck(control_labels=["Ghost"], click_controls=["Ghost"])],
            _url_for('<p>something else</p>' + '<!-- filler -->'
                     * 6 + '<b>' + 'x' * 60 + '</b>'))
        assert sum("Ghost" in f for f in r["failures"]) == 1
        assert not any("可点击控件" in f for f in r["failures"])

    def test_script_rendered_control_out_of_scope(self):
        r = judge_checklists(
            [_ck(control_labels=["Widget"], click_controls=["Widget"])],
            _url_for('<div id="root"></div>'
                     '<script>render("Widget ' + "y" * 50 + '")</script>'))
        assert not any("可点击控件" in f for f in r["failures"])

    def test_many_bad_controls_collapse_to_a_count(self):
        labs = [f"Bulk {i}" for i in range(12)]
        body = "".join(f"<p>{x}</p>" for x in labs)
        r = judge_checklists(
            [_ck(control_labels=labs, click_controls=labs)], _url_for(body))
        role_fails = [f for f in r["failures"] if "可点击控件" in f]
        assert len(role_fails) == 8
        assert any("另有 4 条" in f for f in r["failures"])
