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

出口另有一道入口保底：发现树里没有任何可导入入口（作者组装模块缺失）时
机械装配 app_main.create_app 兜底——产物起不来是 exit 1（不评分），比任
何 UI 缺陷都贵，这一层不交给概率。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.utils.auto_fixer import _py_files, _read

_BACKEND_MAIN = '''\
"""官方 runner 启动入口：PORT 环境变量（默认 3301），/api/health 就绪。

入口择优：模块级 `app`/`application` 与 `create_app()` 工厂【同池竞争】，
池内按「约定入口名优先 → 路由数最多」择优（与本地冒烟闸同一套算法，
9/23 审计取证：两套择优算法＝本地绿、平台 404 的错配温床）。
两遍全空且探测期见过「缺三方依赖」时，原地按 backend/requirements.txt
补装一次再探（官方容器不保证替产物装依赖）。
起服前保底挂 GET /api/health：runner 60 秒轮询这条路由，产物漏写 = 整跑
不评分，而「有没有 health」是布局契约而不是业务功能，不该交给概率。
"""
import importlib
import os
import pkgutil
import sys
from pathlib import Path

try:
    # 本启动器的日志有中文，runner 侧捕获 stdout：一次 UnicodeEncodeError
    # 就能把起得来的服务换成崩服，编码问题按环境问题处理，不留给概率。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_CODE = Path(__file__).resolve().parent
sys.path.insert(0, str(_CODE))
for _child in sorted(_CODE.iterdir()):
    # keep4 尸检：含 __init__.py 的包目录不得入 path——同名子模块遮蔽包
    if (_child.is_dir() and not _child.name.startswith(("_", "."))
            and not (_child / "__init__.py").exists()):
        sys.path.insert(0, str(_child))

_missing: set[str] = set()          # 探测期缺失的顶层导入名


def _iter_mods():
    for _m in pkgutil.walk_packages([str(_CODE)]):
        if _m.name.startswith(("_", "main", "test")):
            continue
        try:
            yield importlib.import_module(_m.name)
        except ModuleNotFoundError as _exc:
            # 缺依赖与代码写坏是两种病：前者记下来交给依赖自举，后者
            # 照旧静默跳过（坏模块不得拖累整棵树的入口探测——9/23 walk
            # 语义实证：包名失败后子模块仍会被尝试，父包异常原样重抛）
            _missing.add(str(getattr(_exc, "name", "") or "").split(".")[0])
        except Exception:
            continue


def _route_count(_cand):
    try:
        if hasattr(_cand, "url_map"):       # Flask/WSGI
            return sum(1 for _ in _cand.url_map.iter_rules())
        return len(getattr(_cand, "routes", []) or [])  # ASGI
    except Exception:
        return 0


def _discover():
    """入口候选池：模块级 app 与 create_app() 工厂同池竞争。

    9/20 泛化：只认 create_app 会漏掉 FastAPI 风格的模块级 `app = FastAPI()`；
    9/23 审计取证：原来「①非空即返回」把工厂池整个丢掉，而本地冒烟闸是
    同池择优——作者入口由 create_app() 提供、某个业务包又自带裸自测
    `app = Flask()` 时，本地测真应用、runner 起空壳，冒烟全绿而平台首页 404。
    闸与判分面只能有一套算法：此处与 arcbench_smoke 逐字对齐，择优规则
    （约定名优先→路由数）也在下方共用同一份口径。
    """
    _mods = list(_iter_mods())              # 单次 walk：全树导入只做一遍
    _c = []
    for _mod in _mods:                      # ① 模块级 app/application
        _cand = getattr(_mod, "app", None) or getattr(
            _mod, "application", None)
        if (_cand is not None and callable(_cand)
                and not isinstance(_cand, type)):
            _c.append((_mod.__name__, _cand))
    for _mod in _mods:                      # ② create_app() 工厂同池并进
        if hasattr(_mod, "create_app"):
            try:
                _cand = _mod.create_app()
            except Exception:
                continue                    # 坏工厂跳过，找下一个
            if _cand is not None:
                _c.append((_mod.__name__, _cand))
    return _c


def _third_party_missing():
    """探测期缺失名里真正属于第三方依赖的那部分。

    标准库名不触发装包：解释器版本错配（3.12 语法/新符号）装什么救不回来，
    而产物 requirements.txt 里也不会有它——只报真正的缺包，避免拿一次
    注定徒劳的 40 秒去换必然的超时。"""
    return _missing - set(getattr(sys, "stdlib_module_names", ()))


def _bootstrap_deps():
    """产物依赖自举：官方 reproduction entrypoint 只做
    `arc compile → cd backend && npm run start`，从不 pip install
    backend/requirements.txt——镜像 venv 里也没有 flask（编译器自带依赖
    仅 openai/pydantic/langchain 一族）。缺依赖时整棵树 import 全灭，
    60 秒健康探针必然超时 = 不评分。原地补装一次：有网即活，无网也只是
    回到原来的死法。

    四种解释器形态按「先常规后特例」依次试，各档失败都很快（缺工具/参数
    不认识都不耗网络），只有真在装的那一次会吃时间：
    ① 裸 pip（任何带 pip 的 venv）
    ② uv 装进 --python 所指解释器（官方 reproduction 镜像正是这一形：
       /opt/venv 由 `uv venv` 建、默认不带 pip，`python -m pip` 必失败）
    ③ pip + --break-system-packages（Ubuntu Noble 系统解释器 PEP 668）
    ④ uv + --break-system-packages（uv 指向系统解释器）
    总预算 40 秒：剩下 ~20 秒够 flask 起服，超预算的尝试直接放弃。
    """
    req = _CODE / "requirements.txt"
    if not req.is_file() or not _third_party_missing():
        return False
    import subprocess
    import time

    pip_base = ["install", "--quiet", "--disable-pip-version-check",
                "-r", str(req)]
    uv_base = ["pip", "install", "--quiet", "--python", sys.executable,
               "-r", str(req)]
    plans = [
        [sys.executable, "-m", "pip", *pip_base],
        ["uv", *uv_base],
        [sys.executable, "-m", "pip", *pip_base, "--break-system-packages"],
        ["uv", *uv_base, "--break-system-packages"],
    ]
    deadline = time.monotonic() + 40
    for cmd in plans:
        left = deadline - time.monotonic()
        if left <= 2:
            break
        try:
            # stdin=DEVNULL：装不动时绝不许弹交互提示（无人值守容器里
            # 一次 read 就能把健康预算耗成永久挂起）
            if subprocess.run(cmd, timeout=left, check=False,
                              stdin=subprocess.DEVNULL).returncode == 0:
                print(f"[backend] 依赖已自举: {sorted(_third_party_missing())}",
                      flush=True)
                # 装完清查找器缓存：site-packages 的目录快照解释器启动时
                # 已取过，新落盘的包可能仍不可见
                importlib.invalidate_caches()
                return True
        except FileNotFoundError:
            continue                     # 该工具不存在（如无 uv），试下一种
        except Exception as exc:
            print(f"[backend] 依赖自举尝试失败: {exc!r}"[:200], flush=True)
            continue
    return False


_cands = _discover()
if not _cands and _bootstrap_deps():
    _cands = _discover()          # 装完重探：失败模块不会留在 sys.modules
if not _cands:
    # 尸检要能一眼分清「没入口」和「缺依赖」：keep r0 死法是前者（保底
    # 壳已在导出时兜住），9/23 官方 entrypoint 取证新增后者——镜像不装
    # 产物依赖，缺 flask 与缺入口在 stderr 里长得一模一样。
    _msg = "no create_app/app entry found in backend/"
    if _missing:
        _msg += f" (missing imports: {sorted(_missing)})"
        if _third_party_missing():
            _msg += " [deps NOT bootstrapped: no install attempt succeeded]"
    raise SystemExit(_msg)
# 9/22 stackoverflow 取证：业务包常自带裸自测 app（有 health 无业务
# 路由），walk_packages 迭代序里抢先当选 → 首页 404 全场团灭。作者
# 入口必须按【路由数最多】择优。
# 9/22 keep#2 取证：流氓演示模块路由更多时纯路由数会被击败——
# 约定入口名（main/app/project_main/…）优先，池内再比路由数。
# 9/23 审计取证：同池择优后「保底壳压过作者修好的入口」成了新风险
# （旧的两遍探测天然不会），故壳自带 __arcbench_assembled__ 标记：
# 壳只在其他候选全不在场时才登场，作者修复永不被旁路。
_CONVENTION = ("main", "app", "app_main", "project_main",
               "server", "wsgi", "run")


def _is_shell(_name):
    try:
        return bool(getattr(sys.modules.get(_name),
                            "__arcbench_assembled__", False))
    except Exception:
        return False


_pool = [x for x in _cands if not _is_shell(x[0])] or _cands
_pref = [x for x in _pool if x[0].lower() in _CONVENTION]
app = max(_pref or _pool, key=lambda _x: _route_count(_x[1]))[1]


def _has_health(_a):
    if hasattr(_a, "url_map"):                         # Flask/WSGI
        _paths = [getattr(_r, "rule", "")
                  for _r in _a.url_map.iter_rules()]
    else:                                              # ASGI
        _paths = [getattr(_r, "path", "")
                  for _r in getattr(_a, "routes", []) or []]
    return any(_p in ("/api/health", "/api/health/") for _p in _paths)


def _ensure_health(_a):
    """缺 /api/health 时机械补挂——runner 就绪探针只认这条路由。

    产物漏写它 = 60 秒轮询必然超时 = 整跑不评分，而这条路由不承载任何
    业务语义（应用自带的同名路由一律优先，本函数只在缺席时补位）。
    """
    try:
        if _has_health(_a):
            return
        if hasattr(_a, "url_map"):                     # Flask/WSGI
            _a.add_url_rule("/api/health", "arcbench_health",
                            lambda: {"status": "ok"})
        elif hasattr(_a, "routes"):                    # FastAPI/Starlette ASGI
            def _endpoint(_request):
                from starlette.responses import JSONResponse
                return JSONResponse({"status": "ok"})
            if hasattr(_a, "add_api_route"):
                _a.add_api_route("/api/health", _endpoint, methods=["GET"])
            else:
                _a.router.add_route("/api/health", _endpoint,
                                    methods=["GET"])
        print("[backend] /api/health 缺失，已由启动入口补挂（就绪探针保活）",
              flush=True)
    except Exception as _exc:
        # 保底层自己摔了不能带走应用：能起服就有分，判读留给日志。
        print(f"[backend] /api/health 补挂失败（照常起服）: {_exc!r}"[:200],
              flush=True)


_ensure_health(app)

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


_DB_DATA_EXT = (".db", ".db-journal", ".db-wal", ".db-shm",
                ".sqlite", ".sqlite3",
                ".sqlite-journal", ".sqlite-wal", ".sqlite-shm")


def _is_runtime_data(p: Path) -> bool:
    """ sqlite 运行库判定——这类文件一律不得进交付包。

    9/23 keep r1 取证：导出把 code/notes.db（49KB）整份搬进 backend/，
    而这个库是自测闸每一轮改写完的残局（测试建的笔记、被删掉的行、改过
    的标签都在里面）。平台起服读到的就是这个脏初态：种子重复、被测数据
    缺失，官方用例成批落空——而本地自测因为同一份脏库反而全绿。官方侧的
    跑测环境给每个套件一个全新的 sqlite 路径（ARC_DB_FILE），参考实现
    一律「空库启动 + 启动时播种」，干净库才是这条链路的正确初态。
    剥掉之后本地自测也换成干净环境：启动即播种的应用照旧绿，依赖现成库
    文件的应用立刻判红进修复环——原本那颗无声的假绿就此变成可修的失败。"""
    name = p.name.lower()
    return name.endswith(_DB_DATA_EXT)


def export_platform_layout(output_dir: Path, project_dir: Path) -> dict:
    """把生成项目适配导出为官方 runner 布局，返回导出摘要。

    - backend/  = project code 全量（剥离 __pycache__/instance 数据）
                  + 通用启动入口 main.py + requirements.txt + package.json
    - frontend/ = 最小 Vite+React 壳（含 build 脚本）
    原子换入：新布局先落在 .export-*.new，全部步骤成功后才替换旧目录。
    （9/23 审计取证：原先「先 rmtree 再写」把导出中途失败换成了「连上一轮
    已经落地、能起服的产物也没了」，而调用方对导出失败照常 exit 0——
    抢先交付那份成果就此无声消失。幂等性不变：重复导出仍整体覆盖。）
    任何子步失败抛异常由调用方决定降级。
    """
    output_dir = Path(output_dir).resolve()
    code_dir = Path(project_dir).resolve() / "code"
    if not code_dir.is_dir():
        raise FileNotFoundError(f"项目无 code 目录: {code_dir}")

    backend = output_dir / "backend"
    frontend = output_dir / "frontend"
    staged = {backend: output_dir / ".export-backend.new",
              frontend: output_dir / ".export-frontend.new"}
    for target in staged.values():
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
    backend = staged[backend]
    frontend = staged[frontend]

    # --- backend ---
    for src in _py_files(code_dir):
        rel = src.relative_to(code_dir)
        dst = backend / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    # 静态资源/模板等非 py 资产一并随迁（排除运行数据与缓存）
    stripped_data: list[str] = []
    for src in code_dir.rglob("*"):
        parts = set(src.parts)
        if src.is_dir() or parts & {"__pycache__", "instance", ".git"}:
            continue
        if src.suffix == ".py":
            continue
        if _is_runtime_data(src):
            stripped_data.append(src.name)
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
    # 入口保底（9/23 keep r0 产物取证）：整棵树查不到可导入入口时，通用
    # 启动器 raise SystemExit → 容器 exit 1 = 不评分 = 整跑 0 分，UI 写得
    # 再好也一样。机械装配一个 create_app（注册全部扫到的 Blueprint）至
    # 少换来「服务活着 + /api/health 绿」的可评分终态。必须在写入通用
    # 启动器之前扫描：那份文本里的 `app = max(...)` 会被入口规则误认。
    entry_fix: dict | None = None
    try:
        from app.utils.mechanical_assembly import ensure_entry

        entry_fix = ensure_entry(backend)
    except Exception:
        entry_fix = None
    req_text = _requirements_for(code_dir)
    if entry_fix:
        import re

        need = (["fastapi", "uvicorn"]
                if entry_fix["framework"] == "fastapi" else ["flask"])
        for dep in need:
            if not re.search(rf"^{dep}\b", req_text, re.M | re.I):
                req_text = req_text + f"{dep}\n"
    (backend / "main.py").write_text(_BACKEND_MAIN, encoding="utf-8")
    (backend / "requirements.txt").write_text(
        req_text, encoding="utf-8")
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

    # 全部步骤都已成功——此刻才动旧目录（换入前任何异常都不影响在位产物）
    for final, target in staged.items():
        if final.exists():
            shutil.rmtree(final)
        target.rename(final)
    backend, frontend = (output_dir / "backend", output_dir / "frontend")

    return {
        "backend_files": sum(1 for _ in backend.rglob("*") if _.is_file()),
        "frontend_files": sum(1 for _ in frontend.rglob("*") if _.is_file()),
        "backend": str(backend),
        "frontend": str(frontend),
        # 入口来源：author = 生成的组装模块在场；mechanical = 保底壳已装配
        # （务必见于日志，否则「产物活着」与「产物靠保底壳活着」看不出来）
        "entry": ("mechanical" if entry_fix else "author"),
        # 剥除的运行库清单：产物数据不在这几枚文件里，只在启动播种里
        "runtime_data_stripped": stripped_data,
    }
