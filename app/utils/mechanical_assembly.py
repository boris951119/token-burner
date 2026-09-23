# -*- coding: utf-8 -*-
"""拼接机械化（v8 P0-a）：AST 扫描模块蓝图/路由器/初始化函数，确定性
生成 app_main 的 create_app——组装是确定性工作，不交给概率。

取证（2026-09-20 首跑）：LLM 组装的产物 = 空壳 create_app
（仅 /static）+ 幻觉导入的 main.py + 全库 0 处 /api/health，3 个模块
修复耗尽冻结——拼接失败是 2/34 的第一根因，非交互层。

生成物（幂等覆盖 app_main/app_main.py）：
- Flask 版：注册全部 Blueprint + 调用全部 init_* + 保底 /api/health
- FastAPI 版（9/20 泛化）：include_router 全部 APIRouter + 同上保底；
  框架甄别见 assemble()
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModuleSurface:
    name: str                       # 包名（可导入名）
    blueprints: list[tuple[str, str]] = field(default_factory=list)  # (file_stem, var)
    routers: list[tuple[str, str]] = field(default_factory=list)  # FastAPI (file_stem, var)
    inits: list[tuple[str, str, bool]] = field(default_factory=list)  # (file_stem, func, takes_app)
    parse_errors: list[str] = field(default_factory=list)
    path: Path | None = None


def _scan_package(pkg_dir: Path, name: str) -> ModuleSurface:
    surface = ModuleSurface(name=name, path=pkg_dir)
    for py in sorted(pkg_dir.glob("*.py")):
        if py.name.startswith("_"):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            surface.parse_errors.append(f"{py.name}: {exc}")
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and isinstance(node.value, ast.Call):
                        call = node.value
                        # fastapi.APIRouter() 的 func 是 Attribute，取 attr 名
                        fn = (getattr(call.func, "id", "")
                              or getattr(call.func, "attr", ""))
                        if fn == "Blueprint":
                            surface.blueprints.append((py.stem, t.id))
                        elif fn == "APIRouter":
                            surface.routers.append((py.stem, t.id))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("init_"):
                    args = [a.arg for a in node.args.args]
                    # 签名甄别（2026-09-20 取证：seed_data.init_db 要的是
                    # 连接不是 Flask）——首参叫 app 才传 app；无参则无参
                    # 调用；其他必需参（conn/db...）无法安全调用，跳过
                    takes_app = None
                    if args and "app" in args[0].lower():
                        takes_app = True
                    elif not args:
                        takes_app = False
                    if takes_app is not None:
                        surface.inits.append(
                            (py.stem, node.name, takes_app))
    return surface


def scan_surfaces(code_dir: Path) -> list[ModuleSurface]:
    """扫全部包：Blueprint/APIRouter 变量与 init_* 函数清单（跳过 _shared/_*）。"""
    code_dir = Path(code_dir)
    surfaces: list[ModuleSurface] = []
    for child in sorted(code_dir.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        if child.name == "__pycache__":
            continue
        if not (child / "__init__.py").exists():
            continue
        surface = _scan_package(child, child.name)
        if surface.blueprints or surface.routers or surface.inits:
            surfaces.append(surface)
    return surfaces


def _sub_import(surface: ModuleSurface, stem: str) -> str:
    return f"{surface.name}.{stem}"


def generate_app_main(surfaces: list[ModuleSurface]) -> str:
    """生成 app_main/app_main.py 内容（确定性模板）。"""
    imports: list[str] = []
    bp_reg: list[str] = []
    init_calls: list[str] = []
    for s in surfaces:
        for stem, var in s.blueprints:
            imp = _sub_import(s, stem)
            imports.append(f"from {imp} import {var} as _bp_{s.name}_{stem}")
            bp_reg.append(
                f"    app.register_blueprint(_bp_{s.name}_{stem})")
        for stem, fn, takes_app in s.inits:
            imp = _sub_import(s, stem)
            alias = f"_init_{s.name}_{stem}_{fn}"
            imports.append(f"from {imp} import {fn} as {alias}")
            init_calls.append(
                f"        {alias}({'app' if takes_app else ''})")
        if not s.blueprints and not s.inits:
            imports.append(f"import {s.name}  # noqa: F401  (保底导入)")
    imports = sorted(set(imports))
    return f'''"""机械装配的组装模块（mechanical_assembly 生成，勿手改）。"""
__arcbench_assembled__ = True  # 保底壳标记：入口择优时永不让它压过作者入口

import os

from flask import Flask, jsonify

{chr(10).join(imports)}


def create_app() -> Flask:
    app = Flask(__name__)
    # 组装层自带 secret_key：冒烟闸对「有登录路由却缺 secret_key」判红，
    # 保底壳若不含 session 支持，等于把可修的登录功能判死。
    app.secret_key = os.environ.get("SECRET_KEY", "arcbench-assembled-app")

    @app.route("/api/health")
    def health():
        return jsonify(status="ok")

    with app.app_context():
{chr(10).join(init_calls) if init_calls else "        pass"}

{chr(10).join(bp_reg) if bp_reg else "    pass"}
    return app


def main() -> None:
    create_app().run(host="0.0.0.0", threaded=True)


if __name__ == "__main__":
    main()
'''


def generate_app_main_fastapi(surfaces: list[ModuleSurface]) -> str:
    """FastAPI 版 app_main（9/20 泛化：生成项目可能是 FastAPI 风格，
    APIRouter 与 Blueprint 同构对待——确定性 include_router + 保底 health）。"""
    imports: list[str] = []
    router_reg: list[str] = []
    init_calls: list[str] = []
    for s in surfaces:
        for stem, var in s.routers:
            imp = _sub_import(s, stem)
            imports.append(f"from {imp} import {var} as _r_{s.name}_{stem}")
            router_reg.append(
                f"    app.include_router(_r_{s.name}_{stem})")
        for stem, fn, takes_app in s.inits:
            imp = _sub_import(s, stem)
            alias = f"_init_{s.name}_{stem}_{fn}"
            imports.append(f"from {imp} import {fn} as {alias}")
            # init 失败不拖死组装：打印后继续（缺种子/建表由冒烟 DDL 比对兜底）
            init_calls.append(
                f"    try:\n"
                f"        {alias}({'app' if takes_app else ''})\n"
                f"    except Exception as _e:\n"
                f"        print(f'[assemble] init {fn} 失败: {{_e!r}}')")
        if not s.routers and not s.inits:
            imports.append(f"import {s.name}  # noqa: F401  (保底导入)")
    imports = sorted(set(imports))
    return f'''"""机械装配的组装模块（mechanical_assembly 生成，勿手改）。"""
__arcbench_assembled__ = True  # 入口择优时让位作者入口

from fastapi import FastAPI
from fastapi.responses import JSONResponse

{chr(10).join(imports)}


def create_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return JSONResponse({{"status": "ok"}})

{chr(10).join(init_calls)}

{chr(10).join(router_reg) if router_reg else "    pass"}
    return app


def main() -> None:
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0")


if __name__ == "__main__":
    main()
'''


_STUB_TEMPLATE = '''\
# -*- coding: utf-8 -*-
"""{pkg} 路由存根（mechanical_assembly 契约层生成）。

本模块生成期冻结无路由——修复器直接在本文件写页面路由：
    @bp.route("/…", methods=[…])
    def xxx(): …
（勿改蓝图变量名 bp；app_main 已注册本蓝图，写完即生效）
"""
from flask import Blueprint

bp = Blueprint("{pkg}", __name__)
'''


def scaffold_frozen_modules(code_dir: Path,
                            surfaces: list[ModuleSurface]) -> list[str]:
    """契约层 v0：给无路由定义的冻结包生成 Blueprint 存根文件。

    9/21 取证：pro 反复幻觉 `from app_main.routers import …`——它知道
    该有路由层但不知道落在哪。存根把"往哪写"变成确定性事实：
    每个冻结包一个 <pkg>_routes.py，app_main 注册全部蓝图，修复器
    只需往存根里填 handler。幂等：已有存根不覆盖（保护修复器写入）。
    导入闸（9/21 取证：search/__init__ 链 _shared.infra 缺失，往坏包
    放存根会毒化整个 app）：包本身导不进就不放，留给修复器先修包。
    """
    code_dir = Path(code_dir)
    created: list[str] = []
    have = {s.name for s in surfaces}
    for child in sorted(code_dir.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        if child.name in ("__pycache__", "app_main"):
            continue
        if not (child / "__init__.py").exists():
            continue
        if child.name in have:
            continue
        stub = child / f"{child.name}_routes.py"
        if stub.exists():
            continue
        if not _package_importable(code_dir, child.name):
            continue
        stub.write_text(_STUB_TEMPLATE.format(pkg=child.name),
                        encoding="utf-8")
        created.append(stub.relative_to(code_dir).as_posix())
    return created


def _package_importable(code_dir: Path, pkg: str) -> bool:
    """子进程试导入（隔离，不污染当前解释器）。"""
    import subprocess
    import sys

    try:
        r = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, r'{code_dir}'); import {pkg}"],
            capture_output=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0


def assemble(code_dir: Path, scaffold: bool = False) -> dict:
    """扫描 + 生成 app_main。返回摘要（幂等：重复调用覆盖同文件）。

    框架甄别：扫到 Blueprint → Flask 模板（现状）；只有 APIRouter →
    FastAPI 模板；两者并存（混合项目）按 Flask——Blueprint 的
    register_blueprint 无法在 FastAPI 里落地，反之 include_router
    同理，取能接上更多模块的那个。
    scaffold=True 时先给冻结包补 Blueprint 存根再扫（契约层 v0）。
    """
    code_dir = Path(code_dir)
    stubs: list[str] = []
    if scaffold:
        stubs = scaffold_frozen_modules(code_dir, scan_surfaces(code_dir))
    surfaces = scan_surfaces(code_dir)
    n_bp = sum(len(s.blueprints) for s in surfaces)
    n_r = sum(len(s.routers) for s in surfaces)
    if n_bp == 0 and n_r > 0:
        content = generate_app_main_fastapi(surfaces)
        framework = "fastapi"
    else:
        content = generate_app_main(surfaces)
        framework = "flask"
    compile(content, "app_main_generated", "exec")  # 语法自证
    target = code_dir / "app_main"
    target.mkdir(parents=True, exist_ok=True)
    init_py = target / "__init__.py"
    if not init_py.exists():
        init_py.write_text(
            "from app_main.app_main import *  # noqa: F401,F403\n",
            encoding="utf-8")
    (target / "app_main.py").write_text(content, encoding="utf-8")
    return {
        "framework": framework,
        "modules": [s.name for s in surfaces],
        "blueprints": n_bp,
        "routers": n_r,
        "inits": sum(len(s.inits) for s in surfaces),
        "scaffolded": stubs,
        "parse_errors": [f"{s.name}/{e}" for s in surfaces for e in s.parse_errors],
        "file": str(target / "app_main.py"),
    }


_ENTRY_FACTORY = re.compile(r"^def create_app\b", re.M)
_ENTRY_APP = re.compile(r"^(?:app|application)\s*=\s*[\w.]+\s*\(", re.M)


def has_importable_entry(code_dir: Path) -> bool:
    """官方 runner 导入期能否发现应用入口。

    只认列零（模块级、import 即执行）的 `def create_app` 与
    `app = Flask(...)`：缩进在 `if __name__ == "__main__"` 守卫里的 app
    不算——runner 是 import 不是 run，那种产物在容器里直接 exit 1
    （不评分，比任何 UI 缺陷都贵）。
    """
    for py in sorted(Path(code_dir).rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _ENTRY_FACTORY.search(src) or _ENTRY_APP.search(src):
            return True
    return False


def ensure_entry(code_dir: Path) -> dict | None:
    """入口保底：树里查不到可导入入口时机械装配一个（返回 assemble 摘要）。

    只在最后一道出口调用，不在构建/修复轮次里调用——保底壳与作者入口在
    runner 的择优规则里会打架，作者入口在场时必须原样让位（返回 None）。
    """
    code_dir = Path(code_dir)
    if has_importable_entry(code_dir):
        return None
    return assemble(code_dir)
