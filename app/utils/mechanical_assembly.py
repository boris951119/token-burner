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
import sys
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


def _alias_part(surface: ModuleSurface) -> str:
    """别名片段：包名带点时（嵌套包/脚手架给的子包）直接插进标识符会生成
    `_bp_home.sub_web` 这种非法名字——装配产物本身就是 SyntaxError，
    保底壳等于没写。"""
    return surface.name.replace(".", "_")


def _guarded(imp: str, alias: str) -> str:
    """一条 import 配一个 try：坏模块只能杀掉它自己，杀不掉保底壳。

    9/24 对照集实证（26 号）：保底壳已经装配出来了，却因为壳里一句
    `from view_mode import ...` 抛 TypeError 而整个壳一起死——启动器仍然
    「找不到入口」→ exit 1 → 整跑不评分。保底壳的全部价值就在于「服务活着」，
    它自己绝不能被一个坏包带走。
    """
    return (
        f"try:\n"
        f"    {imp}\n"
        f"except Exception as _e:\n"
        f"    {alias} = None\n"
        f"    print(f'[assemble] 跳过 {imp}: {{_e!r}}')"
    )


def generate_app_main(surfaces: list[ModuleSurface]) -> str:
    """生成 app_main/app_main.py 内容（确定性模板）。"""
    imports: list[str] = []
    bp_reg: list[str] = []
    init_calls: list[str] = []
    for s in surfaces:
        for stem, var in s.blueprints:
            imp = _sub_import(s, stem)
            alias = f"_bp_{_alias_part(s)}_{stem}"
            imports.append(_guarded(f"from {imp} import {var} as {alias}",
                                    alias))
            bp_reg.append(
                f"    if {alias} is not None:\n"
                f"        app.register_blueprint({alias})")
        for stem, fn, takes_app in s.inits:
            imp = _sub_import(s, stem)
            alias = f"_init_{_alias_part(s)}_{stem}_{fn}"
            imports.append(_guarded(f"from {imp} import {fn} as {alias}",
                                    alias))
            init_calls.append(
                f"        if {alias} is not None:\n"
                f"            try:\n"
                f"                {alias}({'app' if takes_app else ''})\n"
                f"            except Exception as _e:\n"
                f"                print(f'[assemble] init {fn} 失败: {{_e!r}}')")
        if not s.blueprints and not s.inits:
            imports.append(f"try:\n    import {s.name}\n"
                           f"except Exception:\n    pass  # 保底导入：坏包不连坐")
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
            alias = f"_r_{_alias_part(s)}_{stem}"
            imports.append(_guarded(f"from {imp} import {var} as {alias}",
                                    alias))
            router_reg.append(
                f"    if {alias} is not None:\n"
                f"        app.include_router({alias})")
        for stem, fn, takes_app in s.inits:
            imp = _sub_import(s, stem)
            alias = f"_init_{_alias_part(s)}_{stem}_{fn}"
            imports.append(_guarded(f"from {imp} import {fn} as {alias}",
                                    alias))
            # init 失败不拖死组装：打印后继续（缺种子/建表由冒烟 DDL 比对兜底）
            init_calls.append(
                f"    if {alias} is not None:\n"
                f"        try:\n"
                f"            {alias}({'app' if takes_app else ''})\n"
                f"        except Exception as _e:\n"
                f"            print(f'[assemble] init {fn} 失败: {{_e!r}}')")
        if not s.routers and not s.inits:
            imports.append(f"try:\n    import {s.name}\n"
                           f"except Exception:\n    pass  # 保底导入：坏包不连坐")
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


def assemble(code_dir: Path, scaffold: bool = False,
             exclude: "tuple[str, ...] | list[str]" = ()) -> dict:
    """扫描 + 生成 app_main。返回摘要（幂等：重复调用覆盖同文件）。

    框架甄别：扫到 Blueprint → Flask 模板（现状）；只有 APIRouter →
    FastAPI 模板；两者并存（混合项目）按 Flask——Blueprint 的
    register_blueprint 无法在 FastAPI 里落地，反之 include_router
    同理，取能接上更多模块的那个。
    scaffold=True 时先给冻结包补 Blueprint 存根再扫（契约层 v0）。
    exclude=坏模块包名：把这些包从装配清单里剔除（批次#63「隔离病灶」——
    保底壳若 import 同一个坏包，等于把 exit 1 换了个文件名重写一遍）。
    """
    code_dir = Path(code_dir)
    stubs: list[str] = []
    if scaffold:
        stubs = scaffold_frozen_modules(code_dir, scan_surfaces(code_dir))
    dropped = sorted({str(x) for x in exclude})
    surfaces = [s for s in scan_surfaces(code_dir) if s.name not in dropped]
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
        "excluded": dropped,
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


_PROBE_SRC = '''
import importlib, json, pkgutil, sys
from pathlib import Path

_code = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(_code))
_missing, _dead, _live = set(), {}, []
_mods = []
# 与通用启动器同一套枚举：iter_modules 只列名不导入，坏包杀不掉整棵树
# （pkgutil.walk_packages 在迭代器内部 import，一个语法错的包会连坐全部入口）
_stack, _seen = [(_code, "")], set()
while _stack:
    _base, _pkg = _stack.pop()
    try:
        for _mi in pkgutil.iter_modules([str(_base)]):
            _nm = f"{_pkg}{_mi.name}"
            if _nm in _seen or _nm.startswith(("_", "main", "test")):
                continue
            _seen.add(_nm)
            _mods.append(_nm)
            if _mi.ispkg:
                _stack.append((Path(str(_base)) / _mi.name, _nm + "."))
    except Exception as _exc:
        _dead[f"<enumerate {Path(str(_base)).name}>"] = (
            f"{type(_exc).__name__}: {_exc}")[:160]
for _n in _mods:
    try:
        _mod = importlib.import_module(_n)
    except ModuleNotFoundError as _exc:
        _missing.add(str(getattr(_exc, "name", "") or "").split(".")[0])
        _dead[_n] = f"ModuleNotFoundError: {_exc}"[:160]
        continue
    except Exception as _exc:
        _dead[_n] = f"{type(_exc).__name__}: {_exc}"[:160]
        continue
    _cand = getattr(_mod, "app", None) or getattr(_mod, "application", None)
    if _cand is not None and callable(_cand) and not isinstance(_cand, type):
        _live.append(_n)
    if hasattr(_mod, "create_app"):
        try:
            _made = _mod.create_app()
        except Exception as _exc:
            _dead[_n] = f"create_app(): {type(_exc).__name__}: {_exc}"[:160]
        else:
            if _made is not None:
                _live.append(f"{_n}.create_app")
print(json.dumps({"live": _live, "dead": _dead,
                  "missing": sorted(_missing)}, ensure_ascii=False))
'''


def probe_entries(code_dir: Path, timeout: float = 45.0) -> dict | None:
    """真导入探测：与通用启动器同一套发现规则，报「谁活着/谁炸/缺哪个包」。

    返回 None＝探测本身不可信（超时/子进程炸/输出不合法），调用方按老口径走。
    """
    import json
    import subprocess

    code_dir = Path(code_dir)
    try:
        proc = subprocess.run([sys.executable, "-c", _PROBE_SRC, str(code_dir)],
                              capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None
    lines = [ln for ln in (proc.stdout or "").strip().splitlines() if ln]
    if not lines:
        return None
    try:
        data = json.loads(lines[-1])
    except Exception:
        return None
    if not isinstance(data, dict) or "live" not in data:
        return None
    return {"live": [str(x) for x in data.get("live") or []],
            "dead": {str(k): str(v) for k, v in (data.get("dead") or {}).items()},
            "missing": [str(x) for x in data.get("missing") or []]}


def _stdlib_or_local(name: str) -> bool:
    """缺失名是不是「装包也救不回来」的那一类（标准库/本项目自己的包）。"""
    if name in set(getattr(sys, "stdlib_module_names", ())):
        return True
    return name in {"_shared"}            # 共享层缺失是产物缺陷，不是依赖缺陷


def ensure_entry(code_dir: Path) -> dict | None:
    """入口保底：确认没有活入口时机械装配一个（返回 assemble 摘要）。

    只在最后一道出口调用，不在构建/修复轮次里调用——保底壳与作者入口在
    runner 的择优规则里会打架，作者入口在场时必须原样让位（返回 None）。

    批次#63 改判口径：老版本用「文本里有没有 `def create_app` / `app = Flask(`」
    决定要不要兜，而 40 份对照集里 7 份的全红死法是**文字在场、运行时导入炸**
    （27 号实证：view/search 悬空 import `_shared.notes_store`）——文本扫描看不见
    这件事，于是保底壳没写、启动器 raise SystemExit、整跑不评分。现按真导入探测
    判三种终态：
      ① 探到活入口 → 不动（作者修复永不被旁路）；
      ② 探不到活入口、但缺失名里有第三方包 → 判「依赖没装」的不确定态，沿用旧
         文本口径（`_bootstrap_deps` 那条腿不能被抢：装上就能起来）；
      ③ 探不到活入口也没缺包 → 作者入口确实是坏的，装配保底壳，并把探测到的
         坏包从装配清单里剔除（隔离病灶，不是造内容：壳只挂真能 import 的蓝图）。
    """
    code_dir = Path(code_dir)
    text_entry = has_importable_entry(code_dir)
    probe = probe_entries(code_dir)
    if probe and probe["live"]:
        return None
    if text_entry and (probe is None or any(
            not _stdlib_or_local(m) for m in probe["missing"])):
        return None
    dead_roots = sorted({k.split(".")[0] for k in (probe or {}).get("dead", {})})
    return assemble(code_dir, exclude=dead_roots)
