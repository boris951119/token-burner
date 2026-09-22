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
① 模块级 app/application 可调用属性（作者入口优先——pro 修好的
  main.py 若能 import，必须压过机械装配的保底壳，否则修复被旁路）
② 任意模块 create_app() 工厂（机械装配兜底）
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


def _route_count(_cand):
    try:
        if hasattr(_cand, "url_map"):       # Flask/WSGI
            return sum(1 for _ in _cand.url_map.iter_rules())
        return len(getattr(_cand, "routes", []) or [])  # ASGI
    except Exception:
        return 0


_cands = []
for _mod in _iter_mods():                       # ① 模块级 app/application
    _cand = getattr(_mod, "app", None) or getattr(
        _mod, "application", None)
    if (_cand is not None and callable(_cand)
            and not isinstance(_cand, type)):
        _cands.append((_mod.__name__, _cand))
if not _cands:                                  # ② create_app 工厂兜底
    for _mod in _iter_mods():
        if hasattr(_mod, "create_app"):
            try:
                _cand = _mod.create_app()
            except Exception:
                continue                        # 坏工厂跳过，找下一个
            if _cand is not None:
                _cands.append((_mod.__name__, _cand))
if not _cands:
    raise SystemExit("no create_app/app entry found in backend/")
# 9/22 stackoverflow 取证：业务包常自带裸自测 app（有 health 无业务
# 路由），walk_packages 迭代序里抢先当选 → 首页 404 全场团灭。作者
# 入口必须按【路由数最多】择优——装配保底壳路由更少，意图不变。
# 9/22 keep#2 取证：流氓演示模块路由更多时纯路由数会被击败——
# 约定入口名（main/app/project_main/…）优先，池内再比路由数。
_CONVENTION = ("main", "app", "app_main", "project_main",
               "server", "wsgi", "run")
_pref = [_x for _x in _cands if _x[0].lower() in _CONVENTION]
app = max(_pref or _cands, key=lambda _x: _route_count(_x[1]))[1]

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
    """按代码实际 import 推导依赖（写死 flask 会饿死 FastAPI 项目；
    2026-09-21 取证：LLM 用 flask_login 而依赖表没有 → 部署即死）。
    通用规则：stdlib/本地包剔除；已知框架映射版本；其余三方按 pip
    名称归一化直出（pip 对 _/- 大小写自动归一）。"""
    import re
    import sys

    # 顶层单文件模块（seed_data.py）的 import 名是 seed_data（无扩展名），
    # 用 p.name 会永不匹配 → 自己的模块被当三方依赖直写 requirements，
    # 平台 pip 装不上即部署死（Qoder 交叉审查 9/21 取证）
    local_tops: set[str] = set()
    for p in Path(code_dir).iterdir():
        if p.is_dir():
            if not p.name.startswith(".") and p.name != "__pycache__":
                local_tops.add(p.name)
        elif p.is_file() and p.suffix == ".py":
            local_tops.add(p.stem)
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    text = "\n".join(_read(p) for p in _py_files(code_dir))
    tops: set[str] = set()
    for m in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", text, re.M):
        tops.add(m.group(1).split(".")[0])
    third = sorted(t for t in tops
                   if t and t not in stdlib and t not in local_tops)
    deps: list[str] = []
    pins = {
        "flask": "flask>=3.0.0",
        "fastapi": "fastapi>=0.110.0",
        "uvicorn": "uvicorn>=0.29.0",
        "flask_login": "Flask-Login>=0.6.3",
        "flask_sqlalchemy": "Flask-SQLAlchemy>=3.1.1",
        "sqlalchemy": "SQLAlchemy>=2.0.0",
        "PIL": "Pillow>=10.0.0",
    }
    for t in third:
        if t in pins:
            deps.append(pins[t])
        else:
            deps.append(t)   # pip 名称归一化（_ → -，大小写不敏感）
    # 伴随依赖：代码只 import fastapi 不会写 uvicorn，但导出 runner
    # 的 ASGI 起服用的就是 uvicorn——缺它部署即死（9/21 测试取证）
    if any(d.startswith("fastapi") for d in deps) \
            and not any(d.startswith("uvicorn") for d in deps):
        deps.append(pins["uvicorn"])
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
