# -*- coding: utf-8 -*-
"""拼接机械化（v8 P0-a）：AST 扫描模块蓝图/初始化函数，确定性生成
app_main 的 create_app——组装是确定性工作，不交给概率。

取证（2026-09-20 BookStack 本地首跑）：LLM 组装的产物 = 空壳 create_app
（仅 /static）+ 幻觉导入的 main.py + 全库 0 处 /api/health，3 个模块
修复耗尽冻结——拼接失败是 2/34 的第一根因，非交互层。

生成物（幂等覆盖 app_main/app_main.py）：
- create_app：注册全部 Blueprint（保留其自带 url_prefix）+ 调用全部
  init_* 种子/初始化函数 + 保底 /api/health（不存在时补）
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModuleSurface:
    name: str                       # 包名（可导入名）
    blueprints: list[tuple[str, str]] = field(default_factory=list)  # (file_stem, var)
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
                        fn = getattr(call.func, "id", "")
                        if fn == "Blueprint":
                            surface.blueprints.append((py.stem, t.id))
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
    """扫全部包：Blueprint 变量与 init_* 函数清单（跳过 _shared/_*）。"""
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
        if surface.blueprints or surface.inits:
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
from flask import Flask, jsonify

{chr(10).join(imports)}


def create_app() -> Flask:
    app = Flask(__name__)

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


def assemble(code_dir: Path) -> dict:
    """扫描 + 生成 app_main。返回摘要（幂等：重复调用覆盖同文件）。"""
    code_dir = Path(code_dir)
    surfaces = scan_surfaces(code_dir)
    content = generate_app_main(surfaces)
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
        "modules": [s.name for s in surfaces],
        "blueprints": sum(len(s.blueprints) for s in surfaces),
        "inits": sum(len(s.inits) for s in surfaces),
        "parse_errors": [f"{s.name}/{e}" for s in surfaces for e in s.parse_errors],
        "file": str(target / "app_main.py"),
    }
