# -*- coding: utf-8 -*-
"""刀P 工具带：沙箱、一事一具、参数≤3、坏补丁回滚、循环协议。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.utils.agent_tools import ToolBelt, run_tool_loop


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(
        "from flask import Flask\n\napp = Flask(__name__)\n\n\n"
        "@app.get('/')\ndef home():\n    return '<h1>Workbook Home</h1>'\n",
        encoding="utf-8")
    (tmp_path / "big.py").write_text("x = 1\n" * 60_000, encoding="utf-8")  # >200KB 触发外科上限
    (tmp_path / "dup.py").write_text("TAG = 1\nTAG = 2\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "m.py").write_text("VALUE = 1\n", encoding="utf-8")
    return tmp_path


def belt(repo: Path, **kw) -> ToolBelt:
    return ToolBelt(root=repo, **kw)


def test_read_numbered_and_missing(repo):
    r = belt(repo).read("app.py")
    assert r.ok and "1\tfrom flask" in r.output
    assert not belt(repo).read("nope.py").ok


def test_grep_hits_and_bad_regex(repo):
    r = belt(repo).grep("Workbook", ".")
    assert r.ok and "app.py:" in r.output
    assert not belt(repo).grep("(unclosed").ok


def test_edit_surgical_unique_only(repo):
    b = belt(repo)
    r = b.edit("app.py", "<h1>Workbook Home</h1>", "<h1>Q3 Sales</h1>")
    assert r.ok
    assert "Q3 Sales" in (repo / "app.py").read_text(encoding="utf-8")
    # 非唯一命中拒绝（dup.py 两处 TAG）
    r2 = belt(repo).edit("dup.py", "TAG", "REPLACED")
    assert not r2.ok and "命中 2 处" in r2.output


def test_edit_bad_patch_rolls_back(repo):
    b = belt(repo)
    before = (repo / "app.py").read_text(encoding="utf-8")
    r = b.edit("app.py", "from flask import Flask",
               "from flask import Flask\nthis is ((( not python")
    assert not r.ok and "语法非法已回滚" in r.output
    assert (repo / "app.py").read_text(encoding="utf-8") == before  # 盘上无损


def test_edit_oversize_refused(repo):
    # 直接 API 层断言超限拒改（唯一性在此无干扰：超限检查先于命中检查）
    r = belt(repo).edit("big.py", "x = 1\nx = 2 never-matches", "whatever")
    assert not r.ok and "外科上限" in r.output


def test_sandbox_escape_blocked(repo):
    for path in ("../outside.py", "/etc/passwd", "sub/../../escape.py"):
        r = belt(repo).read(path)
        assert not r.ok and "沙箱" in r.output


def test_check_without_cmd(repo):
    assert not belt(repo).check().ok


def test_check_with_cmd(repo):
    b = belt(repo, check_cmd=[sys.executable, "-c", "print('all green')"])
    r = b.check()
    assert r.ok and "all green" in r.output


def test_tool_loop_converges_with_stub_llm(repo):
    """循环协议回归：stub 大脑走 read→edit→check(DONE) 收敛路径。"""
    calls = {"n": 0}

    def llm(system: str, user: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "read('sub/m.py')"
        if calls["n"] == 2:
            return "edit('sub/m.py', 'VALUE = 1', 'VALUE = 2')"  # 引号参数含空格安全
        return "DONE fixed VALUE"

    b = belt(repo, check_cmd=[sys.executable, "-c", "print('ok')"])
    out = run_tool_loop(llm, b, "VALUE 应为 2", max_turns=6)
    assert out["ok"] is True and out["turns"] == 3
    assert (repo / "sub" / "m.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert any("edit(" in t for t in out["trace"])


def test_parse_args_quoted_spaces_and_arity():
    from app.utils.agent_tools import _parse_args
    assert _parse_args("'a.py', 'old text', 'new'", 3) == (
        "a.py", "old text", "new")
    assert _parse_args("'line1\\nline2'", 1) == ("line1\nline2",)
    with pytest.raises(ValueError):
        _parse_args("bare, args", 2)
    with pytest.raises(ValueError):
        _parse_args("'a', 'b'", 3)


def test_tool_loop_bad_format_coached(repo):
    """格式错误不清零预算：系统回喂纠正，下一轮继续。"""
    seq = ["我要先看看文件", "DONE just kidding"]

    def llm(system: str, user: str) -> str:
        return seq.pop(0)

    b = belt(repo)
    out = run_tool_loop(llm, b, "x", max_turns=4)
    assert out["turns"] == 2 and "bad-format" in out["trace"][0]


def test_three_call_forms_all_accepted(repo):
    """实测三形态：行协议 / kwargs / XML（<tool_call> 与 <invoke> 都收）。"""
    from app.utils.agent_tools import _extract_call
    assert _extract_call("grep('A', '.')") == ("grep", ["A", "."])
    assert _extract_call('grep("A", path=".")') == ("grep", ["A", "."])
    xml1 = ('<tool_calls>\n<tool_call name="grep">\n'
            '<parameter name="pattern" string="true">Create</parameter>\n'
            '<parameter name="path" string="true">.</parameter>\n'
            '</tool_call>\n</tool_calls>')
    assert _extract_call(xml1) == ("grep", ["Create", "."])
    xml2 = ('<tool_calls>\n<invoke name="edit">\n'
            '<parameter name="file">a.py</parameter>\n'
            '<parameter name="old">x=1</parameter>\n'
            '<parameter name="new">x=2</parameter>\n'
            '</invoke>\n</tool_calls>')
    assert _extract_call(xml2) == ("edit", ["a.py", "x=1", "x=2"])
    assert _extract_call("just prose") is None


def test_native_xml_tool_call_accepted(repo):
    """deepseek/glm 网关原生 XML 工具调用形态（pro 30 轮全灭的根因回归）。"""
    seq = [
        '<tool_calls>\n<invoke name="grep">\n'
        '<parameter name="pattern">Workbook</parameter>\n'
        '<parameter name="path">.</parameter>\n</invoke>\n</tool_calls>',
        "DONE seen it",
    ]

    def llm(system: str, user: str) -> str:
        return seq.pop(0)

    b = belt(repo)
    out = run_tool_loop(llm, b, "找 Workbook", max_turns=4)
    assert out["turns"] == 2
    assert "grep(" in out["trace"][0] and "bad-format" not in out["trace"][0]
