# -*- coding: utf-8 -*-
"""拼接机械化回归：Flask Blueprint / FastAPI APIRouter / 混合甄别。

9/20 泛化取证：装配器原为 Flask-only——生成项目出现 FastAPI 风格时
装配全盲（0 路由空壳）。
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.utils.mechanical_assembly import assemble


def _mk_pkg(code: pathlib.Path, name: str, body: str) -> None:
    pkg = code / name
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / f"{name}.py").write_text(body, encoding="utf-8")


FLASK_MOD = """
from flask import Blueprint
bp = Blueprint('x', __name__)
def init_db(app):
    pass
"""

FASTAPI_MOD = """
from fastapi import APIRouter
router = APIRouter()
@router.get('/items')
def items():
    return []
"""


def test_flask_project_assembles_blueprint(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    _mk_pkg(code, "mod", FLASK_MOD)
    info = assemble(code)
    assert info["framework"] == "flask"
    assert info["blueprints"] == 1
    gen = (code / "app_main" / "app_main.py").read_text(encoding="utf-8")
    assert "register_blueprint" in gen
    assert "from flask import Flask" in gen


def test_fastapi_project_assembles_router(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    _mk_pkg(code, "mod", FASTAPI_MOD)
    info = assemble(code)
    assert info["framework"] == "fastapi", "纯 APIRouter 项目必须走 FastAPI 模板"
    assert info["routers"] == 1
    gen = (code / "app_main" / "app_main.py").read_text(encoding="utf-8")
    assert "include_router" in gen
    assert "from fastapi import FastAPI" in gen
    assert '"/api/health"' in gen


def test_fastapi_prefixed_router_import_detected(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    _mk_pkg(code, "mod", FASTAPI_MOD.replace(
        "from fastapi import APIRouter\nrouter = APIRouter()",
        "import fastapi\nrouter = fastapi.APIRouter()"))
    info = assemble(code)
    assert info["routers"] == 1, "fastapi.APIRouter(...) 属性式调用必须扫到"


def test_mixed_project_prefers_flask(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    _mk_pkg(code, "fa", FLASK_MOD)
    _mk_pkg(code, "fb", FASTAPI_MOD)
    info = assemble(code)
    assert info["framework"] == "flask", "并存时 Blueprint 优先（见 assemble 注释）"


def test_generated_fastapi_app_imports_and_serves(tmp_path):
    """端到端：生成物可导入、路由真挂上（TestClient 实行为——
    本仓 FastAPI 版 include_router 摊平为 _IncludedRouter，不能靠
    扫 app.routes 断言）。"""
    code = tmp_path / "code"
    code.mkdir()
    _mk_pkg(code, "mod", FASTAPI_MOD)
    assemble(code)
    # 防跨测试 sys.modules 污染：先清同名残留再导入本例产物
    for name in list(sys.modules):
        if name.startswith(("app_main", "mod")):
            sys.modules.pop(name, None)
    sys.path.insert(0, str(code))
    try:
        from fastapi.testclient import TestClient
        import app_main.app_main as m
        client = TestClient(m.create_app())
        assert client.get("/api/health").status_code == 200
        assert client.get("/items").status_code == 200, \
            "include_router 必须把模块路由真接上"
    finally:
        sys.path.remove(str(code))
        sys.modules.pop("app_main.app_main", None)
        sys.modules.pop("app_main", None)
        sys.modules.pop("mod.mod", None)
        sys.modules.pop("mod", None)


def test_scaffold_creates_stubs_for_frozen_only_and_idempotent(tmp_path):
    """契约层 v0：冻结包得存根；已有路由的包不动；幂等且不覆盖修复器写入。"""
    from app.utils.mechanical_assembly import assemble, scaffold_frozen_modules, scan_surfaces

    code = tmp_path / "code"
    code.mkdir()
    _mk_pkg(code, "frozen_a", "# 无路由定义\n")
    _mk_pkg(code, "authed", FLASK_MOD)          # 已有 Blueprint+init
    # 第一遍：只有 frozen_a 拿存根
    created = scaffold_frozen_modules(code, scan_surfaces(code))
    assert created == ["frozen_a/frozen_a_routes.py"]
    stub = code / "frozen_a" / "frozen_a_routes.py"
    assert "Blueprint" in stub.read_text(encoding="utf-8")
    # 修复器往存根里写了 handler
    stub.write_text(
        stub.read_text(encoding="utf-8")
        + '\n@_bp.route("/a")\ndef a():\n    return "A"\n',
        encoding="utf-8")
    # 第二遍：幂等，不覆盖（修复器内容保留）
    created2 = scaffold_frozen_modules(code, scan_surfaces(code))
    assert created2 == []
    assert '@_bp.route("/a")' in stub.read_text(encoding="utf-8")


def test_assemble_scaffold_registers_stub_and_route_lives(tmp_path):
    """scaffold=True：存根蓝图进 app_main，修复器写入的路由真生效。"""
    from fastapi.testclient import TestClient  # noqa: F401  （flask 路径用 flask client）

    code = tmp_path / "code"
    code.mkdir()
    _mk_pkg(code, "pages", "# 冻结\n")
    assemble(code, scaffold=True)
    # 修复器往存根写页面路由
    stub = code / "pages" / "pages_routes.py"
    stub.write_text(
        stub.read_text(encoding="utf-8")
        + '\n@_bp.route("/pages")\ndef pages():\n    return "PAGES"\n',
        encoding="utf-8")
    # 下一轮脚手架重装配（app_main 再生，存根保留）
    info = assemble(code, scaffold=True)
    assert info["blueprints"] >= 1
    gen = (code / "app_main" / "app_main.py").read_text(encoding="utf-8")
    assert "pages_routes" in gen, "存根蓝图必须注册进 app_main"
    # 行为验证
    for name in list(sys.modules):
        if name.startswith(("app_main", "pages")):
            sys.modules.pop(name, None)
    sys.path.insert(0, str(code))
    try:
        import app_main.app_main as m
        client = m.create_app().test_client()
        assert client.get("/pages").status_code == 200
        assert client.get("/pages").data == b"PAGES"
        assert client.get("/api/health").status_code == 200
    finally:
        sys.path.remove(str(code))
        for name in list(sys.modules):
            if name.startswith(("app_main", "pages")):
                sys.modules.pop(name, None)


def test_scaffold_skips_broken_and_app_main(tmp_path):
    """导入闸：__init__ 链断裂的包不放存根（防毒化 app）；app_main 自身不放。"""
    from app.utils.mechanical_assembly import scaffold_frozen_modules, scan_surfaces

    code = tmp_path / "code"
    code.mkdir()
    # 健康冻结包
    _mk_pkg(code, "healthy", "# 冻结\n")
    # 坏包：__init__ 导入不存在的模块
    bad = code / "bad"
    bad.mkdir()
    (bad / "__init__.py").write_text(
        "from bad.core import *\n", encoding="utf-8")
    # （bad/core.py 不存在 → import bad 必炸）
    # app_main 包（历史上被误放存根）
    am = code / "app_main"
    am.mkdir()
    (am / "__init__.py").write_text("", encoding="utf-8")

    created = scaffold_frozen_modules(code, scan_surfaces(code))
    assert created == ["healthy/healthy_routes.py"], \
        "坏包与 app_main 不得放存根"


# ---- 入口探测（export 出口保假的判据）----------------------------------
# 官方 runner 是 import 而非 run：入口必须**导入期可见**才算数。

def _entry_tree(tmp_path, src: str) -> bool:
    from app.utils.mechanical_assembly import has_importable_entry

    pkg = tmp_path / "code" / "notes"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "notes.py").write_text(src, encoding="utf-8")
    return has_importable_entry(tmp_path / "code")


def test_import_time_entry_counts(tmp_path):
    assert _entry_tree(tmp_path, "from flask import Blueprint\n"
                                 "def create_app():\n    pass\n")
    assert _entry_tree(tmp_path, "from flask import Flask\n"
                                 "app = Flask(__name__)\n")


def test_main_guarded_app_is_not_an_entry(tmp_path):
    """`app = Flask(...)` 缩进在 __main__ 守卫里 = import 后无属性可取，
    runner 两遍探测全空 → exit 1。这种树必须判「无入口」并触发保底装配。"""
    assert not _entry_tree(tmp_path, "from flask import Flask\n"
                                     "if __name__ == '__main__':\n"
                                     "    app = Flask(__name__)\n")


def test_ensure_entry_yields_to_author(tmp_path):
    from app.utils.mechanical_assembly import ensure_entry

    pkg = tmp_path / "code" / "notes"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "notes.py").write_text(
        "from flask import Flask\n\n"
        "def create_app():\n"
        "    return Flask(__name__)\n", encoding="utf-8")
    assert ensure_entry(pkg.parent) is None
    assert not (tmp_path / "code" / "app_main").exists()


def test_ensure_entry_replaces_dead_factory(tmp_path):
    """批次#63 的核心改判：作者入口**文字在场但跑不起来**时必须装配保底壳。

    旧口径只看文本（`def create_app` 在不在），而对照集里 7/40 的全红死法正是
    「文字在、导入炸/工厂返回 None/工厂是模块名」——保底壳没写、启动器
    raise SystemExit、整跑不评分。这里用「工厂返回 None」代表那一类：
    runner 拿不到应用，等同于没有入口。
    """
    from app.utils.mechanical_assembly import ensure_entry

    pkg = tmp_path / "code" / "notes"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "notes.py").write_text("def create_app():\n    pass\n",
                                  encoding="utf-8")
    fix = ensure_entry(pkg.parent)
    assert fix and (tmp_path / "code" / "app_main" / "app_main.py").is_file(), \
        "作者入口跑不起来时必须机械装配，换一次可评分的终态"


def test_ensure_entry_shells_undeclared_missing_local(tmp_path):
    """v44 P0：缺失名不在 requirements.txt → 产物缺陷 → 照常装壳。

    旧口径把未生成的本地包名当成第三方，放弃装壳去 pip → 容器装不上 →
    SystemExit → 不评分。"""
    from app.utils.mechanical_assembly import ensure_entry

    code = tmp_path / "code"
    pkg = code / "notes"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "notes.py").write_text(
        "import ghost_local_pkg\n"
        "from flask import Flask\n"
        "def create_app():\n"
        "    return Flask(__name__)\n", encoding="utf-8")
    (code / "requirements.txt").write_text("flask\n", encoding="utf-8")
    fix = ensure_entry(code)
    assert fix is not None, "未声明的缺失本地名必须触发装壳"
    assert (code / "app_main" / "app_main.py").is_file()
    gen = (code / "app_main" / "app_main.py").read_text(encoding="utf-8")
    assert "_assembled_home" in gen or 'route("/")' in gen


def test_ensure_entry_still_waits_for_declared_third_party(tmp_path):
    """缺失名已写进 requirements.txt → 仍可能是依赖没装，不抢装壳。"""
    from app.utils.mechanical_assembly import ensure_entry

    code = tmp_path / "code"
    pkg = code / "notes"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "notes.py").write_text(
        "import some_weird_dep_xyz\n"
        "from flask import Flask\n"
        "def create_app():\n"
        "    return Flask(__name__)\n", encoding="utf-8")
    (code / "requirements.txt").write_text(
        "flask\nsome_weird_dep_xyz\n", encoding="utf-8")
    assert ensure_entry(code) is None
    assert not (code / "app_main").exists()


def test_mechanical_shell_provides_home_when_no_blueprint_home(tmp_path):
    """保底壳在业务蓝图未挂 / 时必须自带可渲染首页。"""
    from app.utils.mechanical_assembly import assemble

    code = tmp_path / "code"
    code.mkdir()
    pkg = code / "api"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "api.py").write_text(
        "from flask import Blueprint\n"
        "bp = Blueprint('api', __name__)\n"
        "@bp.route('/api/items')\n"
        "def items():\n"
        "    return []\n", encoding="utf-8")
    info = assemble(code)
    assert info["framework"] == "flask"
    gen = (code / "app_main" / "app_main.py").read_text(encoding="utf-8")
    assert "_assembled_home" in gen
    # 真能挂上 /
    import json
    import subprocess
    import sys as _sys

    probe = (
        "import sys, json; sys.path.insert(0, %r)\n"
        "import app_main.app_main as m\n"
        "a = m.create_app()\n"
        "print(json.dumps(sorted(r.rule for r in a.url_map.iter_rules())))\n"
        % str(code)
    )
    res = subprocess.run([_sys.executable, "-c", probe], capture_output=True,
                         text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-400:]
    rules = json.loads(res.stdout.strip().splitlines()[-1])
    assert "/api/health" in rules and "/" in rules


def test_shell_survives_its_own_broken_import(tmp_path):
    """保底壳逐条 import 容错（9/24 对照集 26 号实证）：壳装配出来了，却因为
    壳里一句 `from view_mode import ...` 抛 TypeError 而整个壳一起死——
    启动器仍然「找不到入口」→ exit 1。壳的全部价值就是「服务活着」。"""
    import importlib.util
    from app.utils.mechanical_assembly import ModuleSurface, generate_app_main

    code = tmp_path / "code"
    good = code / "home"
    (good / "sub").mkdir(parents=True)
    (good / "__init__.py").write_text("", encoding="utf-8")
    (good / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (good / "sub" / "web.py").write_text(
        "from flask import Blueprint\nbp = Blueprint('home', __name__)\n"
        "@bp.route('/')\ndef home(): return 'ok'\n", encoding="utf-8")
    surfaces = [
        ModuleSurface(name="home.sub", blueprints=[("web", "bp")],
                      routers=[], inits=[], path=good / "sub"),
        # 作者入口被写成模块名（TypeError: 'module' object is not callable）
        # 那一类：装配清单里引用它，壳必须跳过而不是陪它死
        ModuleSurface(name="ghost", blueprints=[("x", "bp")], routers=[],
                      inits=[], path=code),
    ]
    (code / "app_main").mkdir()
    (code / "app_main" / "__init__.py").write_text("", encoding="utf-8")
    src = generate_app_main(surfaces)
    (code / "app_main" / "app_main.py").write_text(src, encoding="utf-8")
    # 子进程里验：本用例造的包名叫 home/app_main，塞进本进程 sys.modules 会
    # 连坐后面同名的用例（9/24 全量跑里就是这么把 test_package_layout 的自动
    # 垫片用例打成 order-dependent 红的）。
    import json
    import subprocess
    import sys as _sys

    probe = (
        "import sys, json; sys.path.insert(0, %r)\n"
        "import app_main.app_main as m\n"
        "a = m.create_app()\n"
        "print(json.dumps(sorted(r.rule for r in a.url_map.iter_rules())))\n" % str(code)
    )
    res = subprocess.run([_sys.executable, "-c", probe], capture_output=True,
                         text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-400:]
    rules = json.loads(res.stdout.strip().splitlines()[-1])
    assert "/api/health" in rules and "/" in rules, \
        "坏包只能杀掉它自己的那条 import，好蓝图必须挂上"
