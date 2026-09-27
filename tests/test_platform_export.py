# -*- coding: utf-8 -*-
"""官方 runner 布局适配器回归（6 平台提交取证：布局违约主死因）。"""
from __future__ import annotations

import json
import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from app.platform_export import export_platform_layout


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "proj"
    code = proj / "code"
    (code / "view").mkdir(parents=True)
    (code / "view" / "__init__.py").write_text("", encoding="utf-8")
    (code / "view" / "view.py").write_text(
        "def create_app():\n    pass\n", encoding="utf-8")
    static = code / "view" / "static"
    static.mkdir()
    (static / "style.css").write_text("body{}", encoding="utf-8")
    return proj


def test_backend_layout_complete(tmp_path, project):
    out = tmp_path / "out"
    summary = export_platform_layout(out, project)
    backend = out / "backend"
    assert (backend / "main.py").is_file()
    assert (backend / "requirements.txt").is_file()
    assert (backend / "package.json").is_file()
    assert (backend / "view" / "view.py").is_file()
    assert (backend / "view" / "static" / "style.css").is_file(), \
        "非 py 资产必须随迁"
    assert summary["backend_files"] >= 5


def test_backend_entry_has_port_and_health_contract(tmp_path, project):
    out = tmp_path / "out"
    export_platform_layout(out, project)
    entry = (out / "backend" / "main.py").read_text(encoding="utf-8")
    assert 'os.environ.get("PORT"' in entry
    assert "create_app" in entry


def test_start_command_and_bind_match_official_runner(tmp_path, project):
    """官方启动姿势（本地模拟材料的 entrypoint 实测）：cd backend →
    PORT=<runtime port> npm run start → curl http://127.0.0.1:<port>
    /api/health。任何一环对不上都是 runtime_unhealthy 全场零分，
    所以这三条写死成契约而不是靠人工核对。"""
    out = tmp_path / "out"
    export_platform_layout(out, project)
    pkg = json.loads((out / "backend" / "package.json").read_text(
        encoding="utf-8"))
    assert "start" in pkg["scripts"], "runner 只认 npm run start"
    assert "main.py" in pkg["scripts"]["start"]
    entry = (out / "backend" / "main.py").read_text(encoding="utf-8")
    assert 'host="0.0.0.0"' in entry, "绑 127.0.0.1 时容器外探针永远拿不到 200"
    assert '"3301"' in entry, "PORT 缺省值必须与 runner 默认端口一致"


def test_sqlite_runtime_db_never_ships(tmp_path, project):
    """9/23 keep r1 取证：code/notes.db 是自测闸一轮轮改写后的残局，
    随迁即把脏初态交给平台判分（种子重复、被测行缺失），本地却因同一份
    脏库全绿。运行库必须剥掉，让本地与平台跑在同一个干净初态上。"""
    code = project / "code"
    (code / "notes.db").write_text("dirty test state", encoding="utf-8")
    (code / "notes.db-wal").write_text("w", encoding="utf-8")
    (code / "view" / "app.sqlite3").write_text("d", encoding="utf-8")
    out = tmp_path / "out"
    summary = export_platform_layout(out, project)
    names = {p.name for p in (out / "backend").rglob("*") if p.is_file()}
    assert not ({"notes.db", "notes.db-wal", "app.sqlite3"} & names), names
    assert "style.css" in names, "真资产仍要随迁，剥的只是运行库"
    assert sorted(summary["runtime_data_stripped"]) == \
        ["app.sqlite3", "notes.db", "notes.db-wal"], \
        "剥了什么必须见于日志——否则「数据没了」查不到是谁干的"


def test_frontend_shell_buildable_shape(tmp_path, project):
    out = tmp_path / "out"
    export_platform_layout(out, project)
    pkg = json.loads((out / "frontend" / "package.json").read_text(
        encoding="utf-8"))
    assert "build" in pkg["scripts"], "runner 只构建声明了 build 的前端"
    assert (out / "frontend" / "index.html").is_file()
    assert (out / "frontend" / "src" / "App.tsx").is_file()


def test_export_idempotent(tmp_path, project):
    out = tmp_path / "out"
    export_platform_layout(out, project)
    export_platform_layout(out, project)  # 重复导出不抛错
    assert (out / "backend" / "main.py").is_file()


def test_missing_code_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        export_platform_layout(tmp_path / "out", tmp_path / "noproj")


@pytest.fixture
def fastapi_project(tmp_path):
    proj = tmp_path / "fproj"
    code = proj / "code"
    code.mkdir(parents=True)
    (code / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/api/health')\n"
        "def health():\n    return {'status': 'ok'}\n",
        encoding="utf-8")
    return proj


def test_project_main_preserved_as_project_main(tmp_path, fastapi_project):
    out = tmp_path / "out"
    export_platform_layout(out, fastapi_project)
    backend = out / "backend"
    # FastAPI 风格唯一入口在 main.py——runner 覆盖前必须保真
    assert (backend / "project_main.py").read_text(
        encoding="utf-8").startswith("from fastapi import FastAPI")
    entry = (backend / "main.py").read_text(encoding="utf-8")
    assert "wsgi_app" in entry and "uvicorn" in entry, \
        "runner 必须双框架起服"


def test_requirements_follow_frameworks(tmp_path, fastapi_project):
    out = tmp_path / "out"
    export_platform_layout(out, fastapi_project)
    reqs = (out / "backend" / "requirements.txt").read_text(encoding="utf-8")
    assert "fastapi" in reqs and "uvicorn" in reqs
    assert "flask" not in reqs, "纯 FastAPI 项目不必装 flask"

    # 混合项目（flask+fastapi import 并存）双依赖都要有
    fcode = fastapi_project / "code"
    (fcode / "mixed_pkg").mkdir()
    (fcode / "mixed_pkg" / "__init__.py").write_text("", encoding="utf-8")
    (fcode / "mixed_pkg" / "x.py").write_text(
        "from flask import Flask\n", encoding="utf-8")
    export_platform_layout(out, fastapi_project)
    reqs2 = (out / "backend" / "requirements.txt").read_text(encoding="utf-8")
    assert "fastapi" in reqs2 and "flask" in reqs2


def test_authored_app_entry_beats_create_app_factory(tmp_path):
    """作者入口（模块级 app）必须压过机械装配 create_app 壳——
    否则修复器修好的 main.py 被旁路，修复白做。"""
    import importlib.util

    from app.platform_export import _BACKEND_MAIN

    be = tmp_path / "backend"
    be.mkdir()
    # 机械装配壳：只有 health
    (be / "app_main").mkdir()
    (be / "app_main" / "__init__.py").write_text("", encoding="utf-8")
    (be / "app_main" / "app_main.py").write_text(
        "from flask import Flask, jsonify\n"
        "def create_app():\n"
        "    app = Flask(__name__)\n"
        "    @app.route('/api/health')\n"
        "    def h():\n"
        "        return jsonify(status='ok')\n"
        "    return app\n", encoding="utf-8")
    # 作者入口：模块级 app，带业务路由
    (be / "project_main.py").write_text(
        "from flask import Flask, jsonify\n"
        "app = Flask(__name__)\n"
        "AUTHORED = True\n"
        "@app.route('/api/health')\n"
        "def h():\n"
        "    return jsonify(status='ok')\n"
        "@app.route('/books')\n"
        "def books():\n"
        "    return jsonify([])\n", encoding="utf-8")
    (be / "main.py").write_text(_BACKEND_MAIN, encoding="utf-8")

    spec = importlib.util.spec_from_file_location("runner_main", be / "main.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)      # 模块级执行即完成入口探测
        assert mod.app.name == "project_main", \
            "可导入的作者入口必须赢过 create_app 工厂"
        rules = {r.rule for r in mod.app.url_map.iter_rules()}
        assert "/books" in rules
    finally:
        # walker 把 app_main/project_main 等灌进了共享 sys.modules，
        # 不清会污染后续测试的同名导入（跨文件隔离取证）
        for name in list(sys.modules):
            if name.startswith(("app_main", "project_main", "runner_main")):
                sys.modules.pop(name, None)


# ---- 出口入口保底（9/23 keep r0 真产物取证）------------------------------
# 那份交付的整棵树里没有任何 create_app，也没有模块级 app：官方 runner 的
# 入口探测两遍全空 → SystemExit → 容器 exit 1 = **不评分**。首页写得再好
# 也换不到一分，而管线当时还「尽力交付」成功了——这一层不能交给概率。

@pytest.fixture
def entryless_project(tmp_path):
    proj = tmp_path / "eproj"
    code = proj / "code"
    (code / "records").mkdir(parents=True)
    (code / "records" / "__init__.py").write_text("", encoding="utf-8")
    (code / "records" / "records.py").write_text(
        "from flask import Blueprint\n"
        "bp = Blueprint('records', __name__)\n"
        "@bp.route('/records')\n"
        "def page():\n    return 'records page'\n", encoding="utf-8")
    return proj


def test_missing_entry_is_backfilled_at_export(tmp_path, entryless_project):
    out = tmp_path / "out"
    summary = export_platform_layout(out, entryless_project)
    assert summary["entry"] == "mechanical", "出口必须报告入口是保底壳"
    assert (out / "backend" / "app_main" / "app_main.py").is_file()
    reqs = (out / "backend" / "requirements.txt").read_text(encoding="utf-8")
    assert "flask" in reqs, "保底壳 import flask，依赖表得跟着补（缺=部署即死）"


def test_backfilled_artifact_boots_with_business_routes(tmp_path,
                                                        entryless_project):
    """保底不是「只求活着」：扫到的 Blueprint 必须真挂上，否则产物只剩
    /api/health，评测仍按可见文案全灭。"""
    import importlib.util

    out = tmp_path / "out"
    export_platform_layout(out, entryless_project)
    be = out / "backend"
    spec = importlib.util.spec_from_file_location(
        "runner_main_backfill", be / "main.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)          # 模块级执行即完成入口探测
        rules = {r.rule for r in mod.app.url_map.iter_rules()}
        assert "/records" in rules and "/api/health" in rules, rules
        assert mod.app.secret_key, "保底壳缺 secret_key：session 登录必 500"
    finally:
        for name in list(sys.modules):
            if name.startswith(("app_main", "records", "runner_main")):
                sys.modules.pop(name, None)


def test_author_entry_is_never_shadowed(tmp_path, project):
    """作者入口**跑得起来**时保底必须让位——修复成果不许被壳旁路。"""
    (project / "code" / "view" / "view.py").write_text(
        "from flask import Flask\n\n"
        "def create_app():\n    return Flask(__name__)\n", encoding="utf-8")
    out = tmp_path / "out"
    summary = export_platform_layout(out, project)
    assert summary["entry"] == "author"
    assert not (out / "backend" / "app_main").exists(), \
        "作者入口在场时装配保底必须让位，不得旁路修复成果"


def test_dead_author_entry_gets_a_shell_instead_of_exit1(tmp_path, project):
    """批次#63 改判：`def create_app(): pass` 这种「文字在场、工厂返回 None」
    的产物，runner 拿不到应用 → exit 1 → 整跑不评分。旧口径按文本判「有入口」
    所以不兜底；现按真导入探测判，必须装配保底壳换一次可评分终态。"""
    out = tmp_path / "out"
    summary = export_platform_layout(out, project)
    assert summary["entry"] == "mechanical", \
        "跑不起来的作者入口不再被当成入口——否则交付出去还是 exit 1"
    assert (out / "backend" / "app_main" / "app_main.py").is_file()
    shell = (out / "backend" / "app_main" / "app_main.py").read_text(
        encoding="utf-8")
    assert "__arcbench_assembled__ = True" in shell, \
        "壳必须带标记：作者把入口修好后它自动让位"


def test_broken_package_cannot_abort_entry_discovery(tmp_path, project):
    """walk-abort（批次#49 记过名，9/24 重测对照集仍有份这么死）：一个语法错的
    包会把 `pkgutil.walk_packages` 的迭代器当场炸穿，好模块一起陪葬。
    启动器改成自己走目录树（iter_modules 只列名不导入）后，坏包只能杀自己。"""
    import os
    import socket
    import subprocess
    import sys
    import time
    import urllib.request

    bad = project / "code" / "brokentool"
    bad.mkdir()
    # 坏在 __init__.py 上：walk_packages 要 import 父包才能下潜，异常从迭代器
    # 内部抛出、直接炸穿 for 循环——后面的好模块与保底壳一个字都扫不到。
    (bad / "__init__.py").write_text("def oops(:\n    pass\n", encoding="utf-8")
    (bad / "bad.py").write_text("X = 1\n", encoding="utf-8")
    (project / "code" / "view" / "view.py").write_text(
        "from flask import Blueprint, render_template_string\n"
        "bp = Blueprint('view', __name__)\n"
        "@bp.route('/')\n"
        "def home():\n"
        "    return '<html><body><button>Go</button></body></html>'\n",
        encoding="utf-8")
    out = tmp_path / "out"
    export_platform_layout(out, project)
    backend = out / "backend"
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    log = open(backend / "boot.log", "wb")
    proc = subprocess.Popen([sys.executable, "main.py"],
                            cwd=backend, env={**os.environ, "PORT": str(port)},
                            stdout=log, stderr=subprocess.STDOUT)
    try:
        health = None
        deadline = time.time() + 30
        while time.time() < deadline and health is None:
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                    health = r.status
            except Exception:
                time.sleep(0.4)
        assert health == 200, "语法错的包拖垮了整棵树的入口发现（walk-abort）"
        tmpl = (backend / "main.py").read_text(encoding="utf-8")
        assert "pkgutil.walk_packages(" not in tmpl, \
            "启动器又用回 walk_packages：它在下潜时 import 父包，坏包能连坐整棵树"
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


# ---- 产物依赖自举（9/23 官方 entrypoint 取证）------------------------------
# 判分容器只跑 `arc compile → cd backend && npm run start`：没有任何一步替
# 产物 pip install，而镜像 /opt/venv 的依赖来自编译器 requirements
# （openai/pydantic/langchain 一族），flask/fastapi/uvicorn 一个都没有。
# 缺依赖的产物整棵树 import 全灭 → 60 秒健康探针必超时 → exit 1 不评分，
# 且 stderr 与「没有入口」长得一模一样。入口由出口保底兜死，依赖由启动
# 入口原地补装兜活——两头都要确定性抓手，不能交给镜像运气。

# 伪安装器：装「成功」时落一个可导入模块（入口随之复活），并把每次调用
# 记进日志——「试了哪几种装法、按什么顺序」因此是可断言事实，不是注释承诺。
_INSTALLER_STUB = '''\
import json
import os
import sys


def run(tool, rc_env):
    log = os.environ.get("FAKE_INSTALL_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"tool": tool, "argv": sys.argv[1:]}) + "\\n")
    rc = int(os.environ.get(rc_env, "1"))
    target = os.environ.get("FAKE_INSTALL_WRITE")
    if rc == 0 and target:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(
                "class _App:\\n"
                "    bootstrapped = True\\n"
                "    routes = ['GET /health']\\n"
                "    def __call__(self):\\n"
                "        return self\\n"
                "\\n"
                "def make_app():\\n"
                "    return _App()\\n")
    return rc


sys.exit(run("__TOOL__", "__RC_ENV__"))
'''


class _Installer:
    """`python -m pip` 与 `uv` 的可控伪件（默认全失败：忘记配置 ≠ 偷偷成功）。"""

    def __init__(self, root, log, monkeypatch):
        self.root, self._log, self._mp = root, log, monkeypatch
        self.reset()

    def reset(self):
        self._mp.setenv("FAKE_PIP_RC", "1")
        self._mp.setenv("FAKE_UV_RC", "1")
        self._mp.delenv("FAKE_INSTALL_WRITE", raising=False)

    def install_ok(self, tool, *, name="pip"):
        """让 `tool` 这一档安装成功，并把伪模块写到 `name`。"""
        self._mp.setenv(f"FAKE_{tool.upper()}_RC", "0")
        self._mp.setenv("FAKE_INSTALL_WRITE", str(name))

    def attempts(self):
        if not self._log.exists():
            return []
        return [json.loads(line) for line in
                self._log.read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture
def installer(tmp_path, monkeypatch):
    """PYTHONPATH 先于 site-packages 解析（实测 `python -m pip` 命中伪件），
    PATH 前置 bin/ 遮蔽 uv——两种装法都在被测代码之外，测试说了算。"""
    root = tmp_path / "installer"
    (root / "pip").mkdir(parents=True)
    (root / "pip" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pip" / "__main__.py").write_text(
        _INSTALLER_STUB.replace("__TOOL__", "pip").replace("__RC_ENV__",
                                                           "FAKE_PIP_RC"),
        encoding="utf-8")
    bindir = root / "bin"
    bindir.mkdir()
    uv = bindir / "uv"
    uv.write_text(
        "#!" + sys.executable + "\n"
        + _INSTALLER_STUB.replace("__TOOL__", "uv").replace("__RC_ENV__",
                                                            "FAKE_UV_RC"),
        encoding="utf-8")
    uv.chmod(0o755)
    monkeypatch.setenv("PYTHONPATH", str(root))
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    log = tmp_path / "install-log.jsonl"
    monkeypatch.setenv("FAKE_INSTALL_LOG", str(log))
    return _Installer(root, log, monkeypatch)


def _dep_missing_backend(tmp_path):
    """backend/ 里唯一模块依赖一个不存在的包，入口随该包一起消失。"""
    from app.platform_export import _BACKEND_MAIN

    be = tmp_path / "backend"
    (be / "svc").mkdir(parents=True)
    (be / "svc" / "__init__.py").write_text("", encoding="utf-8")
    (be / "svc" / "svc.py").write_text(
        "import zzzwebkit\n"
        "app = zzzwebkit.make_app()\n", encoding="utf-8")
    (be / "requirements.txt").write_text("zzzwebkit\n", encoding="utf-8")
    (be / "main.py").write_text(_BACKEND_MAIN, encoding="utf-8")
    return be


def _plain_backend(tmp_path, body, name="solo"):
    """一个依赖齐全、能直接跑完探测的 backend/。"""
    from app.platform_export import _BACKEND_MAIN

    be = tmp_path / "backend"
    be.mkdir()
    (be / f"{name}.py").write_text(body, encoding="utf-8")
    (be / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (be / "main.py").write_text(_BACKEND_MAIN, encoding="utf-8")
    return be


def _exec_entry(be, name):
    """以独立模块名执行产物启动入口，并还原它对 sys.path/sys.modules 的改动。

    必须还原：入口把 backend/ 插进了 sys.path，留着会让后续测试在同名包上
    互相串味——假绿比假红难查得多。"""
    import importlib.util

    path_snap = list(sys.path)
    mods_snap = set(sys.modules)
    try:
        spec = importlib.util.spec_from_file_location(name, be / "main.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path[:] = path_snap
        for gone in set(sys.modules) - mods_snap:
            sys.modules.pop(gone, None)


_CALLABLE = (
    "class _A:\n"
    "    def __call__(self):\n"
    "        return self\n"
    "\n"
    "app = _A()\n")


def test_bootstrap_revives_entry_and_tries_cheapest_install_first(
        tmp_path, installer, capsys):
    be = _dep_missing_backend(tmp_path)
    installer.install_ok("pip", name=be / "zzzwebkit.py")
    try:
        mod = _exec_entry(be, "runner_main_bootstrap")
    except SystemExit as exc:
        pytest.fail(f"依赖自举后仍未复活入口: {exc}")
    assert "依赖已自举" in capsys.readouterr().out
    assert getattr(mod.app, "bootstrapped", None) is True, \
        "重探必须拿到装完依赖后才可导入的作者入口"
    got = installer.attempts()
    assert [a["tool"] for a in got] == ["pip"], \
        f"裸 pip 成功就不该再试更贵的装法: {got}"


def test_bootstrap_falls_back_to_uv_when_pip_is_absent(tmp_path, installer):
    """官方 reproduction 镜像的 /opt/venv 由 `uv venv` 建立、默认不带 pip：
    `python -m pip` 必 rc=1，此时 uv 是唯一活路，梯子必须走到第二档。"""
    be = _dep_missing_backend(tmp_path)
    installer.install_ok("uv", name=be / "zzzwebkit.py")
    try:
        mod = _exec_entry(be, "runner_main_uv")
    except SystemExit as exc:
        pytest.fail(f"uv 兜底未生效: {exc}")
    assert getattr(mod.app, "bootstrapped", None) is True
    assert [a["tool"] for a in installer.attempts()] == ["pip", "uv"]


def test_uninstallable_deps_report_truth(tmp_path, installer, capsys):
    """装不动（无网 / 镜像里根本没有安装器）必须如实报缺依赖，不得假装成功。"""
    be = _dep_missing_backend(tmp_path)
    with pytest.raises(SystemExit) as got:
        _exec_entry(be, "runner_main_dead")
    msg = str(got.value)
    assert "missing imports" in msg and "zzzwebkit" in msg, msg
    assert "NOT bootstrapped" in msg, msg
    assert "依赖已自举" not in capsys.readouterr().out
    ladder = [(a["tool"], "--break-system-packages" in a["argv"])
              for a in installer.attempts()]
    assert ladder == [("pip", False), ("uv", False),
                      ("pip", True), ("uv", True)], \
        f"梯子必须「常规在前、特例在后」且四档试尽才认输: {ladder}"


def test_no_install_attempt_when_nothing_is_missing(tmp_path, installer):
    """入口在场就走快路：判分容器可能无网，一次徒劳的安装会把 60 秒健康
    预算整段烧掉。"""
    mod = _exec_entry(_plain_backend(tmp_path, _CALLABLE), "runner_main_fast")
    assert mod.app is not None
    assert installer.attempts() == [], "无缺包却动了安装器 = 白烧启动预算"


def test_broken_module_is_not_misdiagnosed_as_missing_dep(tmp_path, installer):
    """代码写坏（非缺包）不得被误诊成依赖问题：坏模块照旧静默跳过，否则
    注定徒劳的 pip 会吃掉健康预算，还顺手掩盖真病因。"""
    be = _plain_backend(tmp_path, "raise ValueError('bad module')\n")
    with pytest.raises(SystemExit) as got:
        _exec_entry(be, "runner_main_broken")
    assert "missing imports" not in str(got.value), str(got.value)
    assert installer.attempts() == [], "坏模块触发安装 = 诊断方向错了"


def test_stdlib_only_gap_never_installs(tmp_path, installer):
    """只缺标准库名时绝不动安装器：装什么都救不回来，却会烧掉起服预算。
    （3.12 才有的标准库**符号**如 itertools.batched 抛的是 ImportError 而非
    ModuleNotFoundError，压根不进 _missing——同样是这条快路。）"""
    be = _plain_backend(tmp_path,
                        "import json.no_such_submodule\napp = 1\n")
    with pytest.raises(SystemExit) as got:
        _exec_entry(be, "runner_main_stdlib")
    assert installer.attempts() == [], "标准库缺口不该动安装器"
    msg = str(got.value)
    assert "missing imports" in msg, f"仍要如实报缺什么: {msg}"
    assert "NOT bootstrapped" not in msg, f"标准库缺口不该归为依赖未装: {msg}"


def test_312_only_stdlib_symbol_is_not_a_dep(tmp_path, installer):
    """3.11 里 `from itertools import batched` 抛 ImportError（不可名状的
    缺名），必须与「缺三方包」分流：前者静默跳过该模块，后者才谈自举。"""
    be = _plain_backend(tmp_path,
                        "from itertools import batched\napp = 1\n")
    with pytest.raises(SystemExit) as got:
        _exec_entry(be, "runner_main_312")
    assert installer.attempts() == []
    assert "missing imports" not in str(got.value)


# ---- 就绪探针保底（9/23 交付路径审计取证 P0-1）------------------------------
# runner 的 60 秒轮询只认 GET /api/health：产物漏写这一条路由，应用本身
# 写得再对也是「无物就绪」→ 整跑不评分。健康检查是布局契约不是业务功能，
# 因此由启动入口在缺位时机械补挂，而应用自带的同名路由一律优先。

def test_health_backfilled_when_author_omits_it(tmp_path, capsys):
    be = _plain_backend(tmp_path, (
        "from flask import Flask, jsonify\n"
        "app = Flask(__name__)\n"
        "@app.route('/')\n"
        "def home():\n    return jsonify(ok=True)\n"))
    mod = _exec_entry(be, "runner_health_backfill")
    rules = {r.rule for r in mod.app.url_map.iter_rules()}
    assert "/api/health" in rules, f"缺 health 必须补挂: {rules}"
    client = mod.app.test_client()
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200, "补挂不该动业务路由"
    assert "补挂" in capsys.readouterr().out, "补挂必须留痕可 grep"


def test_author_health_route_is_not_overwritten(tmp_path, capsys):
    be = _plain_backend(tmp_path, (
        "from flask import Flask, jsonify\n"
        "app = Flask(__name__)\n"
        "@app.route('/api/health')\n"
        "def h():\n    return jsonify(status='ready')\n"
        "@app.route('/')\n"
        "def home():\n    return '<html><body>ok</body></html>'\n"))
    mod = _exec_entry(be, "runner_health_keep")
    assert mod.app.test_client().get("/api/health").get_json() \
        == {"status": "ready"}
    out = capsys.readouterr().out
    assert "/api/health 缺失" not in out
    assert "/ 缺失" not in out


def test_home_backfilled_when_author_omits_it(tmp_path, capsys):
    """e511：作者入口活着 + health 绿，但 / 缺失 → export-probe home-err。"""
    be = _plain_backend(tmp_path, (
        "from flask import Flask, jsonify\n"
        "app = Flask(__name__)\n"
        "@app.route('/api/health')\n"
        "def h():\n    return jsonify(status='ok')\n"
        "@app.route('/api/sheets')\n"
        "def sheets():\n    return jsonify([])\n"))
    mod = _exec_entry(be, "runner_home_backfill")
    rules = {r.rule for r in mod.app.url_map.iter_rules()}
    assert "/" in rules, f"缺 / 必须补挂: {rules}"
    client = mod.app.test_client()
    home = client.get("/")
    assert home.status_code == 200
    body = home.get_data(as_text=True).lower()
    assert "<html" in body or "<body" in body
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/sheets").status_code == 200, "补挂不该动业务路由"
    assert "/ 缺失" in capsys.readouterr().out


def test_weak_home_gains_requirement_anchors(tmp_path):
    """v50 尸检改策：注入只作用于合成兜底页；真实作者页（哪怕是 JSON 空壳）
    一律不动——v50 实证注入把真应用洗成占位页=0/100。锚点 enrich 只发生在
    _ensure_home 的合成页上。"""
    import json

    be = _plain_backend(tmp_path, (
        "from flask import Flask, jsonify\n"
        "app = Flask(__name__)\n"
        "@app.route('/')\n"
        "def home():\n    return jsonify(ok=True)\n"
        "@app.route('/api/health')\n"
        "def h():\n    return jsonify(status='ok')\n"
        "@app.route('/sheets')\n"
        "def sheets():\n    return 'grid'\n"))
    (be / "arcbench_entry.json").write_text(
        json.dumps({"anchors": ["New sheet"]}), encoding="utf-8")
    mod = _exec_entry(be, "runner_entry_wrap")
    body = mod.app.test_client().get("/").get_data(as_text=True)
    # 作者页必须原样活着（不替换、不洗白）
    assert '"ok"' in body and "New sheet" not in body
    assert mod.app.test_client().get("/sheets").get_data(as_text=True) == "grid"


def test_fallback_home_gains_anchors(tmp_path):
    """合成兜底页（有标记）必须被 enrich 成带锚点的可见链接页。"""
    import json

    be = _plain_backend(tmp_path, (
        "from flask import Flask\n"
        "app = Flask(__name__)\n"
        "@app.route('/api/health')\n"
        "def h():\n    return {'status': 'ok'}\n"
        "@app.route('/sheets')\n"
        "def sheets():\n    return 'grid'\n"))
    (be / "arcbench_entry.json").write_text(
        json.dumps({"anchors": ["New sheet"]}), encoding="utf-8")
    mod = _exec_entry(be, "runner_entry_fallback")
    body = mod.app.test_client().get("/").get_data(as_text=True)
    assert 'data-arcbench-fallback="1"' in body
    assert "New sheet" in body and "<a " in body


def test_home_that_already_shows_anchor_is_kept(tmp_path):
    import json

    be = _plain_backend(tmp_path, (
        "from flask import Flask, jsonify\n"
        "app = Flask(__name__)\n"
        "@app.route('/')\n"
        "def home():\n"
        "    return '<html><body><a href=\"/sheets\">New sheet</a></body></html>'\n"
        "@app.route('/api/health')\n"
        "def h():\n    return jsonify(status='ok')\n"))
    (be / "arcbench_entry.json").write_text(
        json.dumps({"anchors": ["New sheet"]}), encoding="utf-8")
    mod = _exec_entry(be, "runner_entry_keep")
    body = mod.app.test_client().get("/").get_data(as_text=True)
    assert "New sheet" in body
    assert "Application" not in body


def test_author_home_route_is_not_overwritten(tmp_path, capsys):
    be = _plain_backend(tmp_path, (
        "from flask import Flask, jsonify\n"
        "app = Flask(__name__)\n"
        "@app.route('/')\n"
        "def home():\n    return '<html><body>author-home</body></html>'\n"
        "@app.route('/api/health')\n"
        "def h():\n    return jsonify(status='ok')\n"))
    mod = _exec_entry(be, "runner_home_keep")
    body = mod.app.test_client().get("/").get_data(as_text=True)
    assert "author-home" in body
    assert "/ 缺失" not in capsys.readouterr().out


# ---- 入口择优与本地冒烟闸同构（9/23 交付路径审计取证 P0-4）------------------
# 旧启动器「模块级 app 非空即返回」把 create_app 工厂池整个丢掉，而本地
# 冒烟闸是同池择优：作者入口由工厂提供、业务包又自带裸自测 app 时，
# 闸测的是真应用、runner 起的是空壳——冒烟全绿而平台首页 404。

def test_factory_entry_beats_stray_bare_app(tmp_path):
    from app.platform_export import _BACKEND_MAIN

    be = tmp_path / "backend"
    (be / "notes").mkdir(parents=True)
    (be / "notes" / "__init__.py").write_text("", encoding="utf-8")
    (be / "notes" / "notes.py").write_text(
        "from flask import Flask\n"
        "app = Flask('notes')\n"
        "@app.route('/ping')\n"
        "def ping():\n    return 'pong'\n", encoding="utf-8")
    (be / "assemble.py").write_text(
        "from flask import Flask\n"
        "def create_app():\n"
        "    a = Flask('assembled')\n"
        "    for i in range(6):\n"
        "        a.add_url_rule('/r%d' % i, 'r%d' % i, lambda: '')\n"
        "    return a\n", encoding="utf-8")
    (be / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (be / "main.py").write_text(_BACKEND_MAIN, encoding="utf-8")
    mod = _exec_entry(be, "runner_pool")
    assert mod.app.name == "assembled", \
        "工厂入口必须与裸自测 app 同池按路由数竞争"


def test_assembled_shell_yields_to_author_entry_even_with_more_routes(
        tmp_path):
    """同池择优带来的新风险必须锁死：保底壳路由更多、名字也更「约定」，
    但作者入口在场时它只能垫后（旧的两遍探测天然保住这条不变量）。"""
    from app.platform_export import _BACKEND_MAIN

    be = tmp_path / "backend"
    be.mkdir()
    (be / "app_main.py").write_text(
        "__arcbench_assembled__ = True\n"
        "from flask import Flask\n"
        "app = Flask('shell')\n"
        "for i in range(9):\n"
        "    app.add_url_rule('/s%d' % i, 's%d' % i, lambda: '')\n",
        encoding="utf-8")
    (be / "project_main.py").write_text(
        "from flask import Flask\n"
        "app = Flask('authored')\n"
        "@app.route('/notes')\n"
        "def notes():\n    return 'ok'\n", encoding="utf-8")
    (be / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (be / "main.py").write_text(_BACKEND_MAIN, encoding="utf-8")
    mod = _exec_entry(be, "runner_shell_yields")
    assert mod.app.name == "authored"


# ---- 导出原子换入（9/23 交付路径审计取证 P0-2）------------------------------
# 旧导出「先 rmtree 再写」：写失败时抢先交付那份能起服的产物也被带走，
# 而调用方对导出失败照常 exit 0——尸检只看得到一次成功的跑。

def test_export_failure_keeps_previous_backend(tmp_path, project,
                                               monkeypatch):
    out = tmp_path / "out"
    export_platform_layout(out, project)
    first = (out / "backend" / "main.py").read_text(encoding="utf-8")
    (out / "backend" / "sentinel.txt").write_text("keep me",
                                                  encoding="utf-8")

    def boom(*args, **kwargs):
        raise RuntimeError("写到一半摔了")

    monkeypatch.setattr("app.platform_export._requirements_for", boom)
    with pytest.raises(RuntimeError):
        export_platform_layout(out, project)
    assert (out / "backend" / "main.py").read_text(encoding="utf-8") == first
    assert (out / "backend" / "sentinel.txt").read_text(
        encoding="utf-8") == "keep me", "在位产物必须整份活到换入那一刻"
    # 换入前的中间态落在点前缀暂存目录里，不污染布局验证
    assert (out / ".export-backend.new").is_dir()


def test_export_probe_reports_health_and_home(tmp_path, project, monkeypatch):
    """v44 P0：终局导出后起服探针——health+首页都绿才算 ok。"""
    monkeypatch.setenv("TB_EXPORT_PROBE", "1")
    monkeypatch.setenv("TB_EXPORT_PROBE_WINDOW", "25")
    out = tmp_path / "out"
    summary = export_platform_layout(out, project)
    probe = summary.get("export_probe") or {}
    assert probe.get("health") is True, probe
    assert probe.get("ok") is True, probe


def test_export_probe_skipped_under_pytest_by_default(tmp_path, project):
    """默认在 pytest 下跳过探针，避免每例烧满窗口。"""
    out = tmp_path / "out"
    summary = export_platform_layout(out, project)
    assert summary.get("export_probe") is None


def test_probe_exported_backend_detects_dead_tree(tmp_path):
    from app.platform_export import probe_exported_backend

    be = tmp_path / "backend"
    be.mkdir()
    (be / "main.py").write_text(
        "import sys\nsys.exit(2)\n", encoding="utf-8")
    probe = probe_exported_backend(be, window_s=5)
    assert probe["health"] is False
    assert probe["ok"] is False
    assert "dead" in probe["detail"] or "no-health" in probe["detail"]

# ---- v48 尸检复现（run 85f404a69443，0/100）--------------------------------
# worksheet_crud 迷你 app 路由数最多但无 /，旧择优让它赢 → 合成保活
# 首页吞掉整场。真 / 在场者必须优先。

def test_home_route_beats_route_count(tmp_path):
    from app.platform_export import _BACKEND_MAIN

    be = tmp_path / "backend"
    be.mkdir()
    (be / "worksheet_crud.py").write_text(
        "from flask import Flask\n"
        "app = Flask('worksheet_crud')\n"
        "for i in range(8):\n"
        "    app.add_url_rule('/ws%d' % i, 'ws%d' % i, lambda: '')\n",
        encoding="utf-8")
    (be / "webapp.py").write_text(
        "from flask import Flask\n"
        "def create_app():\n"
        "    a = Flask('webapp')\n"
        "    a.add_url_rule('/', 'home', lambda: '<h1>real home</h1>')\n"
        "    a.add_url_rule('/workbooks', 'wbs', lambda: 'ok')\n"
        "    return a\n",
        encoding="utf-8")
    (be / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (be / "main.py").write_text(_BACKEND_MAIN, encoding="utf-8")
    mod = _exec_entry(be, "runner_home_first")
    assert mod.app.name == "webapp", \
        "无 / 的候选路由再多也是错门（v48：worksheet_crud 赢择优=0/100）"
    body = mod.app.test_client().get("/").get_data(as_text=True)
    assert "real home" in body
    assert "data-arcbench-fallback" not in body


def test_fallback_home_is_flagged_and_lists_routes(tmp_path):
    """全员无 / 时的保活页必须带判红标记 + 真实路由清单（探针据此
    判 home-is-fallback-shell，不再假绿放行快车道）。"""
    from app.platform_export import _BACKEND_MAIN

    be = tmp_path / "backend"
    be.mkdir()
    (be / "onlymod.py").write_text(
        "from flask import Flask\n"
        "app = Flask('onlymod')\n"
        "@app.route('/workbooks')\n"
        "def wb():\n    return 'ok'\n",
        encoding="utf-8")
    (be / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (be / "main.py").write_text(_BACKEND_MAIN, encoding="utf-8")
    mod = _exec_entry(be, "runner_fallback_flag")
    body = mod.app.test_client().get("/").get_data(as_text=True)
    assert 'data-arcbench-fallback="1"' in body
    assert 'href="/workbooks"' in body, "保活页必须铺真实路由链接"


# ---- v50 尸检复现（run 4376f7aaf644，0/100）--------------------------------
# app_factory 幽灵 import（from auth/sheets import bp，模块不存在）毒死唯一
# 真工厂 → 候选池全员无 / → 路由数捡了 pivot_api 迷你 app → 合成首页。

def test_phantom_import_factory_triggers_blueprint_composition(tmp_path, capsys):
    """工厂被幽灵 import 炸掉时：①日志必须喊出死因；②机械组合 Blueprint
    兜底成真应用，web_ui 的 / 要活着。"""
    from app.platform_export import _BACKEND_MAIN

    be = tmp_path / "backend"
    be.mkdir()
    (be / "app_factory.py").write_text(
        "from flask import Flask\n"
        "def create_app():\n"
        "    from auth import bp as auth_bp\n"      # 幽灵模块
        "    from sheets import bp as sheets_bp\n"  # 幽灵模块
        "    a = Flask('composed_real')\n"
        "    return a\n",
        encoding="utf-8")
    (be / "pivot_api.py").write_text(
        "from flask import Flask\n"
        "app = Flask('pivot_api')\n"
        "for i in range(6):\n"
        "    app.add_url_rule('/p%d' % i, 'p%d' % i, lambda: '')\n",
        encoding="utf-8")
    (be / "web_ui.py").write_text(
        "from flask import Blueprint\n"
        "def create_web_ui_blueprint():\n"
        "    bp = Blueprint('web_ui', __name__)\n"
        "    @bp.route('/')\n"
        "    def home():\n        return '<h1>real ui home</h1>'\n"
        "    return bp\n",
        encoding="utf-8")
    (be / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (be / "main.py").write_text(_BACKEND_MAIN, encoding="utf-8")
    mod = _exec_entry(be, "runner_v50_phantom")
    out = capsys.readouterr().out
    assert "create_app 工厂失败" in out and "auth" in out, out
    body = mod.app.test_client().get("/").get_data(as_text=True)
    assert "real ui home" in body, "蓝图组合必须救回真 UI 首页"
    assert "机械组合" in out, out


def test_injected_entry_page_keeps_fallback_marker(tmp_path):
    """入口文案注入页必须保留 data-arcbench-fallback 标记——v50 实证注入
    替换会洗掉标记骗过探针（假绿）。"""
    from app.platform_export import _BACKEND_MAIN

    be = tmp_path / "backend"
    be.mkdir()
    (be / "onlymod.py").write_text(
        "from flask import Flask\n"
        "app = Flask('onlymod')\n"
        "@app.route('/workbooks')\n"
        "def wb():\n    return 'ok'\n",
        encoding="utf-8")
    (be / "arcbench_entry.json").write_text(
        '{"anchors": ["Q3 Sales"]}', encoding="utf-8")
    (be / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (be / "main.py").write_text(_BACKEND_MAIN, encoding="utf-8")
    mod = _exec_entry(be, "runner_v50_marker")
    body = mod.app.test_client().get("/").get_data(as_text=True)
    assert 'data-arcbench-fallback="1"' in body
    assert "Q3 Sales" in body
