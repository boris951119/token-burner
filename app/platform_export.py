# -*- coding: utf-8 -*-
"""官方 runner 布局适配器（6 平台提交取证：布局违约是主死因）。

平台 runner 对 web 类产物验证 output_dir 根：必须含 frontend/ 与
backend/ 目录（arc-bench 2026-09 更新）。参考契约（官方 12306 参考实现
+ web-react-fastapi 模板 + README baseline flow）：

- backend/  服务目录，以 PORT 环境变量（默认 3301）启动；
  GET /api/health 200 = 就绪探针；Playwright 打 http://127.0.0.1:3301
- frontend/ Vite 前端；package.json 定义 build 则 runner 会构建
  （构建产物仅作 preview，评测页面来自 backend 服务端口）

我们的 Flask 单体同时服务 API 与页面，因此：
- backend/  = 生成代码全量 + 通用启动入口 main.py（自动发现 create_app）
- frontend/ = 最小可构建 Vite+React 壳（过布局验证与 preview）
评测页面仍由 backend 渲染，与本地 verify 语义一致。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.utils.auto_fixer import _py_files, _read

_BACKEND_MAIN = '''\
"""官方 runner 启动入口：PORT 环境变量（默认 3301），/api/health 就绪。

入口探测两遍（9/20 泛化取证：只认 create_app 会漏掉 FastAPI 风格的
模块级 `app = FastAPI()` 入口——生成的项目两种风格都可能出现）：
① 任意模块 create_app() 工厂
② 任意模块级 app/application 可调用属性
起服：WSGI（有 wsgi_app，Flask）→ app.run；ASGI（FastAPI/Starlette）
→ uvicorn。
"""
import importlib
import os
import pkgutil
import sys
from pathlib import Path

_CODE = Path(__file__).resolve().parent
sys.path.insert(0, str(_CODE))
for _child in sorted(_CODE.iterdir()):
    # keep4 尸检：含 __init__.py 的包目录不得入 path——同名子模块遮蔽包
    if (_child.is_dir() and not _child.name.startswith(("_", "."))
            and not (_child / "__init__.py").exists()):
        sys.path.insert(0, str(_child))


def _iter_mods():
    for _m in pkgutil.walk_packages([str(_CODE)]):
        if _m.name.startswith(("_", "main")):
            continue
        try:
            yield importlib.import_module(_m.name)
        except Exception:
            continue


app = None
for _mod in _iter_mods():                       # ① create_app 工厂
    if hasattr(_mod, "create_app"):
        try:
            _cand = _mod.create_app()
        except Exception:
            continue                            # 坏工厂跳过，找下一个
        if _cand is not None:
            app = _cand
            break
if app is None:                                 # ② 模块级 app 属性
    for _mod in _iter_mods():
        _cand = getattr(_mod, "app", None) or getattr(
            _mod, "application", None)
        if (_cand is not None and callable(_cand)
                and not isinstance(_cand, type)):
            app = _cand
            break

if app is None:
    raise SystemExit("no create_app/app entry found in backend/")

if __name__ == "__main__":
    if hasattr(app, "wsgi_app"):                # Flask/WSGI
        app.run(host="0.0.0.0",
                port=int(os.environ.get("PORT", "3301")),
                threaded=True)
    else:                                       # FastAPI/Starlette ASGI
        import uvicorn
        uvicorn.run(app, host="0.0.0.0",
                    port=int(os.environ.get("PORT", "3301")))
'''

_FRONTEND_PACKAGE_JSON = {
    "name": "frontend",
    "private": True,
    "version": "0.0.0",
    "type": "module",
    "scripts": {
        "dev": "vite",
        "build": "vite build",
        "preview": "vite preview",
    },
    "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
    "devDependencies": {
        "@vitejs/plugin-react": "^4.3.1",
        "vite": "^5.4.0",
    },
}

_FRONTEND_INDEX_HTML = '''\
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>App Preview</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
'''

_FRONTEND_MAIN_TSX = '''\
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
'''

_FRONTEND_APP_TSX = '''\
export default function App() {
  return (
    <main style={{ fontFamily: "system-ui", padding: 24 }}>
      <p>本应用为服务端渲染单体：请访问后端服务端口（默认 3301）。</p>
    </main>
  );
}
'''

_FRONTEND_VITE_CONFIG = '''\
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
});
'''

_BACKEND_PACKAGE_JSON = {
    "name": "backend",
    "private": True,
    "version": "0.0.0",
    "scripts": {"start": "python3 main.py"},
}


def _requirements_for(code_dir: Path) -> str:
    """按代码实际 import 的框架生成依赖（写死 flask 会饿死 FastAPI 项目）。"""
    import re

    text = "\n".join(
        _read(p) for p in _py_files(code_dir))
    deps: list[str] = []
    if re.search(r"^\s*(from fastapi|import fastapi)\b", text, re.M):
        deps += ["fastapi>=0.110.0", "uvicorn>=0.29.0"]
    if re.search(r"^\s*(from flask|import flask)\b", text, re.M):
        deps.append("flask>=3.0.0")
    return "\n".join(deps or ["flask>=3.0.0"]) + "\n"


def export_platform_layout(output_dir: Path, project_dir: Path) -> dict:
    """把生成项目适配导出为官方 runner 布局，返回导出摘要。

    - backend/  = project code 全量（剥离 __pycache__/instance 数据）
                  + 通用启动入口 main.py + requirements.txt + package.json
    - frontend/ = 最小 Vite+React 壳（含 build 脚本）
    幂等：重复导出先清后写。任何子步失败抛异常由调用方决定降级。
    """
    output_dir = Path(output_dir).resolve()
    code_dir = Path(project_dir).resolve() / "code"
    if not code_dir.is_dir():
        raise FileNotFoundError(f"项目无 code 目录: {code_dir}")

    backend = output_dir / "backend"
    frontend = output_dir / "frontend"
    for d in (backend, frontend):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    # --- backend ---
    for src in _py_files(code_dir):
        rel = src.relative_to(code_dir)
        dst = backend / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    # 静态资源/模板等非 py 资产一并随迁（排除运行数据与缓存）
    for src in code_dir.rglob("*"):
        parts = set(src.parts)
        if src.is_dir() or parts & {"__pycache__", "instance", ".git"}:
            continue
        if src.suffix == ".py":
            continue
        rel = src.relative_to(code_dir)
        dst = backend / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    # 项目自身 main.py 会被通用 runner 覆盖——先保 project_main.py
    # （9/20 取证：FastAPI 风格项目唯一入口常在 main.py，直接丢弃
    # = 活代码被 export 弄死；两遍探测的第二遍会扫到它）
    if (code_dir / "main.py").is_file():
        shutil.copy2(code_dir / "main.py", backend / "project_main.py")
    (backend / "main.py").write_text(_BACKEND_MAIN, encoding="utf-8")
    (backend / "requirements.txt").write_text(
        _requirements_for(code_dir), encoding="utf-8")
    (backend / "package.json").write_text(
        json.dumps(_BACKEND_PACKAGE_JSON, indent=2), encoding="utf-8")

    # --- frontend（最小 Vite 壳）---
    (frontend / "package.json").write_text(
        json.dumps(_FRONTEND_PACKAGE_JSON, indent=2), encoding="utf-8")
    (frontend / "vite.config.js").write_text(
        _FRONTEND_VITE_CONFIG, encoding="utf-8")
    (frontend / "index.html").write_text(
        _FRONTEND_INDEX_HTML, encoding="utf-8")
    (frontend / "src").mkdir()
    (frontend / "src" / "main.tsx").write_text(
        _FRONTEND_MAIN_TSX, encoding="utf-8")
    (frontend / "src" / "App.tsx").write_text(
        _FRONTEND_APP_TSX, encoding="utf-8")

    return {
        "backend_files": sum(1 for _ in backend.rglob("*") if _.is_file()),
        "frontend_files": sum(1 for _ in frontend.rglob("*") if _.is_file()),
        "backend": str(backend),
        "frontend": str(frontend),
    }
