# -*- coding: utf-8 -*-
"""批次#42：悬空 Jinja 继承/包含的机械摘除。

立项度量（零 token，本机 13 份带模板交付全量普查）：用到继承/包含的 3 份、
指令 12 条，其中 10 条指向从未生成的模板（runA 那份 6/6 全悬空 = 整站每页 500）。
对照组同样是硬要求：能解析的继承一个字都不许动。
"""
import inspect
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import jinja2  # noqa: E402

from app.agents.module_builder import inject_ui_manifest  # noqa: E402
from app.utils.auto_fixer import fix_dangling_template, run_all_fixers  # noqa: E402


def _write(p, s):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8", newline="\n")


def _read(p):
    return p.read_text(encoding="utf-8")


INLINE = (
    "from flask import Flask, render_template_string\n"
    "\n"
    "_INDEX_HTML = '''{% extends \"base.html\" %}\n"
    "{% block content %}\n"
    "<h2>链接列表</h2>\n"
    "<a href=\"/links/new\">新建</a>\n"
    "{% endblock %}'''\n"
    "\n"
    "def create_app():\n"
    "    app = Flask(__name__)\n"
    "\n"
    "    @app.route('/')\n"
    "    def index():\n"
    "        return render_template_string(_INDEX_HTML)\n"
    "    return app\n"
)


def _render(source: str, empty_dir: pathlib.Path) -> str:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(empty_dir)))
    return env.from_string(source).render()


class TestInlineShape:
    def test_runA_shape_recovers_the_page(self, tmp_path):
        """内联串里 extends 一个不存在的父模板 = 该页 500 → 摘除后正文可见。"""
        py = tmp_path / "link_creation" / "__init__.py"
        _write(py, INLINE)
        empty = tmp_path / "no_templates"
        empty.mkdir()
        body = INLINE.split("_INDEX_HTML = '''")[1].split("'''")[0]
        try:
            _render(body, empty)
            raise AssertionError("前置条件不成立：悬空 extends 本就该抛 TemplateNotFound")
        except jinja2.exceptions.TemplateNotFound:
            pass

        fixes = fix_dangling_template(tmp_path)
        assert len(fixes) == 1 and "base.html" in fixes[0]
        assert "extends" not in _read(py)
        after = _read(py).split("_INDEX_HTML = '''")[1].split("'''")[0]
        rendered = _render(after, empty)
        assert "链接列表" in rendered and "新建" in rendered
        assert "{#" not in rendered  # 摘除注释不落到页面

    def test_idempotent(self, tmp_path):
        py = tmp_path / "m.py"
        _write(py, INLINE)
        assert fix_dangling_template(tmp_path)
        assert not fix_dangling_template(tmp_path)

    def test_only_the_directive_changes(self, tmp_path):
        """除指令本身外一个字都不许多动（Python 结构与模板正文都得原样）。"""
        py = tmp_path / "m.py"
        _write(py, INLINE)
        before = _read(py)
        fix_dangling_template(tmp_path)
        after = _read(py)
        expected = before.replace(
            '{% extends "base.html" %}',
            '{# 机械摘除：目标模板 base.html 未随交付生成 #}')
        assert after == expected
        compile(after, "m.py", "exec")


class TestFileShape:
    def test_dangling_extends_in_html(self, tmp_path):
        child = tmp_path / "code" / "templates" / "book_detail.html"
        _write(child, '{% extends "base.html" %}\n'
                      '{% block content %}<h1>正文</h1>{% endblock %}\n')
        fixes = fix_dangling_template(tmp_path / "code")
        assert fixes and "extends" in fixes[0]
        assert "{% block content %}" in _read(child)

    def test_resolvable_inheritance_untouched(self, tmp_path):
        """反向控制：父模板真写了出来的交付，一个字都不许动。"""
        code = tmp_path / "code"
        parent = code / "templates" / "base.html"
        child = code / "templates" / "page.html"
        _write(parent, '<html>{% block content %}{% endblock %}</html>')
        _write(code / "templates" / "partials" / "nav.html", "<nav>n</nav>\n")
        _write(child, '{% extends "base.html" %}\n'
                      '{% include "partials/nav.html" %}\n'
                      '{% block content %}x{% endblock %}\n')
        before = _read(child)
        assert not fix_dangling_template(code)
        assert _read(child) == before

    def test_dangling_include_stripped(self, tmp_path):
        f = tmp_path / "templates" / "page.html"
        _write(f, '<h1>a</h1>\n{% include "missing/partial.html" %}\n')
        fixes = fix_dangling_template(tmp_path)
        assert fixes and "include" in fixes[0]
        assert "missing/partial.html" in fixes[0]
        assert "{% include" not in _read(f)
        assert "<h1>a</h1>" in _read(f)

    def test_quoted_and_whitespace_forms(self, tmp_path):
        f = tmp_path / "templates" / "p.html"
        _write(f, "{%- extends 'base.html' -%}\n{% block c %}1{% endblock %}\n")
        assert fix_dangling_template(tmp_path)
        assert "extends" not in _read(f)

    def test_import_left_alone(self, tmp_path):
        """import 的宏真被调用时摘了会换成 UndefinedError——不属本修复器射程。"""
        f = tmp_path / "templates" / "p.html"
        _write(f, '{% import "macros.html" as m %}\n{{ m.row() }}\n')
        assert not fix_dangling_template(tmp_path)
        assert "import" in _read(f)


class TestRosterAndPrompt:
    def test_wired_into_run_all_fixers(self, tmp_path):
        _write(tmp_path / "m.py", INLINE)
        assert "悬空模板继承" in run_all_fixers(tmp_path)

    def test_generator_prompt_carries_the_rule(self):
        """生成侧同步一条框架级通用规则（预防优先于摘除）。"""
        src = inspect.getsource(inject_ui_manifest)
        assert "extends" in src and "TemplateNotFound" in src
