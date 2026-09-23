# -*- coding: utf-8 -*-
"""确定性修复引擎回归测试（用户指令：修复不能靠概率）。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.utils.auto_fixer import (
    fix_column_drift, fix_import_drift,
    fix_submodule_binding, fix_blueprint_registry,
)

def _read(p): return p.read_text(encoding="utf-8")
def _write(p, s): p.write_text(s, encoding="utf-8", newline="\n")


class TestColumnDrift:
    def test_where_column_drift(self, tmp_path):
        """v2 安全契约：包含关系（双方≥4）+ 唯一近名才改写。"""
        f = tmp_path / "search.py"
        _write(f, 'sql = "SELECT * FROM trains WHERE train_number = ?"\n')
        ddl = {"trains": ["id", "number", "origin"]}
        fixes = fix_column_drift(tmp_path, ddl)
        assert fixes, "必须检测到列名漂移"
        assert "number" in fixes[0]
        assert "train_number" not in _read(f)

    def test_short_suffix_not_routed(self, tmp_path):
        """keep7 尸体误伤族：user_id/train_id → id（短后缀）必须拒绝。"""
        f = tmp_path / "a.py"
        _write(f, 'sql = "SELECT * FROM users WHERE user_id = ?"\n')
        assert not fix_column_drift(tmp_path, {"users": ["id", "username"]})
        assert "user_id" in _read(f)

    def test_python_kwargs_untouched(self, tmp_path):
        """keep7 尸体误伤族：SQL 字面量外的 Python 代码不许动。"""
        f = tmp_path / "a.py"
        _write(f, 'def f(name="x", note_row=None):\n'
                  '    return query("SELECT * FROM notes WHERE id = ?",\n'
                  '                 note_row)\n')
        fixes = fix_column_drift(
            tmp_path, {"notes": ["id", "username", "label_id"]})
        assert not fixes, "SQL 字面量外的标识符不得改写"
        assert 'name="x"' in _read(f) and "note_row=None" in _read(f)

    def test_no_fix_if_correct(self, tmp_path):
        f = tmp_path / "s.py"
        _write(f, 'sql = "SELECT * FROM trains WHERE id = ?"\n')
        assert not fix_column_drift(tmp_path, {"trains": ["id", "name"]})


class TestImportDrift:
    def test_f1_auth_to_auth(self, tmp_path):
        """keep3 实证缺陷方向：代码猜名 import auth，实际包是 f1_auth。"""
        pkg = tmp_path / "f1_auth"; pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "f1_auth.py").write_text("def register(): pass\n")
        web = tmp_path / "web_ui"; web.mkdir()
        _write(web / "__init__.py", "")
        f = web / "web_ui.py"
        _write(f, "from auth import register\n")
        fixes = fix_import_drift(tmp_path)
        assert fixes, "import 路径漂移必须被检测到"
        assert "f1_auth" in _read(f), "必须重写为实际包名"

    def test_rewrite_keeps_imported_names(self, tmp_path):
        """9/23 交付 05 尸检：旧实现重写时把名字清单整个丢掉，产出
        `from link_creation import`——语法错让整棵 import 树全灭，启动器
        0 候选 = 官方容器 exit 1（不评分），比它要修的漂移严重一个量级。
        上一条测试只断言「包名换了」，所以这个自伤通道一路绿灯。"""
        import ast

        pkg = tmp_path / "f1_auth"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "f1_auth.py").write_text("def register(): pass\n")
        web = tmp_path / "web_ui"
        web.mkdir()
        _write(web / "__init__.py", "")
        f = web / "web_ui.py"
        _write(f, "from auth import register, login_url as lu\n")
        fix_import_drift(tmp_path)
        src = _read(f)
        ast.parse(src)                       # 修完必须仍是合法 Python
        assert "register" in src and "login_url as lu" in src

    def test_clean_imports_untouched(self, tmp_path):
        pkg = tmp_path / "auth"; pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        web = tmp_path / "web_ui"; web.mkdir()
        _write(web / "__init__.py", "")
        f = web / "web_ui.py"
        _write(f, "from auth import register\n")
        assert not fix_import_drift(tmp_path)


class TestSubmoduleBinding:
    def test_binding_added(self, tmp_path):
        pkg = tmp_path / "seed_data"; pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "seed_data.py").write_text("SEED = 1\n")
        fixes = fix_submodule_binding(tmp_path)
        assert fixes
        assert "from . import seed_data" in _read(pkg / "__init__.py")


class TestBlueprintRegistry:
    def test_missing_bp_registered(self, tmp_path):
        pkg = tmp_path / "search_mod"; pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "search_mod.py").write_text(
            'from flask import Blueprint\nbp = Blueprint("search", __name__)\n')
        asm = tmp_path / "main_app.py"
        _write(asm,
               "from flask import Flask\n"
               "def create_app():\n"
               "    app = Flask(__name__)\n"
               "    return app\n")
        fixes = fix_blueprint_registry(tmp_path)
        assert fixes, "Blueprint 未注册必须被检测到"

    def test_already_registered_no_fix(self, tmp_path):
        asm = tmp_path / "main.py"
        _write(asm, 'from flask import Flask\napp = Flask(__name__)\napp.register_blueprint(bp)\n')
        assert not fix_blueprint_registry(tmp_path)


class TestSharedPackageAndDdlShape:
    """keep7 取证：_shared 是合法公共层包名；collect_ddl 返回嵌套
    dict，run_all_fixers 必须归一化后使用。"""

    def test_underscore_pkg_visible_to_import_drift(self, tmp_path):
        from app.utils.auto_fixer import fix_import_drift
        pkg = tmp_path / "_shared"; pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "hashing.py").write_text("def md5(s): return s\n",
                                        encoding="utf-8")
        web = tmp_path / "web_ui"; web.mkdir()
        (web / "__init__.py").write_text("", encoding="utf-8")
        f = web / "web_ui.py"
        _write(f, "from shared import md5\n")   # 猜名 shared，实际 _shared
        fixes = fix_import_drift(tmp_path)
        assert fixes, "_shared 包必须参与近名匹配"
        assert "_shared" in _read(f)

    def test_run_all_fixers_accepts_nested_ddl(self, tmp_path):
        from app.utils.auto_fixer import run_all_fixers
        f = tmp_path / "search.py"
        _write(f, 'sql = "SELECT * FROM trains WHERE train_number = ?"\n')
        # 嵌套形态（schema_audit.collect_ddl 原样输出）
        nested = {"trains": {"columns": ["id", "number"],
                             "sources": ["schema.py:1"]}}
        results = run_all_fixers(tmp_path, nested)
        assert results.get("列名漂移"), "嵌套 DDL 必须被归一化后使用"
        assert "train_number" not in _read(f)


class TestStdlibShadowAndMissingModule:
    """keep7 尸体取证：re.py 遮蔽标准库；`from _shared.db import` 点
    路径漂移需符号路由。"""

    def test_stdlib_shadow_shim_removed(self, tmp_path):
        from app.utils.auto_fixer import fix_stdlib_shadow
        shim = tmp_path / "re.py"
        _write(shim, "# Auto shim（命名漂移机械修复）：re ⇒ data_core\nx = 1\n")
        human = tmp_path / "json.py"
        _write(human, "MY_JSON = 1\n")   # 无标记的人写文件不许动
        fixes = fix_stdlib_shadow(tmp_path)
        assert not shim.exists(), "遮蔽标准库的自动垫片必须删除"
        assert human.exists(), "人写文件不许动"
        assert any("re.py" in f for f in fixes)

    def test_missing_module_full_route(self, tmp_path):
        from app.utils.auto_fixer import fix_missing_module
        dc = tmp_path / "data_core"; dc.mkdir()
        (dc / "__init__.py").write_text("", encoding="utf-8")
        (dc / "data_core.py").write_text(
            "def get_db(): pass\ndef query_db(q): pass\n",
            encoding="utf-8")
        st = tmp_path / "settings"; st.mkdir()
        (st / "__init__.py").write_text("", encoding="utf-8")
        f = st / "settings.py"
        _write(f, "from _shared.db import get_db, query_db\n")
        fixes = fix_missing_module(tmp_path)
        assert fixes, "点路径漂移必须被检测"
        assert "from data_core.data_core import get_db, query_db" in _read(f)

    def test_missing_module_partial_emits_finding_only(self, tmp_path):
        from app.utils.auto_fixer import fix_missing_module
        dc = tmp_path / "data_core"; dc.mkdir()
        (dc / "__init__.py").write_text("", encoding="utf-8")
        (dc / "data_core.py").write_text(
            "def get_db(): pass\n", encoding="utf-8")
        st = tmp_path / "settings"; st.mkdir()
        (st / "__init__.py").write_text("", encoding="utf-8")
        f = st / "settings.py"
        _write(f, "from _shared.db import get_db, current_user_id\n")
        fixes = fix_missing_module(tmp_path)
        assert any("[发现]" in x and "current_user_id" in x for x in fixes), \
            "部分符号无定义必须产出精确发现"
        assert "from _shared.db" in _read(f), "无法全量路由时不得改写"

    def test_placeholder_none_never_routed(self, tmp_path):
        from app.utils.auto_fixer import fix_missing_module
        pkg = tmp_path / "search"; pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "search.py").write_text("DB_PATH = None\n", encoding="utf-8")
        st = tmp_path / "settings"; st.mkdir()
        (st / "__init__.py").write_text("", encoding="utf-8")
        f = st / "settings.py"
        _write(f, "    from _shared.db import DB_PATH\n")
        fixes = fix_missing_module(tmp_path)
        assert not any("search.search" in x for x in fixes), \
            "None 占位不得作为路由目标"

    def test_shim_generator_skips_stdlib(self, tmp_path):
        import sys as _sys
        from app.arcbench_smoke import auto_shim_imports
        dc = tmp_path / "data_core"; dc.mkdir()
        (dc / "__init__.py").write_text("", encoding="utf-8")
        (dc / "data_core.py").write_text("X = 1\n", encoding="utf-8")
        app_f = tmp_path / "app_main.py"
        _write(app_f, "import re\nfrom data_core import X\n")
        shims = auto_shim_imports(tmp_path)
        assert "re" not in shims, "标准库名绝不生成垫片"
        assert not (tmp_path / "re.py").exists()
