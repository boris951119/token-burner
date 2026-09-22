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
    "/list": ('<html><body><p>Sprint goals</p>'
              '<input placeholder="Take a note">'
              '<label>Email address</label>'
              '<script>var s="Sprint goals 不该算数"</script>'
              '</body></html>'),
}


class _H(BaseHTTPRequestHandler):
    def do_GET(s):  # noqa: N805
        body = PAGES.get(s.path, "").encode()
        s.send_response(200)
        s.send_header("Content-Type", "text/html; charset=utf-8")
        s.end_headers()
        s.wfile.write(body)

    def log_message(s, *a):  # noqa: N805
        pass


@pytest.fixture(scope="module")
def base_url():
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
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


def test_script_content_not_counted_as_visible(base_url):
    # script 里的文案不算可见（防 JS 常量伪装成 UI）
    r = judge_checklists([_ck(seed_entities=["不该算数"])], base_url)
    assert r["failed"] == 1


def test_non_home_nodes_skipped(base_url):
    r = judge_checklists([_ck(home_visible=False,
                              seed_entities=["Anything"])], base_url)
    assert r == {"passed": 0, "failed": 0, "total": 0, "failures": []}


def test_dead_server_degrades_all_fail_not_crash():
    ck = [_ck(seed_entities=["X"], control_labels=["Y"])]
    # 端口 1 必然拒连：判分器不得抛异常，全部记红
    r = judge_checklists(ck, "http://127.0.0.1:1", timeout=1.0)
    assert r["failed"] == 2 and len(r["failures"]) == 2


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
