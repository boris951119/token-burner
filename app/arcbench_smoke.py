"""交付后集成验证 + 自动修复（factory26 参赛强化）。

背景（r2 演练取证）：逐模块门禁各自为政——auth import 了 db 不存在的
符号、组装模块漏注册其他模块的路由、/api/health 与前端静态目录无人
认领——全部在「组合成完整应用」这一步才爆雷，而管线原本没有这一步。

r4 演练再取证：基础冒烟只验「import + create_app + health」，而平台
评测是 Playwright 走用户旅程——搜索模块返回硬编码降级列表而非数据库
种子这类**旅程级缺陷**，冒烟 PASS、评测照样挂。本模块补上旅程级验收：

- run_smoke(code_dir)：确定性组装验证——import 全部顶层模块、定位
  create_app、test_client 打 GET /api/health（Flask/FastAPI 双栈兼容）；
- verify_delivery(project_dir, requirement, settings)：两段式——
  ① 基础冒烟（失败 → auto_repair）；
  ② 旅程验收：探测真实路由表 → LLM 生成「主成功路径」验收脚本
    （结构约束样板内嵌，仅 test_client 同进程访问；危险 API 扫描拦截）
    → 执行；失败先自修复脚本一轮（只修脚本不冤枉应用），仍失败才
    RepoFixer 修应用（验证命令 = 旅程脚本本身）。

约束：只读模块代码 + 新增/修改实现文件；验证/旅程脚本放系统临时目录，
不污染交付物。LLM 生成基础设施故障（超时等）不判应用死刑——旅程段
SKIP，基础冒烟结果兜底。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# 零 LLM 确定性修复（keep7 取证：修复通道必须先机械后 LLM）
from app.utils.auto_fixer import run_all_fixers, _externally_importable
from app.utils.schema_audit import collect_ddl

_VERIFY_TEMPLATE = '''\
"""ArcBench 集成冒烟（自动生成）：import 全模块 + create_app + /api/health。"""
import sys
from pathlib import Path

def _peak_mem_mb():
    """进程峰值内存 MB（官方环境 2GB 内存——应用膨胀必须在演练期暴露）。"""
    try:
        import ctypes
        import ctypes.wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.wintypes.DWORD),
                ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        if ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(pmc), pmc.cb,
        ):
            return pmc.PeakWorkingSetSize / 1048576
    except Exception:
        pass
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux 为 KB、macOS 为字节（同单位差致 Mac 上峰值虚报 1024 倍）
        return peak / 1048576 if sys.platform == "darwin" else peak / 1024
    except Exception:
        return -1.0

code = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(code))
for child in sorted(code.iterdir()):
    # keep4 尸检：含 __init__.py 的包目录不得入 path——其下同名子模块
    # 文件会遮蔽包本身（seed_data 包 vs seed_data.py）
    if (child.is_dir() and not child.name.startswith("_")
            and not (child / "__init__.py").exists()):
        sys.path.insert(0, str(child))

failures = []
mods = []
for child in sorted(code.iterdir()):
    if child.is_dir() and child.name not in ("_shared", "__pycache__"):
        for py in sorted(child.glob("*.py")):
            if not py.name.startswith("_") and py.stem not in sys.modules:
                try:
                    mods.append(__import__(py.stem))
                except Exception as exc:
                    failures.append(f"import {py.stem}: {exc!r}")
# 根目录 .py（main.py 等）也要导入——FastAPI 风格入口常在这里
for py in sorted(code.glob("*.py")):
    if not py.name.startswith("_") and py.stem not in sys.modules:
        try:
            mods.append(__import__(py.stem))
        except Exception as exc:
            failures.append(f"import {py.stem}: {exc!r}")

def _route_count(_c):
    try:
        if hasattr(_c, "url_map"):
            return sum(1 for _ in _c.url_map.iter_rules())
        return len(getattr(_c, "routes", []) or [])
    except Exception:
        return 0

# 9/22 冷启动取证：候选全收集按【路由数最多】择优——业务包
# 自带裸自测 app（有 health 无业务路由）迭代序抢先当选 → 冒烟加载
# 的 app 与导出入口不一致。作者入口=路由面最广者，装配壳垫后。
# 9/23 审计取证：导出启动器原先「模块级 app 非空即返回」，与本处口径
# 不一致——本地测真应用、runner 起裸壳时冒烟全绿而平台首页 404。两处
# 择优算法必须逐字同构（含保底壳让位规则），否则闸永远测不到判分面。
_cands = []
for mod in mods:
    cand = getattr(mod, "app", None) or getattr(mod, "application", None)
    if cand is not None and callable(cand) and not isinstance(cand, type):
        _cands.append((mod.__name__, cand))
for mod in mods:
    if hasattr(mod, "create_app"):
        try:
            _cands.append((mod.__name__, mod.create_app()))
        except Exception:
            continue
_shell = {mod.__name__ for mod in mods
          if getattr(mod, "__arcbench_assembled__", False)}
_cands = [x for x in _cands if x[0] not in _shell] or _cands
_CONVENTION = ("main", "app", "app_main", "project_main",
                "server", "wsgi", "run")
_pref = [x for x in _cands if x[0].lower() in _CONVENTION]
# v48 尸检（run 85f404a69443，0/100）：路由数最多但无 / 的迷你 app
# 赢得择优 → 合成保活首页吞掉整场。评测全部从 / 进：无 / 的候选
# 无论路由多富都是错门，真 / 在场者一律优先（与启动器同构修改）。
def _has_home(_a):
    try:
        if hasattr(_a, "url_map"):
            return any(getattr(_r, "rule", "") == "/"
                       for _r in _a.url_map.iter_rules())
        return any(getattr(_r, "path", "") == "/"
                   for _r in getattr(_a, "routes", []) or [])
    except Exception:
        return False
_home = [x for x in _cands if _has_home(x[1])]
_pref_h = [x for x in _home if x[0].lower() in _CONVENTION]
pool = _pref_h or _home or _pref or _cands
_entry, app = (None, None)
if pool:
    _entry, app = max(pool, key=lambda t: _route_count(t[1]))
    print(f"entry <- {_entry} (routes={_route_count(app)}, "
          f"candidates={len(_cands)})")
if app is None:
    print("loaded mods:", [m.__name__ for m in mods], file=sys.stderr)
    failures.append("没有任何模块提供 create_app 或模块级 app 入口")
    print("\\n".join(failures))
    raise SystemExit(1)

# FastAPI 项目没有 Flask 的 app.config——无条件赋值冒烟即崩，冤枉应用
# 进修复环烧轮次（Qoder 交叉审查 9/21 取证）
if hasattr(app, "config"):
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = True

if hasattr(app, "test_client"):        # Flask
    client = app.test_client()
    resp = client.get("/api/health")
    ok = resp.status_code == 200
    detail = f"/api/health -> {resp.status_code}"
    # r18 取证：入口 URL 必须活着（评测从首页开始走旅程）——
    # 组装层漏注册 `/` 时 health 照样绿，冒烟必须拦住首页 404
    home = client.get("/")
    if home.status_code != 200:
        failures.append(f"GET / -> {home.status_code}（入口路由缺失？）")
        ok = False
else:                                   # FastAPI
    from fastapi.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/api/health")
    ok = resp.status_code == 200
    detail = f"/api/health -> {resp.status_code}"
    home = client.get("/")
    if home.status_code != 200:
        failures.append(f"GET / -> {home.status_code}（入口路由缺失？）")
        ok = False

# 9/21 夜战取证三连（确定性拦截，报错直指修复动作）：
# ① 首页渲染出未求值模板/被转义 HTML = 页面是死文本，评测全灭；
# ② 首页没有 <a> 链接 = 占位壳页（评测从首页导航出发）；
# ③ Flask 有登录路由但缺 secret_key = 登录 POST 必 500。
def _has_nav(_b):
    """首页有没有「评测点得动」的入口控件。

    9/23 mini 彩排取证：需求只给一个 Enter Website 按钮 + JS 切区的落地页，
    被旧判据「首页必须有 <a>」判成占位壳页——按钮与链接在评分器眼里是同一条
    role 通道，判据比官方紧一寸就是白烧一轮修复（还可能把合规页改坏）。
    占位按钮（有标签没接线）由 acceptance_judge 的逐页接线证据负责，这里
    只拦「整页没有任何可点控件」这种真空壳。
    """
    _b = _b.lower().replace('"', '').replace("'", "")
    return any(_t in _b for _t in (
        "<a ", "<a>", "<button", "role=button", "role=link",
        "type=submit", "type=button", "action="))


if home.status_code == 200:
    _body = (home.get_data(as_text=True)
             if hasattr(home, "get_data") else getattr(home, "text", ""))
    if "{{" in _body or "{%" in _body:
        failures.append("GET / 渲染出未求值的模板占位符（{{/{%）——"
                        "模板未被渲染，检查 render_template_string 调用")
        ok = False
    elif "&lt;" in _body:
        failures.append("GET / 渲染出被转义的 HTML（&lt;）——模板双重"
                        "转义：内层 HTML 传入外层模板必须加 |safe")
        ok = False
    elif not _has_nav(_body):
        failures.append("GET / 页面没有任何可点控件（链接/按钮/提交/表单）"
                        "——占位壳页，首页必须渲染真实导航（评测全部用例"
                        "从首页出发）")
        ok = False
if hasattr(app, "wsgi_app") and getattr(app, "secret_key", None) is None:
    _has_login = any(
        "login" in str(getattr(_r, "rule", ""))
        for _r in getattr(app, "url_map", []).iter_rules())
    if _has_login:
        failures.append("Flask secret_key 未设置——session 登录 POST "
                        "将 500（组装层 create_app 必须 app.secret_key=...）")
        ok = False

if not ok:
    failures.append(detail)
    print("\\n".join(failures))
    raise SystemExit(1)

# 平台 v6-2 取证：注册 INSERT 报 no such table——DDL 声明了表但建表
# 初始化未接进启动链路，health/首页双绿照样漏。冒烟追加两步：
# ① 遍历全部 GET 页面（触发惰性初始化，等价评测方首访动作）
# ② DDL 声明表 vs 实际 sqlite_master 比对——缺表即 FAIL 并给精确清单
import re as _re
import sqlite3 as _sq
from html.parser import HTMLParser as _HTMLParser


class _FieldAnchors(_HTMLParser):
    """文本输入控件及其「可定位通道」计数（9/23 ARIA 取证）。

    官方用例几乎全按可访问性通道定位（getByPlaceholder / getByLabel 实测
    与 getByRole 同量级），当期交付里 placeholder 仅 2 处——定位不到的
    输入框等于不存在，功能写对了也照样零分。通道认定与评分器口径对齐：
    placeholder / aria-label / title / <label for=id> / 被 <label> 包住。
    注意 name= 与 id= 本身【不算】通道（评分器不按属性名定位）。"""

    _TEXTY = {"", "text", "search", "email", "password", "tel", "url",
              "number", "date", "time", "datetime-local", "month", "week"}

    def __init__(self):
        _HTMLParser.__init__(self, convert_charrefs=True)
        self.fields = []          # (id, 属性锚定?, 被 label 包住?)
        self._label_fors = set()
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        a = {str(k).lower(): (v or "") for k, v in attrs}
        if tag == "label":
            self._depth += 1
            if a.get("for", "").strip():
                self._label_fors.add(a["for"].strip().lower())
            return
        if tag not in ("input", "textarea"):
            return
        if tag == "input" and a.get("type", "").strip().lower() not in self._TEXTY:
            return                 # hidden/submit/checkbox 等不要求文本通道
        self.fields.append((
            a.get("id", "").strip().lower(),
            bool(a.get("placeholder") or a.get("aria-label") or a.get("title")),
            self._depth > 0))

    def handle_endtag(self, tag):
        if tag == "label" and self._depth:
            self._depth -= 1

    def unanchored(self):
        return [i or "<无 id>" for i, by_attr, wrapped in self.fields
                if not (by_attr or wrapped
                        or (i and i in self._label_fors))]


def _page_paths(_app):
    """全部无参 GET 页面路径，Flask/Starlette 双栈。

    9/23 取证：本段此前直读 app.url_map（Flask 专有）——FastAPI 交付在这
    一行抛 AttributeError 整段冒烟猝死，连后面的 DDL 缺表检查都跑不到，
    修复环拿到的只有一段 traceback 而不是可执行判词。"""
    if hasattr(_app, "url_map"):
        for rule in _app.url_map.iter_rules():
            if "GET" not in rule.methods:
                continue
            yield str(rule)
        return
    for r in getattr(_app, "routes", []):
        path = getattr(r, "path", None)
        if not path:
            continue                      # Mount 等无 path 节点跳过
        if "GET" not in (getattr(r, "methods", None) or ()):
            continue
        yield path


_bodies = []
_server_errors = []
for _p in sorted(_page_paths(app)):
    if "<" in _p or "{" in _p:            # 带参路由留给旅程脚本
        continue
    if _p in ("/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"):
        continue
    try:
        _r = client.get(_p)
        if getattr(_r, "status_code", 200) >= 500:
            _server_errors.append(f"{_p} -> {_r.status_code}")
        if _p.startswith("/api") or "static" in _p:
            continue
        # 锚点/ARIA 语料只收页面正文：JSON 混进去会让判分面虚胖
        _bodies.append(_r.get_data(as_text=True)
                       if hasattr(_r, "get_data")
                       else getattr(_r, "text", ""))
    except Exception as _exc:
        # 9/23 mini 彩排尸检：这里曾无条件 pass，且整段跳过 /api——交付的
        # GET /api/links 把 db 路径字符串当句柄传给 create_blueprint，500
        # 无人认领，本地冒烟全绿而评测列表步必死。异常＝崩溃（测试客户端
        # 已开 PROPAGATE_EXCEPTIONS），不再静默吞。
        _server_errors.append(f"{_p} -> {type(_exc).__name__}: {str(_exc)[:60]}")
if _server_errors:
    failures.append(
        "无参 GET 出现 5xx/异常（评测的列表与查询步直接死）: "
        + "; ".join(_server_errors[:8])
        + "——高频成因是装配层跨模块传参错位（把路径/文件名字符串当成"
          "连接或封装对象传给对端工厂）")
    print("\\n".join(failures))
    raise SystemExit(1)

_fa = _FieldAnchors()
for _h in _bodies:
    try:
        _fa.feed(_h)
    except Exception:
        continue
_orphan = _fa.unanchored()
if _orphan:
    failures.append(
        f"{len(_orphan)}/{len(_fa.fields)} 个文本输入控件没有任何可定位通道"
        "（无 placeholder、无 aria-label/title，也没有关联的 <label>）——"
        "评测按 getByPlaceholder/getByLabel 定位即落空，每个输入框都要"
        "同时补 placeholder 与 <label for>（id 配对）: "
        + ", ".join(_orphan[:8]))
    print("@@ARIA@@" + ",".join(_orphan[:8]))
    print("\\n".join(failures))
    raise SystemExit(1)

_declared = set()
for _py in code.rglob("*.py"):
    if "__pycache__" in _py.parts:
        continue
    try:
        _src = _py.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue
    for _m in _re.finditer(
            r"CREATE\\s+TABLE\\s+(?:IF\\s+NOT\\s+EXISTS\\s+)?(\\w+)",
            _src, _re.IGNORECASE):
        _declared.add(_m.group(1).lower())
_missing = []
if _declared:
    _existing = set()
    for _db in code.rglob("*"):
        if _db.suffix.lower() not in (".db", ".sqlite", ".sqlite3"):
            continue
        if "__pycache__" in _db.parts:
            continue
        try:
            _conn = _sq.connect(str(_db))
            _rows = _conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            _existing.update(str(r[0]).lower() for r in _rows)
            _conn.close()
        except Exception:
            continue
    _missing = sorted(t for t in _declared if t not in _existing)
if _missing:
    failures.append(
        "DDL 声明的表在建表初始化后仍不存在: " + ", ".join(_missing[:10])
        + "（建表 init 未接线——请在 create_app 中调用全部模块的建表/初始化）")
    print("@@SCHEMA@@" + ",".join(_missing))
    print("\\n".join(failures))
    raise SystemExit(1)

print(f"@@MEM@@{_peak_mem_mb():.1f}")
print("SMOKE_OK")
'''

# 锚点覆盖探针：全 GET 页面响应采样（gen-6 取证家族的通用化——
# 需求承诺的 UI 锚点必须出现在页面响应中，机械校验零 LLM）。
_ANCHOR_COVERAGE_TEMPLATE = '''\
"""ArcBench 锚点覆盖探针（自动生成）：页面响应采样 -> @@PAGES@@{json}。"""
import json
import re
import sys
from pathlib import Path


def _visible_text(html: str) -> str:
    """提取渲染可见文本（平台 v6-3 取证：LLM 把锚点字符串塞进
    hidden textarea 骗过子串匹配——子串必须对「可见文本」做）。"""
    txt = re.sub(r"(?is)<script\\b.*?</script>", " ", html)
    txt = re.sub(r"(?is)<style\\b.*?</style>", " ", txt)
    txt = re.sub(r"(?is)<textarea\\b[^>]*>.*?</textarea>", " ", txt)
    txt = re.sub(r"(?is)<(\\w+)[^>]*(?:hidden|visibility\\s*:\\s*hidden|display\\s*:\\s*none)[^>]*>.*?</\\1\\s*>", " ", txt)
    txt = re.sub(r"(?is)<template\\b[^>]*>.*?</template>", " ", txt)
    txt = re.sub(r"(?s)<[^>]+>", " ", txt)
    return txt

code = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(code))
for child in sorted(code.iterdir()):
    if (child.is_dir() and not child.name.startswith("_")
            and not (child / "__init__.py").exists()):
        sys.path.insert(0, str(child))
mods = []
for child in sorted(code.iterdir()):
    if child.is_dir() and child.name not in ("_shared", "__pycache__"):
        for py in sorted(child.glob("*.py")):
            if not py.name.startswith("_") and py.stem not in sys.modules:
                try:
                    mods.append(__import__(py.stem))
                except Exception as _exc:
                    print("import fail:", py.stem, repr(_exc), file=sys.stderr)
def _route_count(_c):
    try:
        if hasattr(_c, "url_map"):
            return sum(1 for _ in _c.url_map.iter_rules())
        return len(getattr(_c, "routes", []) or [])
    except Exception:
        return 0

_cands = []
for mod in mods:
    if hasattr(mod, "create_app"):
        try:
            _cands.append((mod.__name__, mod.create_app()))
        except Exception:
            continue
_CONVENTION = ("main", "app", "app_main", "project_main",
                "server", "wsgi", "run")
_pref = [x for x in _cands if x[0].lower() in _CONVENTION]
# v48 尸检（run 85f404a69443，0/100）：路由数最多但无 / 的迷你 app
# 赢得择优 → 合成保活首页吞掉整场。评测全部从 / 进：无 / 的候选
# 无论路由多富都是错门，真 / 在场者一律优先（与启动器同构修改）。
def _has_home(_a):
    try:
        if hasattr(_a, "url_map"):
            return any(getattr(_r, "rule", "") == "/"
                       for _r in _a.url_map.iter_rules())
        return any(getattr(_r, "path", "") == "/"
                   for _r in getattr(_a, "routes", []) or [])
    except Exception:
        return False
_home = [x for x in _cands if _has_home(x[1])]
_pref_h = [x for x in _home if x[0].lower() in _CONVENTION]
pool = _pref_h or _home or _pref or _cands
app = max(pool, key=lambda t: _route_count(t[1]))[1] if pool else None
if app is None:
    print("loaded mods:", [m.__name__ for m in mods], file=sys.stderr)
    print("sys.modules keys:", [k for k in sys.modules if not k.startswith("_")], file=sys.stderr)
    raise SystemExit("no create_app")
client = app.test_client()
pages = {}
for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
    p = str(rule)
    if "GET" not in rule.methods or "<" in p:
        continue
    if p.startswith("/api") or "static" in p:
        continue
    try:
        r = client.get(p)
        pages[p] = _visible_text(r.data.decode("utf-8", "replace"))[:4000]
    except Exception as exc:
        pages[p] = "__ERROR__ " + repr(exc)
print("@@PAGES@@" + json.dumps(pages))
'''

# 路由探测：与冒烟同一套 import 引导，定位组装模块并倾倒真实 url_map。
# r7e 取证：查询参数名（origin vs from_station）只存在于视图函数源码里，
# 只给路径+方法会让生成脚本瞎猜参数名 → 400。视图源码 .args.get 内省。
_PROBE_TEMPLATE = '''\
"""ArcBench 路由探测（自动生成）：url_map -> @@ROUTES@@{json}。"""
import inspect
import json
import re
import sys
from pathlib import Path

code = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(code))
for child in sorted(code.iterdir()):
    # keep4 尸检：含 __init__.py 的包目录不得入 path——其下同名子模块
    # 文件会遮蔽包本身（seed_data 包 vs seed_data.py）
    if (child.is_dir() and not child.name.startswith("_")
            and not (child / "__init__.py").exists()):
        sys.path.insert(0, str(child))

mods = []
for child in sorted(code.iterdir()):
    if child.is_dir() and child.name not in ("_shared", "__pycache__"):
        for py in sorted(child.glob("*.py")):
            if not py.name.startswith("_") and py.stem not in sys.modules:
                try:
                    mods.append(__import__(py.stem))
                except Exception as _exc:
                    print("import fail:", py.stem, repr(_exc), file=sys.stderr)
# 根目录 .py（main.py=作者入口）也要导入——两遍探测才能看见它
for py in sorted(code.glob("*.py")):
    if not py.name.startswith("_") and py.stem not in sys.modules:
        try:
            mods.append(__import__(py.stem))
        except Exception as _exc:
            print("import fail:", py.stem, repr(_exc), file=sys.stderr)

def _route_count(_c):
    try:
        if hasattr(_c, "url_map"):
            return sum(1 for _ in _c.url_map.iter_rules())
        return len(getattr(_c, "routes", []) or [])
    except Exception:
        return 0

# 9/22 冷启动取证：同 VERIFY——候选全收集按路由数择优
_cands = []
for mod in mods:
    cand = getattr(mod, "app", None) or getattr(mod, "application", None)
    if cand is not None and callable(cand) and not isinstance(cand, type):
        _cands.append((mod.__name__, cand))
for mod in mods:
    if hasattr(mod, "create_app"):
        try:
            _cands.append((mod.__name__, mod.create_app()))
        except Exception:
            continue
_CONVENTION = ("main", "app", "app_main", "project_main",
                "server", "wsgi", "run")
_pref = [x for x in _cands if x[0].lower() in _CONVENTION]
# v48 尸检（run 85f404a69443，0/100）：路由数最多但无 / 的迷你 app
# 赢得择优 → 合成保活首页吞掉整场。评测全部从 / 进：无 / 的候选
# 无论路由多富都是错门，真 / 在场者一律优先（与启动器同构修改）。
def _has_home(_a):
    try:
        if hasattr(_a, "url_map"):
            return any(getattr(_r, "rule", "") == "/"
                       for _r in _a.url_map.iter_rules())
        return any(getattr(_r, "path", "") == "/"
                   for _r in getattr(_a, "routes", []) or [])
    except Exception:
        return False
_home = [x for x in _cands if _has_home(x[1])]
_pref_h = [x for x in _home if x[0].lower() in _CONVENTION]
pool = _pref_h or _home or _pref or _cands
app_module, app = ("", None)
if pool:
    app_module, app = max(pool, key=lambda t: _route_count(t[1]))
if app is None:
    print("loaded mods:", [m.__name__ for m in mods], file=sys.stderr)
    print("code dir:", str(code), "exists:", code.is_dir(), file=sys.stderr)
    try:
        print("code dir listing:", [c.name for c in code.iterdir()], file=sys.stderr)
    except Exception as _e:
        print("code dir listing fail:", repr(_e), file=sys.stderr)
    print("create_app holders in sys.modules:", [
        k for k, v in sys.modules.items() if hasattr(v, "create_app")],
        file=sys.stderr)
    raise SystemExit("没有任何模块提供 create_app 或模块级 app 入口")

routes = []
if hasattr(app, "url_map"):                 # Flask/WSGI
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        methods = sorted(set(rule.methods) - {"HEAD", "OPTIONS"})
        params = set()
        view = app.view_functions.get(rule.endpoint)
        if view is not None:
            try:
                src = inspect.getsource(view)
                params = set(re.findall(r"\\.args\\.get\\(\\s*['\\"](\\w+)", src))
            except Exception:
                params = set()
        entry = f"{rule.rule} [{','.join(methods)}]"
        if params:
            entry += f" params:{','.join(sorted(params))}"
        routes.append(entry)
else:                                        # FastAPI/Starlette ASGI
    for r in getattr(app, "routes", []):
        path = getattr(r, "path", None)
        if not path or path in ("/openapi.json", "/docs",
                                "/redoc", "/docs/oauth2-redirect"):
            continue
        methods = sorted(getattr(r, "methods", None) or ["?"])
        routes.append(f"{path} [{','.join(methods)}]")
print("@@ROUTES@@" + json.dumps(
    {"app_module": app_module, "routes": routes}, ensure_ascii=False))
'''

# 旅程脚本样板：import 引导与 create_app 由框架提供，LLM 只写 === 之间
# 的旅程主体——结构性约束把生成代码的攻击面压到「test_client 内进程访问」。
_JOURNEY_BOILERPLATE = '''\
"""ArcBench 旅程验收（自动生成）：真实 create_app().test_client() 走主旅程。"""
import sys
from pathlib import Path

code = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(code))
for child in sorted(code.iterdir()):
    # keep4 尸检：含 __init__.py 的包目录不得入 path——其下同名子模块
    # 文件会遮蔽包本身（seed_data 包 vs seed_data.py）
    if (child.is_dir() and not child.name.startswith("_")
            and not (child / "__init__.py").exists()):
        sys.path.insert(0, str(child))

from __APP_MODULE__ import create_app
app = create_app()
c = app.test_client()
client = c  # 别名：r11 取证 LLM 惯用 client，NameError 会被误判为应用缺陷
# 轨迹取证（r12/r13/r15 手工诊断的产品化）：应用侧异常直接带着
# file:line 冒泡进报告，修复指令不再只看 HTTP 状态码瞎猜。
# FastAPI 项目没有 Flask 的 app.config——无条件赋值冒烟即崩，冤枉应用
# 进修复环烧轮次（Qoder 交叉审查 9/21 取证）
if hasattr(app, "config"):
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = True

# === JOURNEY BEGIN（LLM 生成段） ===
__BODY__
# === JOURNEY END ===

print("JOURNEY_OK")
'''

_JOURNEY_SYSTEM = (
    "你是 Web 应用验收工程师。只输出一段 Python 代码体（无 import 样板、"
    "无函数定义、无 print JOURNEY_OK——框架已提供），用变量 c "
    "（Flask test client，同进程无网络）从首页开始走应用的主成功路径，"
    "每步 assert 状态码与关键内容，断言消息写清步骤/期望/实际。"
    "场景翻译纪律（官方隐藏测试同款写法）：每个需求场景按 前置(GIVEN)→"
    "动作(WHEN)→断言(THEN) 三段翻译成步骤；断言只验证场景明确要求的"
    "结果，禁止反向断言——场景要求『导航可见』就不要断言其他元素不存在"
    "（反向断言把不相关修复误判成应用缺陷）。"
    "禁止 import json/re 之外的模块；禁止 os/sys/subprocess/socket/requests。"
)

# 旅程步数计数（缩水检测：c.get/c.post/c.put/c.delete 调用数）
_JOURNEY_STEP_RE = re.compile(r"c\.(?:get|post|put|delete|patch)\(")

# 脚本自身缺陷分类（r11 取证）：这些异常 + 脚本帧 = 脚本从未跑到断言，
# 是脚本 bug 而非应用缺陷（AssertionError 排除——那可能是真断言失败）。
# keep7w 取证补充：sqlite3.OperationalError/DatabaseError = 脚本直连
# 数据库连错库（`no such table`），属脚本缺陷走重生成，不冤枉应用。
_SCRIPT_DEFECT_RE = re.compile(
    r"\b(NameError|UnboundLocalError|AttributeError|KeyError|IndexError"
    r"|TypeError|SyntaxError|IndentationError)\b\s*:"
    r"|\bsqlite3\.(?:OperationalError|DatabaseError|ProgrammingError)\b")


_ANCHOR_GATE_TEMPLATE = '''\
"""ArcBench 锚点门禁（自动生成）：页面采样 × 锚点 → 缺失 exit 1。

RepoFixer 修复循环的验证信号（平台 v6 取证：修复用冒烟验证，冒烟
本来就过，锚点缺口三轮分文未收敛）。缺失清单打在 @@MISSING@@ 行。"""
import json
import re
import sys
from pathlib import Path

ANCHORS = __ANCHORS__

code = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(code))
for child in sorted(code.iterdir()):
    if (child.is_dir() and not child.name.startswith("_")
            and not (child / "__init__.py").exists()):
        sys.path.insert(0, str(child))
mods = []
for child in sorted(code.iterdir()):
    if child.is_dir() and child.name not in ("_shared", "__pycache__"):
        for py in sorted(child.glob("*.py")):
            if not py.name.startswith("_") and py.stem not in sys.modules:
                try:
                    mods.append(__import__(py.stem))
                except Exception:
                    pass
def _route_count(_c):
    try:
        if hasattr(_c, "url_map"):
            return sum(1 for _ in _c.url_map.iter_rules())
        return len(getattr(_c, "routes", []) or [])
    except Exception:
        return 0

_cands = []
for mod in mods:
    if hasattr(mod, "create_app"):
        try:
            _cands.append((mod.__name__, mod.create_app()))
        except Exception:
            continue
_CONVENTION = ("main", "app", "app_main", "project_main",
                "server", "wsgi", "run")
_pref = [x for x in _cands if x[0].lower() in _CONVENTION]
# v48 尸检（run 85f404a69443，0/100）：路由数最多但无 / 的迷你 app
# 赢得择优 → 合成保活首页吞掉整场。评测全部从 / 进：无 / 的候选
# 无论路由多富都是错门，真 / 在场者一律优先（与启动器同构修改）。
def _has_home(_a):
    try:
        if hasattr(_a, "url_map"):
            return any(getattr(_r, "rule", "") == "/"
                       for _r in _a.url_map.iter_rules())
        return any(getattr(_r, "path", "") == "/"
                   for _r in getattr(_a, "routes", []) or [])
    except Exception:
        return False
_home = [x for x in _cands if _has_home(x[1])]
_pref_h = [x for x in _home if x[0].lower() in _CONVENTION]
pool = _pref_h or _home or _pref or _cands
app = max(pool, key=lambda t: _route_count(t[1]))[1] if pool else None
if app is None:
    print("loaded mods:", [m.__name__ for m in mods], file=sys.stderr)
    for _name, _m in list(sys.modules.items()):
        if hasattr(_m, "create_app"):
            print("module with create_app (not in mods loop):", _name, file=sys.stderr)
    print("@@MISSING@@" + json.dumps(ANCHORS))
    raise SystemExit(1)
def _visible_text(html: str) -> str:
    """渲染可见文本提取（平台 v6-3 取证同款——hidden textarea 塞串
    在门禁探针里同样要防）。"""
    txt = re.sub(r"(?is)<script\\b.*?</script>", " ", html)
    txt = re.sub(r"(?is)<style\\b.*?</style>", " ", txt)
    txt = re.sub(r"(?is)<textarea\\b[^>]*>.*?</textarea>", " ", txt)
    txt = re.sub(r"(?is)<(\\w+)[^>]*(?:hidden|visibility\\s*:\\s*hidden|display\\s*:\\s*none)[^>]*>.*?</\\1\\s*>", " ", txt)
    txt = re.sub(r"(?is)<template\\b[^>]*>.*?</template>", " ", txt)
    txt = re.sub(r"(?s)<[^>]+>", " ", txt)
    return txt


client = app.test_client()
pages = {}
for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
    p = str(rule)
    if "GET" not in rule.methods or "<" in p:
        continue
    if p.startswith("/api") or "static" in p:
        continue
    try:
        rr = client.get(p)
        pages[p] = _visible_text(rr.data.decode("utf-8", "replace"))[:4000]
    except Exception as exc:
        pages[p] = "__ERROR__ " + repr(exc)
body = " ".join(pages.values()).lower()
missing = [a for a in ANCHORS if a.lower() not in body]
print("@@MISSING@@" + json.dumps(missing))
raise SystemExit(1 if missing else 0)
'''


def _anchor_missing(code_dir: Path, requirement: str) -> list[str]:
    """锚点缺口清单（平台 v6 取证：全盘落空根因——需求带引号文案
    被翻译/改写，评测断言逐字落空）。

    子进程探针采集全部 GET 页面响应样本，与需求文本机械提取的锚点
    做覆盖比对，返回缺失锚点列表（异常/无锚点/探针失败返回空——
    宁漏不误，不因探针自身缺陷冤枉应用）。"""
    try:
        from app.utils.requirement_anchors import (
            collect_anchors_from_text,
            compute_coverage,
        )

        buckets = collect_anchors_from_text(requirement)
        anchors = sorted({a for lst in buckets.values() for a in lst})
        if not anchors:
            return []
        probe = Path(tempfile.gettempdir()) / "arcbench_anchor_pages.py"
        probe.write_text(_ANCHOR_COVERAGE_TEMPLATE, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(probe), str(code_dir)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=240, cwd=str(code_dir))
        pages: dict[str, str] = {}
        for line in (proc.stdout or "").splitlines():
            if line.startswith("@@PAGES@@"):
                try:
                    pages = json.loads(line[len("@@PAGES@@"):])
                except ValueError:
                    pass
        if not pages:
            return []
        return list(compute_coverage(pages, anchors)["missing"])
    except Exception:
        return []


def _anchor_coverage_section(code_dir: Path, requirement: str) -> str:
    """锚点覆盖探针段（gen-6 取证家族通用化）：需求承诺的锚点文案
    在页面响应中的覆盖情况——机械校验，零 LLM。

    通过子进程探针（_ANCHOR_COVERAGE_TEMPLATE）采集全部 GET 页面响应
    样本，再与需求文本机械提取的锚点做覆盖比对。返回 markdown 段
    （无锚点/全覆盖/异常返回空串——宁漏不误）。
    """
    from app.utils.requirement_anchors import (
        collect_anchors_from_text,
        compute_coverage,
    )

    buckets = collect_anchors_from_text(requirement)
    anchors = sorted({a for lst in buckets.values() for a in lst})
    if not anchors:
        return ""
    probe = Path(tempfile.gettempdir()) / "arcbench_anchor_pages.py"
    probe.write_text(_ANCHOR_COVERAGE_TEMPLATE, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(probe), str(code_dir)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            timeout=240, cwd=str(code_dir))
    except Exception:
        return ""
    pages: dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        if line.startswith("@@PAGES@@"):
            try:
                pages = json.loads(line[len("@@PAGES@@"):])
            except ValueError:
                pass
    if not pages:
        return ""
    cov = compute_coverage(pages, anchors)
    lines = ["", "## 锚点覆盖探针（机械校验）"]
    for a in cov["missing"][:14]:
        lines.append(f"- 需求锚点 {a!r} 未出现在任何页面的可见文本中——"
                     "请在对应页面按需求原文补齐该文案/区块（可见元素；"
                     "塞进 display:none/hidden 元素、HTML 注释或 title "
                     "属性都不算补齐，评测按渲染后可见性断言）")
    for a, hits in sorted(cov["where"].items())[:8]:
        lines.append(f"- 需求锚点 {a!r} 已出现在: {', '.join(hits[:2])}")
    return "\n".join(lines) + "\n\n"

def _interface_drift_section(code_dir: Path,
                             project_dir: Path | None = None) -> str:
    """属性级接口漂移审计注入修复指令（9/21 keep 取证：init_db/
    _init_db 一个下划线全站 500，LLM 自省 2 轮零提升）。零 LLM
    AST 比对，发现即高置信；无发现不占提示词。"""
    try:
        from app.utils.interface_attr_audit import audit_interface_drift

        findings = audit_interface_drift(code_dir, project_dir)
    except Exception:
        return ""
    if not findings:
        return ""
    return (
        "【确定性接口漂移审计（AST 比对，优先按此修复——每条都是可"
        "机械验证的缺口）】\n"
        + "\n".join(f"- {f}" for f in findings[:12])
        + "\n对齐方式二选一：改调用方用真实存在名，或在提供方加公共"
        "别名/导出；禁止新建空壳函数应付。\n")


def _seed_audit_section(code_dir: Path, requirement: str) -> str:
    """种子声明落库审计注入修复指令（9/21 keep 取证：官方 yaml 逐字
    声明被无视、LLM 自编种子致 REQ-2.x 簇 16 项连环落空）。零 LLM
    字面比对。"""
    try:
        from app.utils.seed_contract import audit_seeds

        findings = audit_seeds(code_dir, requirement)
    except Exception:
        return ""
    if not findings:
        return ""
    return (
        "【确定性种子审计（需求 Seed data 逐字契约，优先按此修复）】\n"
        + "\n".join(f"- {f}" for f in findings[:15])
        + "\n把每个缺失名字原样补进种子/初始化数据（含大小写与空格）。"
        + "\n")


def _language_audit_section(code_dir: Path, requirement: str) -> str:
    """UI 语言一致性审计注入修复指令（9/22 so 取证：英文需求生成
    中文 UI，66 题第一步全灭——管线提示词语言污染界面语言）。"""
    try:
        from app.utils.ui_language import audit_ui_language

        findings = audit_ui_language(code_dir, requirement)
    except Exception:
        return ""
    if not findings:
        return ""
    return (
        "【确定性 UI 语言审计（文字系别比对，最高优先级——此缺口不修"
        "其余修复全部无效）】\n"
        + "\n".join(f"- {f}" for f in findings[:3])
        + "\n")


def _schema_audit_section(code_dir: Path, findings: list[str] | None = None) -> str:
    """确定性 schema 审计结论注入修复指令（r13 取证：列名漂移 2 轮未定位）。

    零 LLM 正则 diff：DDL 列 vs SQL 引用列。宁漏不误——发现即高置信，
    直接给出表名/文件/行与 DDL 权威列清单；无发现则不占提示词。
    findings 可传入已算好的结果（动态轮次与注入共用一次审计）。
    """
    if findings is None:
        try:
            from app.utils.schema_audit import audit_schema

            findings = audit_schema(code_dir)
        except Exception:
            return ""
    if not findings:
        return ""
    return (
        "【确定性 schema 审计（正则 diff，优先按此修复）】\n"
        + "\n".join(f"- {f}" for f in findings[:10])
        + "\n表结构唯一权威是 seed_data 模块的 DDL；请把查询/插入改为"
        "使用 DDL 实际存在的列。\n"
        "修复形态约束（r16 实证）：直接改 SQL 字面量为 DDL 真实列名，"
        "**严禁**新增运行时 schema 探测/列名自适应/兼容层/防御性校验——"
        "此类代码自身失灵时会把正常请求整体打死（如注册全部 500）。\n\n"
    )


def _is_script_defect(report: str) -> bool:
    """报告含脚本帧且终态异常属于「脚本自身写错」类 → 分类为脚本缺陷。

    轨迹取证后（TESTING+PROPAGATE）应用侧异常也会带脚本帧出现在
    报告里——判定必须看**最深处帧**：异常最终抛出的文件是旅程脚本
    才算脚本缺陷；最深帧在应用代码里 = 应用缺陷（送 RepoFixer）。
    """
    if not report or "arcbench_journey.py" not in report:
        return False
    if not _SCRIPT_DEFECT_RE.search(report[-400:]):
        return False
    frames = re.findall(r'File "([^"]+)"', report)
    deepest = frames[-1] if frames else ""
    return "arcbench_journey.py" in deepest

_JOURNEY_USER = """根据需求摘要与真实路由表，生成该 Web 应用的主旅程验收代码体。

需求摘要：
{requirement}

应用组装模块名：{app_module}（框架已 import 并创建 app）
真实路由表（含查询参数名，仅供查对路径/方法/参数名）：
{routes}

硬性规则：
1. 只走需求的主成功旅程（5-8 步，典型：注册→登录→核心查询→
   提交业务→查记录；需求没有账号概念时从首页/列表起步，**不要**
   为了凑步数发明注册登录步），**禁止**逐个访问路由表里的所有路径，禁止测试
   内部/管理/基建类端点（如建表、初始化、路由注册类）；
2. 路径、HTTP 方法与查询参数名必须逐字取自上方路由表，**禁止访问
   表中不存在的路径**，禁止发明任何端点或参数；
3. 覆盖 GET /api/health 返回 200 一条即可作为第 1 步；
4. 成功路径的状态码断言用 `resp.status_code in (200, 201)`（合法实现
   可能返回 200 或 201，硬编码单一值会误杀正确应用）；失败分支断言
   `in (400, 401, 403, 409)` 区间；
5. **页面导航（首页/登录页/列表页等 GET 页面）一律用
   `c.get(url, follow_redirects=True)` 并断言最终状态码**——评测方
   真实浏览器会自动跟随重定向，登录页 302→200 属合法实现（keep7w
   取证：硬编码 200 断言误杀 302 重定向）；
6. 业务数据现场创建（先注册的账号就用于登录；列表响应里的值取自
   实际响应再断言，不要凭空假设精确值）；
7. **禁止 import sqlite3，禁止 import 应用内部模块**（如 _shared、
   data_core 等），数据断言一律取自 HTTP 响应体——响应里没有的数据
   按缺失处理，如实让断言失败，由应用修复通道补齐（keep7w 取证：
   脚本直连数据库连错库报 `no such table`，从未走到业务断言）；
8. 每步 resp = c.post(...)/c.get(...) 后立刻 assert，断言消息含步骤名。

行为探针（除主旅程外必须包含，各 1-2 步即可；需求没有对应功能时
该探针整条跳过，严禁为了凑探针而发明端点）：
A. 唯一性冲突拒绝：需求点名的唯一字段（用户名、编码、标题、邮箱等）
   重复提交一次，断言 `resp.status_code in (400, 401, 403, 409)`——
   需求几乎总是要求重复提交被拒绝，200/201 属于静默成功违约（r15 实证）；
B. 种子字符串断言：需求给出的精确数据（如编号、名称、标题）
   若出现在查询/列表响应中，用这些精确字符串断言存在性——这是
   评测方 e2e 夹具的断言方式；
C. 非法输入拒绝：含登录的应用用错误密码登录，断言
   `resp.status_code in (400, 401, 403)` 不得放行 2xx；无登录的应用
   对必填字段留空提交，断言 4xx。
"""


def _clear_pycache(code_dir: Path) -> None:
    """验证前清字节码缓存。

    r4 取证：等长同秒覆写（如 29 字符的 return→raise 换法）会让 pyc
    双重校验（mtime 秒级 + 源大小）双双命中，子进程导入陈旧模块——
    修复循环对着旧代码验证，震荡且非确定。全量清除一次性消灭该类。
    """
    for cache in code_dir.rglob("__pycache__"):
        try:
            shutil.rmtree(cache, ignore_errors=True)
        except Exception:
            pass


def auto_shim_imports(code_dir: Path) -> list[str]:
    """机械命名漂移垫片（gen-3 取证：命名漂移家族第四次杀伤，LLM 修复
    不可靠——r17 auth_bp / keep3 auth_bp / keep4 seed_data / gen-3 home）。

    扫描全库顶层 import：被导入的名字 X 不存在（无 X.py 无 X/ 包）但
    存在近名真实包 P（包含关系/下划线后缀）时，生成 X.py 垫片——
    re-export 包 P 全部公开名（含各子模块）。纯加法、零 LLM、smoke
    即时复验。返回生成的垫片文件名列表（空 = 无漂移或无高置信近名）。
    """
    code_dir = Path(code_dir)
    if not code_dir.is_dir():
        return []
    real: dict[str, Path] = {}
    for child in code_dir.iterdir():
        if child.name.startswith(".") or child.name in ("__pycache__",
                                                        "tests"):
            continue
        if child.is_dir() and (child / "__init__.py").exists():
            real[child.name] = child
        elif child.suffix == ".py":
            real[child.stem] = child
    if not real:
        return []

    stdlib = getattr(sys, "stdlib_module_names", ())

    # 收集顶层缺失导入名及其 wanted 符号
    missing: dict[str, set[str]] = {}
    for py in code_dir.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"^\s*(?:import|from)\s+(\w+)", src, re.MULTILINE):
            name = m.group(1)
            # keep7 取证：`import re` 被当漂移收集，"re" in "data_core"
            # 子串匹配成立 → 生成 re.py 遮蔽标准库。标准库/三方包/下划线
            # 名绝不垫。
            if (name in stdlib or name.startswith("_")
                    or _externally_importable(name)):
                continue
            if name in real or name in missing:
                continue
            missing[name] = set()
        for m in re.finditer(
                r"^\s*from\s+(\w+)\s+import\s+([^\n#]+)", src, re.MULTILINE):
            pkg, syms = m.group(1), m.group(2)
            if (pkg in real or pkg in stdlib or pkg.startswith("_")
                    or _externally_importable(pkg)):
                continue
            for raw in syms.split(","):
                sym = raw.strip().split(" as ")[0].strip()
                if re.match(r"^\w+$", sym) and sym != "*":
                    missing.setdefault(pkg, set()).add(sym)

    shims: list[str] = []
    for name in sorted(missing):
        if (code_dir / f"{name}.py").exists() or (code_dir / name).is_dir():
            continue  # 已存在（可能为上轮垫片）——不重复
        near = [p for p in real
                if p.endswith("_" + name)
                or (len(name) >= 3
                    and (p.startswith(name) or name in p))]
        if len(near) != 1:
            continue  # 无唯一高置信近名 → 不垫（宁漏不误）
        target = near[0]
        shim_lines = [
            f"# Auto shim（命名漂移机械修复）：{name} ⇒ {target}（零 LLM，加法不改行为）",
            "import importlib as _il",
            "import pkgutil as _pu",
            f"_pkg = _il.import_module({target!r})",
            "_names = {}",
            "for _n in dir(_pkg):",
            "    _names.setdefault(_n, getattr(_pkg, _n))",
            "for _mi in _pu.iter_modules(getattr(_pkg, '__path__', [])):",
            "    try:",
            f"        _sub = _il.import_module({target!r} + '.' + _mi.name)",
            "        for _n in dir(_sub):",
            "            _names.setdefault(_n, getattr(_sub, _n))",
            "    except Exception:",
            "        pass",
            "globals().update(_names)",
        ]
        wanted = sorted(missing[name])
        if wanted:
            shim_lines.append(
                "for _w in " + repr(wanted) + ":")
            shim_lines.append(
                "    if _w not in globals() and hasattr(_pkg, _w):"
                " globals()[_w] = getattr(_pkg, _w)")
        (code_dir / f"{name}.py").write_text(
            "\n".join(shim_lines) + "\n", encoding="utf-8")
        shims.append(name)
    return shims


def auto_bind_submodules(code_dir: Path) -> list[str]:
    """子模块属性绑定修复（keep4 终局取证）：`from seed_data import
    seed_data` 要的是同名子模块——包 __init__ 未 `from . import 子模块`
    时该导入报 ImportError。纯加法（往 __init__ 追加一行绑定），零 LLM。
    返回修复的包名列表。
    """
    code_dir = Path(code_dir)
    fixed: list[str] = []
    wanted: dict[str, set[str]] = {}
    for py in code_dir.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r"^\s*from\s+(\w+)\s+import\s+([^\n#]+)",
                             src, re.MULTILINE):
            pkg = m.group(1)
            pkg_dir = code_dir / pkg
            if not (pkg_dir / "__init__.py").exists():
                continue
            for raw in m.group(2).split(","):
                sym = raw.strip().split(" as ")[0].strip()
                if re.match(r"^\w+$", sym) and sym != "*" \
                        and (pkg_dir / f"{sym}.py").exists():
                    wanted.setdefault(pkg, set()).add(sym)
    for pkg, syms in sorted(wanted.items()):
        init = code_dir / pkg / "__init__.py"
        init_src = init.read_text(encoding="utf-8", errors="replace")
        missing = [s for s in sorted(syms)
                   if not re.search(rf"^\s*from\s+\.?\s*import\s+.*\b{s}\b"
                                    rf"|^\s*import\s+\.{s}\b|^\s*from\s+{pkg}\s+import"
                                    rf"|^\s*from\s+{s}\.", init_src, re.MULTILINE)]
        if not missing:
            continue
        init.write_text(
            init_src.rstrip() + "\n\n# auto-bind（命名漂移机械修复）\n"
            + "\n".join(f"from . import {s}  # noqa: F401" for s in missing)
            + "\n", encoding="utf-8")
        fixed.append(pkg)
    return fixed


# ---- 批次#43：DOM 表单动作 × 路由表对账（写路径冒烟）---------------------
# 官方评测是 DOM 驱动的：在页面上填字段、点提交，走的是 form 的 action+method。
# 我方原有两道验证都碰不到这条通道——冒烟只做**无参 GET**，旅程脚本按
# 「路由表」生成请求（表里没有的路径它根本不会去试）。于是「页面里的
# action」和「路由表」两份事实各写各的，谁也不对账。
# 40 份已知交付实测（9/23 免费活服探针，零 LLM）：能装配起来的 24 份里
# 4 份有「一点就死」的表单，且这 4 份当日冒烟**全是绿的**——
# 2 份 action 指向路由表里不存在的路径（GET /notes、POST /api/login，
# 浏览器提交即 404），2 份提交 500（建表没跑 / 列名不存在）。
# 实现取法：复用冒烟模板的装配前段（择优算法与冒烟逐字同源，两处不同构
# 就等于闸测不到判分面——116-121 行的老教训），后段换成表单对账；
# 真提交跑在 code/ 的临时副本里，交付自带的库不会被探针写脏。
_FORM_TAIL = r'''
# ==== 表单动作 × 路由表对账（批次#43）====
import re as _qre
from urllib.parse import urlencode as _qenc

_qrules = []
if hasattr(app, "url_map"):
    for _qr in app.url_map.iter_rules():
        _qrules.append((str(_qr), set(_qr.methods) - {"HEAD", "OPTIONS"}))
else:
    for _qr in getattr(app, "routes", []) or []:
        _qp0 = getattr(_qr, "path", None)
        if _qp0:
            _qrules.append((_qp0, set(getattr(_qr, "methods", None) or ())))

_QNUL = "\x00"
_QANY = "\x01"


def _qrx(_rule):
    """路由规则 → 匹配串。`<path:...>`/`{x:path}` 跨斜杠（漏了它会把
    /static/js/app.js 这类真存在的目标判成「路由表里没有」= 假红）。"""
    _b = _qre.sub(r"<\s*path\s*:\s*[A-Za-z_][A-Za-z0-9_]*\s*>", _QANY, _rule)
    _b = _qre.sub(r"\{\s*[A-Za-z_][A-Za-z0-9_]*\s*:\s*path\s*\}", _QANY, _b)
    _b = _qre.sub(r"<[^>]+>", _QNUL, _b)
    _b = _qre.sub(r"\{[^}]+\}", _QNUL, _b)
    _e = _qre.escape(_b)
    return _qre.compile("^" + _e.replace(_qre.escape(_QANY), ".+")
                        .replace(_qre.escape(_QNUL), "[^/]+") + "/?$")


def _qfind(_path, _verb):
    """(路由在不在, 有没有别的动词注册过这条路径)。"""
    _other = False
    for _rule, _ms in _qrules:
        if _qrx(_rule).match(_path.rstrip("/") or "/"):
            if _verb in _ms:
                return True, False
            _other = True
    return False, _other


_QFORM = _qre.compile(r"<form\b([^>]*)>([\s\S]*?)</form>", _qre.I)
_QATTR = _qre.compile(r"\b(action|method)\s*=\s*(['\"])([^'\"]*)\2", _qre.I)
_QNAME = _qre.compile(r"\bname\s*=\s*(['\"])([^'\"]*)\1", _qre.I)
_QTYPE = _qre.compile(r"\btype\s*=\s*(['\"])([^'\"]*)\1", _qre.I)
_QWORD = _qre.compile(r"placeholder\s*=\s*(['\"])([^'\"]+)\1", _qre.I)


def _qcall(_method, _path, _data=None):
    """GET 拼 query、POST 送表单——只用两家客户端都有的方法名入口。
    （client.request 的签名在 Werkzeug/Starlette 之间不一致，传 data 直接
    TypeError；这里宁可退一步也不能把签名错当成应用崩溃。）"""
    if _method == "GET":
        _fn = client.get
        _url = _path + (("?" + _qenc(_data)) if _data else "")
        _kw = {}
    else:
        _fn = client.post
        _url = _path
        _kw = {"data": _data or {}}
    try:
        _r = _fn(_url, follow_redirects=True, **_kw)
    except TypeError as _te:                # Starlette 老版本不认逐请求参数
        if "follow_redirects" not in str(_te):
            raise
        _r = _fn(_url, **_kw)
    return getattr(_r, "status_code", 200)


_QPAGES = {}
for _qp in sorted({str(x) for x in _page_paths(app)}):
    if "<" in _qp or "{" in _qp or _qp.startswith("/api") or "static" in _qp:
        continue                            # 带参页与接口页留给旅程
    try:
        _qr = client.get(_qp)
        _QB = (_qr.get_data(as_text=True) if hasattr(_qr, "get_data")
               else getattr(_qr, "text", ""))
    except Exception:
        continue
    if _QB.lstrip().startswith(("{", "[")):
        continue
    _QPAGES[_qp] = _QB

_qissues = []
_qn = 0
for _qp, _qh in _QPAGES.items():
    for _qm in _QFORM.finditer(_qh):
        _qa = dict((k.lower(), v) for k, _q2, v in _QATTR.findall(_qm.group(1)))
        _qact = (_qa.get("action") or _qp).strip()
        if (not _qact or _qact.startswith(("http://", "https://", "#", "mailto:",
                                           "javascript:", "data:"))
                or "{{" in _qact or "{%" in _qact or "$" in _qact):
            continue                        # 模板/前端框架自己拼的目标，静态无从判定
        _qv = (_qa.get("method") or "get").upper()
        if _qv not in ("GET", "POST"):
            _qv = "POST"                    # put/delete 等表单方法浏览器也只发这两种之一
        _qpath = _qact.split("?")[0]
        if not _qpath.startswith("/"):
            _qpath = "/" + _qpath
        _qn += 1
        _qf = [x for x in _QNAME.findall(_qm.group(2)) if x[1]]
        _qhint = " 字段" + ",".join(sorted({x[1] for x in _qf})[:6])
        _qok, _qother = _qfind(_qpath, _qv)
        if not _qok:
            _qissues.append(
                f"页面 {_qp} 的表单提交到 {_qv} {_qpath}，路由表里没有这条"
                + ("（路径在、方法没注册 = 提交即 405）" if _qother else
                   "（提交即 404）")
                + _qhint + "——把 action 改成真实存在的路径与方法，"
                "或在装配层把这条路由注册上；本应用注册了 "
                f"{len(_qrules)} 条路由")
            continue
        _qw = [x[1] for x in _QWORD.findall(_qm.group(2))][:8] or ["sample"]
        _qd = {}
        for _qf in _qre.finditer(r"<(input|textarea|select)\b([^>]*)>",
                                 _qm.group(2), _qre.I):
            _qat = _qf.group(2)
            _qnm = _QNAME.search(_qat)
            if not _qnm or not _qnm.group(2):
                continue
            _qty = ((_QTYPE.search(_qat) or [None, "text"])[1] or "text").lower()
            if _qty in ("submit", "button", "reset", "file", "image"):
                continue
            if _qty in ("checkbox", "radio"):
                if "checked" in _qat.lower():
                    _qd[_qnm.group(2)] = "on"
                continue
            _qd[_qnm.group(2)] = _qw[len(_qd) % len(_qw)]
        try:
            _qst = _qcall(_qv, _qpath, _qd)
        except Exception as _qe:
            _qissues.append(
                f"页面 {_qp} 的表单 {_qv} {_qpath} 一提交就崩（"
                f"{type(_qe).__name__}: {str(_qe)[:90]}）" + _qhint
                + "——评测就是在这一页填好字段点提交，崩了这条需求整族判红")
            continue
        if _qst >= 500:
            _qissues.append(
                f"页面 {_qp} 的表单 {_qv} {_qpath} 提交返回 {_qst}" + _qhint
                + "——同上：填完点提交即服务端错误")
print(f"@@FORMS@@ n={_qn} issues={len(_qissues)}")
for _qi in _qissues[:8]:
    print("@@FORM-ISSUE@@", _qi)
# ==== 对账结束（探针始终以 0 退出：结论由父进程按标记行解读）====
raise SystemExit(0)
'''

# 装配前段直接切自冒烟模板：两道验证共用同一套应用择优算法
_VERIFY_ASSEMBLY_PREFIX = "_fa = _FieldAnchors()"


def _form_script() -> str:
    """拼出表单对账探针脚本（冒烟装配前段 + 对账后段）。"""
    if _VERIFY_ASSEMBLY_PREFIX not in _VERIFY_TEMPLATE:
        return ""
    return _VERIFY_TEMPLATE.split(_VERIFY_ASSEMBLY_PREFIX)[0] + _FORM_TAIL


# 三段脚本落在同一个临时目录：闸脚本按「同目录邻居」找前两段，
# RepoFixer 以 cwd=项目目录 执行它时才不会找不着北。
VERIFY_SCRIPT_NAME = "arcbench_smoke_verify.py"
FORMS_SCRIPT_NAME = "arcbench_smoke_forms.py"
GATE_SCRIPT_NAME = "arcbench_smoke_gate.py"
SMOKE_TIMEOUT = 180          # 基线冒烟（run_smoke 用）
FORM_TIMEOUT = 120           # 表单对账（run_form_probe 用）

_GATE_TEMPLATE = '''\
"""ArcBench 冒烟闸（自动生成）：基线冒烟 × 表单对账，红字与判定同口径。

上游 run_smoke 说什么，修复循环就被什么验收——两段脚本与本文件同目录。
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
code = Path(sys.argv[1]).resolve()


def _run(_cmd, _timeout, _cwd=None):
    return subprocess.run(_cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=_timeout, cwd=_cwd)


try:
    base = _run([__PY__, str(HERE / "__VERIFY__"), str(code)], __BASE_TIMEOUT__,
                str(code))
except Exception as exc:
    # 基线段跑不起来＝交付没通过（与 run_smoke 把超时判 FAIL 同口径）
    print("基线冒烟未能执行（" + type(exc).__name__ + ": " + str(exc)[:120] + "）")
    raise SystemExit(1)
print((base.stdout or "")[-1500:])
if (base.stderr or "").strip():
    print((base.stderr or "")[-500:])
if base.returncode != 0:
    raise SystemExit(base.returncode)

work = None
try:
    work = Path(tempfile.mkdtemp(prefix="arcbench-gate-forms-"))
    dst = work / "code"
    shutil.copytree(code, dst, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc"))
    pr = _run([__PY__, str(HERE / "__FORMS__"), str(dst)], __FORM_TIMEOUT__,
              str(dst))
    out = (pr.stdout or "") + (pr.stderr or "")
    if "@@FORMS@@" not in out:
        # 没跑起来（解释器报错/脚本被删/应用装不起）：分不清是工具坏了还是
        # 交付坏了，一律按工具失效放行——误拦一次交付的代价比漏一次大。
        print("[gate] 表单探针未跑成（rc=" + str(pr.returncode) + "），按工具失效放行")
        raise SystemExit(0)
except Exception as exc:
    # 探针自己失效（含超时）一律不拦交付：工具坏了不是应用缺陷
    print("[gate] 表单探针未跑成（" + type(exc).__name__ + "），按工具失效放行")
    raise SystemExit(0)
finally:
    if work is not None:
        shutil.rmtree(work, ignore_errors=True)
bad = [ln[len("@@FORM-ISSUE@@ "):].strip() for ln in out.splitlines()
       if ln.startswith("@@FORM-ISSUE@@")]
if bad:
    print("[form] 页面表单与路由表对不上:")
    for ln in bad[:8]:
        print("  " + ln)
    raise SystemExit(1)
raise SystemExit(0)
'''


def write_gate_scripts(python: str | None = None) -> Path:
    """把「判定」写成可独立执行的闸脚本，返回其路径（复测与判定同闸）。

    存在的理由：auto_repair 的修复循环用 test_cmd 判自己修好没有。若复测只看
    基线冒烟而判词里带着 [form] 红，循环就会朝「让基线绿」收敛——锚点闸当年
    正是这样三轮分文未收敛（见 _ANCHOR_GATE_TEMPLATE 的取证）。
    """
    d = Path(tempfile.gettempdir())
    (d / VERIFY_SCRIPT_NAME).write_text(_VERIFY_TEMPLATE, encoding="utf-8")
    script = _form_script()
    if script:
        (d / FORMS_SCRIPT_NAME).write_text(script, encoding="utf-8")
    gate = d / GATE_SCRIPT_NAME
    gate.write_text(
        _GATE_TEMPLATE
        .replace("__VERIFY__", VERIFY_SCRIPT_NAME)
        .replace("__FORMS__", FORMS_SCRIPT_NAME)
        # 复测总预算必须小于 RepoFixer 的 test_timeout（缺省 300s）：两段各让
        # 出余量，宁可内部先判超时，也不能被外层熔断成「验证命令超时」这种
        # 修复者读不懂的信号。
        .replace("__BASE_TIMEOUT__", str(SMOKE_TIMEOUT - 10))
        .replace("__FORM_TIMEOUT__", str(FORM_TIMEOUT - 30))
        .replace("__PY__", repr(python or sys.executable)),
        encoding="utf-8")
    return gate


def run_form_probe(code_dir: Path, python: str | None = None,
                   timeout: int = FORM_TIMEOUT) -> list[str]:
    """在 code/ 的临时副本上跑表单×路由对账，返回缺陷描述列表（空=没问题）。

    副本是硬要求：对账要真提交，真提交会写库——探针不能把测试数据烙进
    交付自带的 sqlite（评测看见多出来的行同样是保真缺陷）。
    探针自己炸了（超时/装不起应用/脚本没跑起来）一律返回空列表：
    这是工具失效，不是应用缺陷，不该拦交付。
    """
    code_dir = Path(code_dir).resolve()
    script = _form_script()
    if not script:
        return []
    work = Path(tempfile.mkdtemp(prefix="arcbench-formprobe-"))
    try:
        dst = work / "code"
        shutil.copytree(code_dir, dst,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        path = work / FORMS_SCRIPT_NAME
        path.write_text(script, encoding="utf-8")
        proc = subprocess.run(
            [python or sys.executable, str(path), str(dst)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            timeout=timeout, cwd=str(dst),
        )
    except Exception:
        return []
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    return [ln[len("@@FORM-ISSUE@@ "):].strip()
            for ln in out.splitlines() if ln.startswith("@@FORM-ISSUE@@")]


def run_smoke(code_dir: Path, python: str | None = None) -> tuple[bool, str]:
    """确定性集成冒烟。返回 (是否通过, 报告文本)。"""
    code_dir = Path(code_dir).resolve()
    if not code_dir.is_dir():
        return False, f"code 目录不存在: {code_dir}"

    try:
        shims = auto_shim_imports(code_dir)
    except Exception:
        shims = []
    try:
        bound = auto_bind_submodules(code_dir)
        shims = shims + [f"{p}(子模块绑定)" for p in bound]
    except Exception:
        pass
    _clear_pycache(code_dir)
    verify = Path(tempfile.gettempdir()) / VERIFY_SCRIPT_NAME
    verify.write_text(_VERIFY_TEMPLATE, encoding="utf-8")

    try:
        proc = subprocess.run(
            [python or sys.executable, str(verify), str(code_dir)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            timeout=SMOKE_TIMEOUT,
            cwd=str(code_dir),
        )
    except subprocess.TimeoutExpired:
        # 与 _probe_routes 同口径：冒烟超时是「没通过」，不是「冒烟器炸了」。
        # 上抛会穿过 verify_delivery 的冒烟段（该段无 try），把已经写完的
        # 项目换成一次崩溃退出。
        return False, (
            f"冒烟验证超时（{SMOKE_TIMEOUT}s 熔断）：导入应用模块时疑似被阻塞——"
            "典型成因是模块级 while True/常驻服务/等待输入。"
            "应用应可 import 而不阻塞（服务启动放 __main__ 守卫内）。")
    except OSError as exc:
        return False, f"冒烟验证启动失败: {exc!r}"
    report = (proc.stdout or "") + (proc.stderr or "")[-500:]
    ok = proc.returncode == 0
    # 内存哨兵（官方环境 2GB 内存取证）：应用进程峰值超限判 FAIL——
    # Chromium 约占 1GB，应用必须留足余量。阈值环境变量可调。
    mem_mb = _parse_mem_peak(report)
    limit_mb = float(os.environ.get("ARCBENCH_MEM_LIMIT_MB", "512") or 512)
    if mem_mb >= 0 and mem_mb > limit_mb:
        ok = False
        report = report + (
            f"\n[mem] 应用峰值内存 {mem_mb:.0f}MB 超过 {limit_mb:.0f}MB 限额"
            "（官方运行环境仅 2GB，含浏览器）")
    if shims:
        report = "[shim] 机械垫片已生成: " + ", ".join(shims) + " → " + report
    if ok:
        # 绿了才查写路径：红的时候修复环已经拿到判词，且探针要再启一次应用
        issues = run_form_probe(code_dir, python=python)
        if issues:
            ok = False
            report += ("\n[form] 页面表单与路由表对不上（评测在页面上点提交，"
                       "冒烟只 GET 所以此前全程看不见）:\n  " + "\n  ".join(issues))
    return ok, report.strip()


def _parse_mem_peak(report: str) -> float:
    """从冒烟报告中解析 @@MEM@@ 峰值内存；缺失返回 -1（不判罚）。"""
    m = re.search(r"@@MEM@@(-?\d+(?:\.\d+)?)", report or "")
    return float(m.group(1)) if m else -1.0


def _llm_from(settings):
    """平台侧验收 LLM。模型级备胎链（平台首单取证：验收修复阶段
    pro 超时×3 全灭且无备胎，RuntimeError 崩穿 main → 平台 exit 1）
    ——主模型失败后依 settings.models 逐备胎，全灭上抛由调用方容错。"""
    from app.utils.budget import BudgetExceededError, TaskCancelledError
    from app.utils.model_client import ModelClient

    mc = ModelClient(settings)
    chain = tuple(settings.models[:3]) or ("openai/gpt-4o",)

    def llm(system: str, user: str) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        last_exc: Exception | None = None
        for model in chain:
            try:
                content = mc.chat(model, messages).content or ""
            except (BudgetExceededError, TaskCancelledError):
                # 总闸不是「这条腿废了」：换腿续跑＝把中止指令改成多烧几腿
                raise
            except RuntimeError as exc:
                last_exc = exc
                continue
            if not content.strip():
                # gen-4 取证:空响应会让下游 plan 解析"输入文本为空"
                # 直接死——视为该模型失败,接力下一模型
                last_exc = RuntimeError(f"{model} 返回空内容")
                continue
            return content
        raise RuntimeError(f"验收 LLM 全链失败（{chain}）: {last_exc}")

    return llm


def _extract_body(text: str) -> str:
    """剥掉 LLM 输出的 markdown 围栏（如有）。"""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t)
    return t.strip()


_JOURNEY_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([\w.]+)", re.MULTILINE)


def _journey_script_dangers(candidate: str, app_module: str,
                            code_dir: Path) -> list[str]:
    """旅程脚本生成期拦截（keep7w 取证家族）：在通用危险扫描之上
    叠加旅程专属禁令——直连 sqlite3 与应用内部模块导入。

    脚本连错库报 `no such table` 从未走到业务断言，却会污染应用修复
    通道空转烧轮次——第一道门就拦下，送回重生成。"""
    from app.execution.local_executor import scan_dangerous
    dangers = list(scan_dangerous(candidate))
    internal = {app_module.split(".")[0]}
    for child in code_dir.iterdir():
        if child.is_dir() and (child / "__init__.py").exists():
            internal.add(child.name)
        elif child.suffix == ".py":
            internal.add(child.stem)
    for m in _JOURNEY_IMPORT_RE.finditer(candidate):
        top = m.group(1).split(".")[0]
        if top == "sqlite3":
            dangers.append(
                "import sqlite3: 旅程脚本禁止直连数据库"
                "（数据断言一律取自 HTTP 响应）")
        elif top in internal:
            dangers.append(
                f"import {m.group(1)}: 禁止导入应用内部模块"
                "（只许通过 test client 走接口）")
    return dangers


def _probe_routes(code_dir: Path) -> tuple[str, list[str]] | None:
    """定位组装模块并倾倒真实路由表；(app_module, routes) / None。"""
    code_dir = Path(code_dir).resolve()
    _clear_pycache(code_dir)
    probe = Path(tempfile.gettempdir()) / "arcbench_probe_routes.py"
    probe.write_text(_PROBE_TEMPLATE, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(probe), str(code_dir)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            timeout=180,
            cwd=str(code_dir),
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    marker = "@@ROUTES@@"
    for line in (proc.stdout or "").splitlines():
        if line.startswith(marker):
            try:
                info = json.loads(line[len(marker):])
            except ValueError:
                continue
            module = str(info.get("app_module") or "").strip()
            routes = [str(r) for r in info.get("routes") or [] if str(r).strip()]
            if module and routes:
                return module, routes
    return None


def _run_script(cmd: list[str], timeout: int = 120) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            cwd=str(cmd[-1]),
        )
    except subprocess.TimeoutExpired as exc:
        return False, f"旅程脚本超时（{timeout}s）: {exc!r}"
    except OSError as exc:
        return False, f"旅程脚本启动失败: {exc!r}"
    report = (proc.stdout or "") + (proc.stderr or "")[-800:]
    return proc.returncode == 0, report.strip()


def run_journey_script(script_path: Path, code_dir: Path) -> tuple[bool, str]:
    """执行旅程验收脚本。返回 (是否通过, 报告文本)。"""
    code_dir = Path(code_dir).resolve()
    _clear_pycache(code_dir)
    return _run_script(
        [sys.executable, str(Path(script_path).resolve()), str(code_dir)]
    )


def _journey_acceptance_brief(requirement: str, budget: int = 5000) -> str:
    """旅程生成器的需求摘要：逐节点验收行，替代盲切 head 4000。

    keep#3 夜间取证：渲染文本前 4000 字符＝技术栈规则 1-16 全文，
    旅程断言从未见过任何逐字验收文案——「凭想象写定位器」在旅程
    通道的翻版（自测通道 9/20 已修，见 :1154 注释同源事故）。
    无 ### 结构的纯文本需求回落旧 head 切片。
    P1-C：主旅程置顶，逼跨模块串起来。
    v45：超预算不再静默 break——按未命中/GWT 密度轮换纳入。
    """
    if not requirement:
        return ""
    journey_head = ""
    try:
        from app.utils.main_journeys import render_main_journeys
        journey_head = render_main_journeys(requirement)
    except Exception:
        journey_head = ""
    try:
        from app.utils.selftest_gate import _split_atomic_nodes
        nodes, _g = _split_atomic_nodes(requirement)
    except Exception:
        nodes = []
    if not nodes:
        return journey_head + requirement[:4000]
    head = requirement.split("技术栈硬性要求", 1)[0].strip()[:600]
    prefer: list[str] = []
    try:
        from app.acceptance_compile import compile_checklists_from_text
        prefer = [
            c.req_id for c in compile_checklists_from_text(requirement)
            if c.behavior_constraints and not (
                c.control_labels or c.seed_entities)
        ]
    except Exception:
        prefer = []

    def _chunk_of(nid_text: tuple) -> str:
        _nid, text = nid_text
        keep = [ln for ln in text.splitlines()
                if ln.startswith("### ")
                or ln.strip().startswith(
                    ("GIVEN", "WHEN", "THEN", "AND", "BUT"))
                or ln.strip().startswith("- 场景")]
        if len(keep) <= 1:
            body = [ln for ln in text.splitlines()
                    if not ln.startswith(("##", "###", "依赖："))]
            header = keep[0] if keep else f"### {_nid}"
            keep = [header, "\n".join(body)[:240]]
        return "\n".join(keep)

    remain = max(0, budget - len(journey_head) - len(head) - 40)
    try:
        from app.utils.coverage_rotation import select_under_budget
        picked = select_under_budget(
            nodes,
            lambda nt: len(_chunk_of(nt)),
            remain,
            prefer_ids=prefer,
            head_size=0,
        )
        chunks = [_chunk_of(nt) for nt in picked]
    except Exception:
        chunks = []
        size = 0
        for nt in nodes:
            chunk = _chunk_of(nt)
            if size + len(chunk) > remain:
                break
            chunks.append(chunk)
            size += len(chunk)
    return (journey_head + head + "\n\n【逐节点验收（原文逐字）】\n"
            + "\n".join(chunks))


def _journey_gate(
    code_dir: Path,
    project_dir: Path,
    requirement: str,
    llm,
    max_app_rounds: int,
    notes: list[str],
) -> tuple[bool, str]:
    """旅程验收：生成 → 执行 → 脚本自修复一轮 → 应用修复（RepoFixer）。

    返回 (是否通过, 报告)。生成基础设施故障 = SKIP（通过），不冤枉
    基础冒烟已绿的应用；旅程断言失败 = 应用缺陷，修复直到通过。
    """
    probe = _probe_routes(code_dir)
    if probe is None:
        notes.append("[journey] SKIP: 路由探测失败")
        return True, "skip"
    app_module, routes = probe
    notes.append(f"[journey] {app_module} 共 {len(routes)} 条路由")
    brief = _journey_acceptance_brief(requirement)

    def gen(user_extra: str = "") -> str:
        return _extract_body(llm(
            _JOURNEY_SYSTEM,
            _JOURNEY_USER.format(
                requirement=brief,
                app_module=app_module,
                routes="\n".join(routes[:80]),
            ) + user_extra,
        ))

    jpath = Path(tempfile.gettempdir()) / "arcbench_journey.py"
    script: str | None = None
    best_script: str | None = None  # 执行报告中信息量最大的合法脚本版本
    last_report = ""
    best_report = ""  # 信息量最大的一次真实执行报告（修应用时交给 LLM）
    best_steps = 0  # 已接受版本的最大步数（缩水检测基线，r8 取证）
    for attempt in (1, 2):
        try:
            body = gen("" if attempt == 1 else
                       "\n\n上一版脚本执行失败输出（修正脚本本身的路径/参数/"
                       "选择器错误；**禁止缩减旅程覆盖范围**——需求要求的注册/"
                       "登录/查询/下单等步骤一个都不能少，应用缺能力就保留"
                       "断言如实失败，缺失将由应用修复通道补齐）：\n"
                       + last_report[-800:])
        except Exception as exc:
            notes.append(f"[journey] SKIP: 脚本生成失败 {exc!r}")
            return True, "skip"
        candidate = _JOURNEY_BOILERPLATE.replace(
            "__APP_MODULE__", app_module
        ).replace("__BODY__", body)
        # 语法预检：LLM 可能把说明文字漏进代码体（r5 取证：全角冒号
        # U+FF1A SyntaxError）——语法不合格就地重生成，绝不写入执行，
        # 更不能把脚本 bug 当应用缺陷去修（修复验证命令=旅程脚本，
        # 坏脚本下的应用修复注定空转）。
        try:
            compile(candidate, "<journey>", "exec")
        except SyntaxError as exc:
            last_report = f"旅程脚本语法不合格: {exc}"
            notes.append(f"[journey] 第{attempt}版脚本语法不合格，重生成")
            continue
        dangers = []
        try:
            # 只扫 LLM 生成段：样板自身的 from app_module import create_app
            # 是框架合法装配，不算脚本导入违禁
            dangers = _journey_script_dangers(body, app_module, code_dir)
        except Exception:
            dangers = []
        if dangers:
            last_report = "危险 API 扫描未通过: " + "; ".join(dangers[:5])
            notes.append(f"[journey] 第{attempt}版脚本被扫描拦截，重生成")
            continue
        script = candidate
        # r8 取证：自修复脚本「缩水迁就残缺应用」（v1 八步旅程 → v2 只查
        # health）会把空心 PASS 放行——真实评测 0 分。步数不得低于 v1：
        # 缩水版按无效处理，落应用修复通道（宁可诚实 FAIL）。
        steps = len(_JOURNEY_STEP_RE.findall(body))
        if steps and steps < best_steps:
            last_report = (
                f"自修复脚本步数缩水（{best_steps}→{steps}），疑似迁就残缺应用"
            )
            notes.append(f"[journey] 第{attempt}版脚本缩水被拒收")
            continue
        best_steps = max(best_steps, steps)
        jpath.write_text(script, encoding="utf-8")
        ok, last_report = run_journey_script(jpath, code_dir)
        if len(last_report) > len(best_report):
            best_report = last_report
            best_script = script
        if ok:
            notes.append("[journey] PASS")
            return True, ""
        notes.append(
            f"[journey] 第{attempt}版脚本执行失败"
            + ("（自修复重生成）" if attempt == 1 else "")
        )

    if script is None:
        # 两版都没能产出可执行的合法脚本（扫描拦截/语法不合格）：
        # 不放行也不冤枉应用——SKIP 交人工
        notes.append("[journey] SKIP: 脚本两版均不可执行（扫描/语法）")
        return True, "skip"

    # r11 取证：脚本自身 NameError/AttributeError（如用错客户端变量名）
    # 说明脚本从未跑到断言——这是【脚本缺陷】，送 RepoFixer 修应用注定
    # 空转甚至误伤。再给一版重生成机会，仍败则 SKIP 交人工，绝不修应用。
    if _is_script_defect(last_report):
        notes.append("[journey] 脚本自身异常（非应用缺陷）→ 重生成第3版")
        try:
            body = gen("\n\n上一版脚本自身报错（修脚本，勿改应用行为假设）：\n"
                       + last_report[-800:])
        except Exception:
            body = None
        if body:
            candidate = _JOURNEY_BOILERPLATE.replace(
                "__APP_MODULE__", app_module
            ).replace("__BODY__", body)
            try:
                compile(candidate, "<journey>", "exec")
                script = candidate
                jpath.write_text(script, encoding="utf-8")
                ok, last_report = run_journey_script(jpath, code_dir)
                if len(last_report) > len(best_report):
                    best_report = last_report
                    best_script = script
                if ok:
                    notes.append("[journey] PASS（第3版）")
                    return True, ""
            except SyntaxError:
                pass
        notes.append("[journey] SKIP: 脚本三版均自身异常（交人工，不修应用）")
        return True, "skip"

    # 脚本本身两轮收敛了但断言仍失败 → 应用缺陷，进入修复循环
    notes.append("[journey] 旅程断言失败 → RepoFixer 修复应用")
    # r7d 取证：修复可能把应用越修越残（业务路由 11→3 全丢）——修复前
    # 备份 code/，修复后路由面退化即回滚；修复指令携带完整路由面快照
    backup = Path(tempfile.mkdtemp()) / "code_backup"
    try:
        shutil.copytree(
            code_dir, backup, ignore=shutil.ignore_patterns("__pycache__")
        )
    except Exception as exc:
        # 备份失败必须留痕：回滚段以 backup.is_dir() 为前置断言——静默
        # 失败 + 路由退化双条件会把整个 code/ 清空（保险丝自身带电，
        # Qoder 交叉审查 9/21 取证）
        notes.append(f"[journey] 修复前备份失败 {exc!r}（本次禁用回滚）")
    try:
        from app.agents.repo_fixer import RepoFixer
        from app.utils.schema_audit import audit_schema

        # r15 取证：诊断发现数应兑换成修复轮次——带着确定性结论却只有
        # 基础轮次，等于把到手的定位信息浪费掉。
        try:
            audit_findings = audit_schema(code_dir)
        except Exception:
            audit_findings = []
        extra_rounds = min(len(audit_findings), 4) // 2  # 0-2 轮增量
        rounds = max_app_rounds + extra_rounds
        if extra_rounds:
            notes.append(
                f"[journey] 审计发现 {len(audit_findings)} 处 → "
                f"修复轮次 {max_app_rounds}+{extra_rounds}")

        fixer = RepoFixer(
            llm, project_dir,
            test_cmd=[sys.executable, str(jpath), str(code_dir)],
            max_rounds=rounds,
        )
        fixer.fix(
            "旅程验收失败（评测方以真实浏览器走用户旅程，本脚本是同进程"
            "等价验收）。失败输出如下，请最小化修复使旅程通过（典型："
            "查询/列表必须返回数据库种子数据而非硬编码列表、缺失页面/"
            "路由补齐、响应字段补齐）。\n"
            + _schema_audit_section(code_dir, findings=audit_findings)
            + _anchor_coverage_section(code_dir, requirement)
            + _interface_drift_section(code_dir, project_dir)
            + _seed_audit_section(code_dir, requirement)
            + _language_audit_section(code_dir, requirement)
            + "硬性约束：修复后应用必须仍注册下列全部路由（方法不得改动、"
            "不得删除任何既有路由）——\n"
            + "\n".join(routes)
            + "\n禁止修改 tests/ 目录与旅程脚本。\n"
            + best_report[-1500:]
        )
    except Exception as exc:
        notes.append(f"[journey] 修复通道异常 {exc!r}")
    if best_script is not None:
        # r7d：修复后终验必须用「最有效的脚本版本」——自修复轮可能产出
        # 退化脚本（SystemExit 占位），复用最后一版会把修好的应用判死
        jpath.write_text(best_script, encoding="utf-8")
    ok, report = run_journey_script(jpath, code_dir)
    if not ok:
        # 路由面退化守卫：修复后探针路由数明显缩水 → 回滚到修复前状态
        post = _probe_routes(code_dir)
        if post is None or len(post[1]) < len(routes) - 1:
            if not backup.is_dir():
                # 前置断言：备份不存在时绝不 rmtree——「先删后恢复」在
                # 备份缺失时等于清空 code/（满分夜战成果一把归零）
                notes.append(
                    f"[journey] 路由面退化（{len(routes)}→"
                    f"{len(post[1]) if post else 0}）但无可用备份，保留现状"
                )
            else:
                try:
                    shutil.rmtree(code_dir)
                    shutil.copytree(backup, code_dir)
                    notes.append(
                        f"[journey] 修复致路由面退化（{len(routes)}→"
                        f"{len(post[1]) if post else 0}），已回滚修复"
                    )
                except Exception:
                    notes.append("[journey] 路由面退化但回滚失败")
    notes.append(f"[journey] 修复后 {'PASS' if ok else 'FAIL'}")
    if not ok:
        return False, last_report[-300:]
    return True, ""


def _repair_blocked() -> str:
    """LLM 修复通道开工前的预算体检：返不可开工的原因，可修则返空串。

    彩排取证（shape-mini，9/23）：总闸在验收段被打穿后，三轮修复各自瞬时
    raise 在同一行「任务 token 总预算已耗尽」上——异常被下方 except 吞成一条
    note，循环照进下一轮，于是零进展、零修复、墙钟照烧，最后 rc=0 交出一份
    明知是坏的交付。开工前判一次就够了：钱不会在修复途中变多。
    零 LLM 的机械修复（run_all_fixers）不受此限——它不花钱。
    """
    try:
        from app.utils.budget import get_active_budget_guard

        guard = get_active_budget_guard()
    except Exception:
        return ""
    if guard is None:
        return ""
    if guard.exceeded:
        return f"总闸已耗尽 {guard.summary()}"
    if guard.repair_reserve_ratio > 0 and not guard.repair_fund_intact:
        return f"修复保留额已动用 {guard.summary()}"
    return ""


def _failure_sig(*parts: str) -> str:
    """一轮失败的指纹（空白归一 + 数字抹平），用于识别「修了等于没修」。

    keep-r1 彩排取证：R2 与 R3 在同一条 seed 断言上各自失败（`expected pinned
    seed 'Sprint goals' in /api/notes, got []` 重复 4 次），repo_fix 对同一文件
    连续两次交出语法非法补丁（views.py 138 行 / 116 行）——行号在变、根因没变，
    所以数字必须抹平后再比。指纹相同即证明这一轮的修复没有改变可观察失败。
    """
    blob = " | ".join(
        re.sub(r"\d+", "#", re.sub(r"\s+", " ", p or "")).strip()
        for p in parts if p)
    return blob[:400]


def _beat(project_dir: Path, stage: str, detail: str = "") -> None:
    """验收阶段直接写心跳（r18 误判教训：verify 阶段心跳冻结 6 小时
    被误判为挂死——排障者需要「验收进行到哪一步」的实时信号）。"""
    try:
        import time as _time

        hb = Path(project_dir) / "sessions" / "heartbeat.json"
        hb.parent.mkdir(parents=True, exist_ok=True)
        hb.write_text(json.dumps({
            "timestamp": _time.strftime("%Y-%m-%d %H:%M:%S"),
            "stage": stage,
            "last_event": "verify",
            "module": detail[:60],
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    try:
        # 2026-09-19 本地首跑取证：看门狗只认 Pipeline._emit 的阶段变更，
        # 验收期 5 小时活跃修复被误判「200 分钟无进展」强杀——验收阶段
        # 切换同样是进展。
        from app.pipeline import touch_progress

        touch_progress()
    except Exception:
        pass


def verify_delivery(
    project_dir: Path,
    requirement: str,
    settings,
    max_app_rounds: int = 3,
    max_verify_rounds: int = 3,
    requirements_dir: Path | None = None,
    probe_green: bool = False,
    repair_budget_s: float = 0,
) -> tuple[bool, str]:
    """交付前自检闭环：冒烟→修复→旅程→修复→循环直到全过或轮次耗尽。

    generation-5 取证：旧版为一次性串行（冒烟→旅程），任何一段失败
    直接返回 FAIL，即使 auto_repair 已部分修好了代码也不会再试。
    新版将冒烟+旅程作为统一自检循环：每轮修复后从头验证，
    全部通过才交付——「验收是教练，不是评判者」。

    probe_green（532193）：抢先导出起服探针已 health+home 全绿时，
    再烧 LLM 修环只会推迟 Stage3。快车道：至多 1 轮冒烟+机械修复，
    跳过 LLM auto_repair / 旅程 LLM 环，尽快交评分。
    """
    project_dir = Path(project_dir).resolve()
    code_dir = project_dir / "code"
    notes: list[str] = []
    all_reports: list[str] = []
    all_passed = False
    prev_sig = ""
    if probe_green:
        # 探针已绿 ≠ 作者工厂可起 / 表单写路径通。
        # v53 刀B：create_app 池试装；v52：表单×路由对账。任一红 → 退快车道。
        # v53.1（批次#78 评审 #1）：守卫**失败关闭**——基础设施异常视为红，
        # 不得静默 [] 放行（异常=不知道，不知道=不能放）。
        form_issues: list[str] = []
        factory_issues: list[str] = []
        try:
            from app.utils.factory_pool import probe_author_factories_safe
            factory_issues, _infra = probe_author_factories_safe(code_dir)
        except Exception as exc:
            factory_issues = [f"工厂池探针基础设施失败: {exc!r}"[:200]]
        try:
            form_issues = run_form_probe(code_dir)
        except Exception as exc:
            form_issues = [f"表单对账探针基础设施失败: {exc!r}"[:200]]
        if factory_issues or form_issues:
            why = []
            if factory_issues:
                why.append(f"作者create_app失败{len(factory_issues)}处")
                print(
                    "[probe-fast] 作者工厂试装红: "
                    + "; ".join(factory_issues[:3]),
                    flush=True,
                )
            if form_issues:
                why.append(f"表单×路由未对齐{len(form_issues)}处")
                print(
                    f"[probe-fast] 表单×路由未对齐 {len(form_issues)} 处，"
                    "退出快车道走完整验收",
                    flush=True,
                )
            notes.append(
                "[probe-fast→full] " + "; ".join(why) + ": "
                + "; ".join((factory_issues + form_issues)[:5])
            )
            probe_green = False
        else:
            import time as _time
            deadline = _time.monotonic() + max(30.0, float(repair_budget_s or 8 * 60))
            msg = (
                "[probe-fast] 探针已绿且作者工厂/表单×路由对齐，"
                "仅修入口控件后交 Stage3"
            )
            print(msg, flush=True)
            try:
                if _time.monotonic() < deadline and max_app_rounds != 0:
                    from app.utils.checklist_priority import checklist_priority_note
                    note = checklist_priority_note(requirement, max_nodes=4)
                    auto_repair(
                        project_dir, settings, max_rounds=1,
                        requirement=requirement,
                        priority_note=(
                            "【入口优先】官方评测从首页进。先让首页出现需求里的"
                            "入口控件（可点击的链接或按钮，文案逐字），再谈其它。\n"
                            + note
                        ),
                    )
            except Exception as exc:
                msg += f"（修补降级: {exc!r}"[:120] + "）"
            return True, msg
    _beat(project_dir, "验收-启动")

    # --- Phase 0: 体检前移（v42-3，零 LLM、秒级）---
    # 官方判分是从 / 出发爬「渲染可见」的逐字事实；这个口径原先只在 Phase 3
    # 自测闸里跑一次，而它排在整个验收循环**之后**。sheet 首跑实证：预算在
    # 循环中途断气，那条免费的判分段一次都没走到，首页形态错了 10 小时无人知。
    # 这里复用同一段（specs_dir=None ⇒ 导出官方布局→起服→健康探针→编译清单，
    # 不碰 node/playwright），把缺口带 REQ id 交给下面现有的修复轮搭车，
    # 不额外开一次 LLM 调用。
    pre_txt = ""
    prefer_ids: list[str] = []
    if requirements_dir:
        _beat(project_dir, "验收-前置体检")
        try:
            from app.utils.selftest_gate import run_selftests

            pc, pf, pfail, pnotes = run_selftests(
                project_dir, None, port_hint=3409,
                requirements_dir=requirements_dir)
            prefer_ids = []
            try:
                import json
                import re
                cov_path = (Path(project_dir) / "sessions"
                            / "atomic_coverage.json")
                if cov_path.is_file():
                    raw = json.loads(cov_path.read_text(encoding="utf-8"))
                    prefer_ids.extend(raw.get("uncovered") or [])
                    prefer_ids.extend(list((raw.get("assigned") or {}).keys()))
                spec_path = (Path(project_dir) / "sessions"
                             / "spec_req_coverage.json")
                if spec_path.is_file():
                    raw = json.loads(spec_path.read_text(encoding="utf-8"))
                    prefer_ids.extend(raw.get("missing") or [])
                for line in (pfail or []):
                    m = re.search(r"\bREQ-[\w.-]+\b", str(line))
                    if m:
                        prefer_ids.append(m.group(0))
            except Exception:
                prefer_ids = []
            try:
                from app.utils.coverage_rotation import rotate_lines
                gap = rotate_lines(pfail or [], prefer_ids=prefer_ids, limit=20)
            except Exception:
                gap = (pfail or [])[:20]
            notes.append(
                f"[precheck] 逐字事实 {pc}/{pc + pf} 命中"
                + (f"（缺 {len(pfail)}）" if pf else ""))
            if gap:
                pre_txt = (
                    "\n【官方口径体检缺口（从首页爬取渲染可见文案判出，"
                    "评测方同口径；按 REQ id 定位需求条目；未命中优先轮换）】\n"
                    + "\n".join(f"- {f}" for f in gap))
                all_reports.append(
                    f"[precheck] 逐字事实未命中 {len(pfail)} 条"
                    f"（前 {len(gap)} 条见修复指令）")
            elif pc:
                notes.append(f"[precheck] 官方口径全绿 {pnotes[-120:]}")
            else:
                # 0/0 不是「全绿」：编译清单没抽出可判的逐字事实（或需求
                # 目录为空），报告必须说「没信号」，否则下一轮排障会把
                # 「眼睛没睁开」读成「看过了，没问题」。
                notes.append(
                    f"[precheck] 零信号（无逐字事实可判）{pnotes[-120:]}")
        except Exception as exc:
            # 前置体检是眼睛不是闸：它自己摔了不得带走验收
            notes.append(f"[precheck] 异常降级（不影响后续验收）: {exc!r}"[:160])
            prefer_ids = []
            gap = []
    else:
        notes.append("[precheck] SKIP（无需求清单目录，编译判分环无源可判）")

    for verify_round in range(1, max_verify_rounds + 1):
        _beat(project_dir, f"验收-第{verify_round}轮")

        # --- Phase 1: 冒烟 ---
        ok, report = run_smoke(code_dir)
        if not ok:
            # 零 LLM 机械修复先出牌（确定性收敛，不烧 token；用户指令
            # 「修复不能靠概率」）。机械修复后复烟，修好则跳过 LLM 通道。
            _beat(project_dir, f"验收-R{verify_round}-机械修复")
            try:
                mech = run_all_fixers(code_dir, collect_ddl(code_dir))
            except Exception as exc:
                mech = {}
                notes.append(f"[R{verify_round}][mech-fix] 异常降级: {exc!r}"[:120])
            if mech:
                notes.append(
                    f"[R{verify_round}][mech-fix] "
                    + "; ".join(f"{k}×{len(v)}" for k, v in mech.items()))
                _beat(project_dir, f"验收-R{verify_round}-机械复烟")
                ok, report = run_smoke(code_dir)
        if not ok:
            notes.append(f"[R{verify_round}][smoke] FAIL → auto_repair")
            blocked = _repair_blocked()
            if blocked:
                # 不假装在修：一句话交代为什么停修，随后由轮末指纹判定收手
                ok = False
                report = f"冒烟修复未开工（{blocked}）"
                notes.append(f"[R{verify_round}][smoke] SKIP LLM 修复：{blocked}")
            elif max_app_rounds <= 0:
                notes.append(
                    f"[R{verify_round}][smoke] SKIP LLM 修复：快车道"
                    f"（max_app_rounds={max_app_rounds}）")
            else:
                _beat(project_dir, f"验收-R{verify_round}-冒烟修复")
                try:
                    from app.utils.checklist_priority import checklist_priority_note
                    from app.utils.atomic_coverage import (
                        CoverageReport, coverage_priority_note,
                    )
                    cov_note = ""
                    try:
                        import json
                        cov_path = (Path(project_dir) / "sessions"
                                    / "atomic_coverage.json")
                        if cov_path.is_file():
                            raw = json.loads(
                                cov_path.read_text(encoding="utf-8"))
                            cov_note = coverage_priority_note(CoverageReport(
                                required=list(raw.get("required") or []),
                                owned=dict(raw.get("owned") or {}),
                                uncovered=list(raw.get("uncovered") or []),
                                duplicates=dict(raw.get("duplicates") or {}),
                                assigned=dict(raw.get("assigned") or {}),
                            ))
                    except Exception:
                        cov_note = ""
                    ok, report = auto_repair(
                        project_dir, settings, max_rounds=max_app_rounds,
                        requirement=requirement,
                        priority_note=_home_route_priority_note(report)
                        + cov_note
                        + checklist_priority_note(
                            requirement, prefer_ids=prefer_ids)
                        + pre_txt,
                    )
                except Exception as exc:
                    ok = False
                    report = f"自动修复异常: {exc!r}"[:400]
            notes.append(f"[R{verify_round}][smoke] {'PASS' if ok else 'FAIL'}")
            if not ok:
                all_reports.append(f"[R{verify_round}] smoke FAIL: {report[-200:]}")
                sig = _failure_sig(report)
                if _repair_blocked():
                    # 修复已无钱开工，下一轮只会重复同一个失败
                    break
                if sig and sig == prev_sig:
                    # keep-r1 取证：同一条 seed 断言在 R2/R3 各自失败 4 次
                    notes.append(
                        f"[R{verify_round}] 冒烟失败指纹与上一轮相同"
                        "（修复换不来变化）→ 停止空转，按现状交付")
                    break
                prev_sig = sig
                if probe_green:
                    notes.append(
                        "[probe-fast] 冒烟仍红但导出探针已绿 → 停止修环，"
                        "按现状交 Stage3（评分 > 空烧）")
                    break
                continue  # smoke 还没过，不进旅程，直接下一轮

        if probe_green:
            # 532193：探针全绿后仍进锚点/旅程/自测 LLM 环 → Stage3 永不启动。
            # 起服契约已满足，快车道到此收束。
            notes.append(
                f"[probe-fast] 冒烟{'过' if ok else '未过'}；导出探针已绿 → "
                "跳过锚点/旅程/自测 LLM，交 Stage3")
            all_passed = bool(ok)
            break

        # --- Phase 1.5: 锚点覆盖修复（平台 v6 取证：全盘落空根因）---
        # 需求带引号文案（"Take a note"、"Sprint goals" 等）是评测方
        # 逐字断言的契约——翻译/改写即挂分。修复的验证信号 = 锚点探针
        # 本身（冒烟本来就过，对文案缺口零感知）。修不齐**不拦交付**：
        # 交付评分只能更好，硬闸只会把整跑打成 0（Keep 实跑 3 轮
        # 112→78 收敛不动被闸死，白烧 6 小时生成的教训）。
        _beat(project_dir, f"验收-R{verify_round}-锚点")
        try:
            missing = _anchor_missing(code_dir, requirement)
        except Exception:
            missing = []
        if missing and (blocked := _repair_blocked()):
            # 锚点缺口不是交付闸（放行进旅程，评分只能更好），但 LLM 修复
            # 无钱开工时不假装在修——如实留一条痕，交付照走
            notes.append(
                f"[R{verify_round}][anchor] 缺失 {len(missing)} 个需求锚点，"
                f"LLM 修复未开工（{blocked}）")
        elif missing:
            notes.append(
                f"[R{verify_round}][anchor] 缺失 {len(missing)} 个需求锚点"
                f"（前 5: {missing[:5]}）→ 修复")
            _beat(project_dir, f"验收-R{verify_round}-锚点修复")
            try:
                from app.utils.requirement_anchors import (
                    collect_anchors_from_text,
                )

                all_anchors = sorted({
                    a for lst in collect_anchors_from_text(
                        requirement).values() for a in lst})
            except Exception:
                all_anchors = list(missing)
            gate = Path(tempfile.gettempdir()) / "arcbench_anchor_gate.py"
            gate.write_text(
                _ANCHOR_GATE_TEMPLATE.replace(
                    "__ANCHORS__", repr(all_anchors)),
                encoding="utf-8")
            try:
                ok2, rep2 = auto_repair(
                    project_dir, settings, max_rounds=max_app_rounds,
                    requirement=requirement,
                    test_cmd=[sys.executable, str(gate), str(code_dir)],
                    extra_issue=(
                        "锚点覆盖机械校验失败：以下需求原文中的带引号"
                        "文案未逐字出现在任何页面响应中（评测方按这些"
                        "字符串逐字断言，翻译/改写=全部用例失败）：\n"
                        + "\n".join(f"- {a!r}" for a in missing[:30])
                        + "\n修复要求：在对应页面/UI 与种子数据中**逐字**"
                        "补齐这些文案（保持需求原文语言与大小写）；"
                        "禁止翻译、禁止改写、禁止只改部分页面。\n"
                        "反作弊约束（平台 v6-3 取证）：文案必须出现在"
                        "**渲染可见**的界面元素里——禁止塞进 hidden/"
                        "display:none/屏幕外定位的元素，禁止塞进"
                        "textarea/script，禁止占位页 stuffing；"
                        "锚点校验基于渲染可见文本，隐藏塞串=白修。"
                    )
                    + pre_txt,
                )
            except Exception as exc:
                ok2, rep2 = False, f"锚点修复异常: {exc!r}"[:200]
            try:
                still = _anchor_missing(code_dir, requirement)
            except Exception:
                still = missing
            notes.append(
                f"[R{verify_round}][anchor] "
                f"{'PASS' if not still else 'WARN'}"
                + (f"（仍缺 {len(still)}: {still[:5]}）" if still else ""))
            if still:
                # 非交付闸：缺 PORT 口已尽力，放行进旅程/交付（评分只增不减）
                all_reports.append(
                    f"[R{verify_round}] anchor 未全对齐（仍缺 {len(still)}）"
                    f": {rep2[-160:]}")

        # --- Phase 2: 旅程 ---
        notes.append(f"[R{verify_round}][smoke] PASS")
        _beat(project_dir, f"验收-R{verify_round}-旅程")
        try:
            llm = _llm_from(settings)
            jok, jreport = _journey_gate(
                code_dir, project_dir, requirement, llm, max_app_rounds, notes
            )
        except Exception as exc:
            jok = False
            jreport = f"旅程闸门异常: {exc!r}"[:400]
        notes.append(f"[R{verify_round}][journey] {'PASS' if jok else 'FAIL'}")

        all_passed = False
        if ok and jok:
            all_passed = True
        else:
            # 未全过 → 下一轮（auto_repair/journey 内部已有修复逻辑）
            all_reports.append(
                f"[R{verify_round}] journey FAIL: {jreport[-200:]}")
        if all_passed:
            break
        sig = _failure_sig("" if ok else report, "" if jok else jreport)
        if sig and sig == prev_sig:
            notes.append(
                f"[R{verify_round}] 失败指纹与上一轮相同（修复换不来变化）"
                "→ 停止空转，按现状交付")
            break
        prev_sig = sig

    # --- Phase 3: 自测交付闸（v8 原则三：需求→自生成 Playwright 自测→
    # 修复→交付前最后检测）。弱自检全过≠行为可用（平台双跑取证：
    # 冒烟/旅程绿而交互全超时）。即使生成失败也降级放行（尽力交付）。---
    try:
        from app.utils.selftest_gate import selftest_gate

        sok, sreport = selftest_gate(project_dir, requirement, settings,
                                     requirements_dir=requirements_dir)
        notes.append(f"[selftest] {'PASS' if sok else 'FAIL'}")
        if sok:
            _beat(project_dir, "验收-通过")
            return True, "\n".join(notes + [sreport])
    except Exception as exc:
        notes.append(f"[selftest] 异常降级: {exc!r}"[:200])
    if all_passed:
        _beat(project_dir, "验收-通过")
        return True, "\n".join(notes)
    _beat(project_dir, "验收-尽力交付")
    return False, "\n".join(notes + all_reports[-3:])


def _package_layout_section(code_dir: Path) -> str:
    """确定性包结构审计（r17 取证：组装模块 import auth，实际包
    f1_auth；目录里还躺着 auth/ 空壳包——ModuleNotFoundError 的
    真凶是命名漂移，不是缺模块）。

    零 LLM：扫全部本地 .py 的顶层 import，凡导入名不是实际包但有
    近名实际包（f1_auth~auth 后缀/包含关系）即报告映射；同时报告
    只含 __init__.py 的空壳包。无发现返回空串（宁漏不误）。
    """
    try:
        code_dir = Path(code_dir)
        packages = {
            child.name for child in code_dir.iterdir()
            if child.is_dir() and not child.name.startswith(("_", "."))
            and (child / "__init__.py").exists()
        }
        # 空壳包不算真实实现（r17 病理：import auth 命中的是空壳包，
        # 真实代码在 f1_auth——对齐目标必须是有实现的包）
        real = {
            p for p in packages
            if any(
                c.suffix == ".py" and c.name != "__init__.py"
                for c in (code_dir / p).iterdir()
            )
        }
        if not packages:
            return ""

        local_imports: dict[str, list[str]] = {}
        for py in code_dir.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            try:
                src = py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in re.finditer(
                    r"^\s*(?:from|import)\s+(\w+)", src, re.MULTILINE):
                name = m.group(1)
                if name not in real:
                    local_imports.setdefault(name, []).append(
                        py.relative_to(code_dir).as_posix())

        lines: list[str] = []
        for name, files in sorted(local_imports.items()):
            near = [p for p in real
                    if p.endswith("_" + name) or p.startswith(name)
                    or name in p]
            if near:
                lines.append(
                    f"- {files[0]}: import {name} —— 实际包名是 "
                    f"{near[0]}（请把 import 对齐为 {near[0]}）")
        for pkg in sorted(packages):
            pkg_dir = code_dir / pkg
            contents = [c.name for c in pkg_dir.iterdir()
                        if c.name not in ("__pycache__",)]
            if contents == ["__init__.py"] or not contents:
                lines.append(f"- {pkg}/ 是空壳包（仅 __init__.py），"
                             "真实实现不在这里——不要为它补代码，"
                             "把调用方指向真实模块")

        # 符号级（keep3 终局取证）：from X import sym 而 X 未定义 sym
        # （模块导出 bp、组装要 auth_bp 这类命名漂移）→ ImportError
        pkg_src_cache: dict[str, str] = {}
        for py in code_dir.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            try:
                src = py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = py.relative_to(code_dir).as_posix()
            for m in re.finditer(
                    r"^\s*from\s+(\w+)\s+import\s+([^\n#]+)", src, re.MULTILINE):
                pkg, syms = m.group(1), m.group(2)
                if pkg not in real:
                    continue
                if pkg not in pkg_src_cache:
                    pkg_src_cache[pkg] = "\n".join(
                        f.read_text(encoding="utf-8", errors="replace")
                        for f in (code_dir / pkg).rglob("*.py")
                        if "__pycache__" not in f.parts
                    )
                pkg_src = pkg_src_cache[pkg]
                for raw in syms.split(","):
                    sym = raw.strip().split(" as ")[0].strip().strip("()")
                    if not sym or sym == "*" or not re.match(r"^\w+$", sym):
                        continue
                    defined = re.search(
                        rf"^\s*(?:def|class)\s+{sym}\b|^\s*{sym}\s*=|"
                        rf"\bas\s+{sym}\b|import\s+.*\b{sym}\b|"
                        rf"from\s+\S+\s+import\s+[^\n]*\b{sym}\b",
                        pkg_src, re.MULTILINE)
                    if not defined:
                        lines.append(
                            f"- {rel}: from {pkg} import {sym} —— 包 {pkg} "
                            f"未定义 {sym}（检查模块内 Blueprint/函数的实际命名，"
                            "对齐 import 或补导出）")
        if not lines:
            return ""
        return ("【确定性包结构审计（正则扫描，优先按此对齐命名）】\n"
                + "\n".join(lines[:10]) + "\n\n")
    except Exception:
        return ""


def _home_route_priority_note(report: str) -> str:
    """冒烟报告里出现「GET / -> 非 200」时，把首页接回修复队列的第一位。

    run 088dd22be41b 实证：产物起服、`/api/health` 绿，但官方评测的
    `GET / → 404` 刷到结束——UI 用例从第一条起全红，而修环当时正被预算
    掐死，钱花在别的问题上。首页是所有旅程的入口，它的修复价值严格高于其他
    任何单条冒烟失败，所以这条必须排在最前，而不是混在报告尾部等模型自己看见。
    """
    if "GET / ->" not in (report or ""):
        return ""
    return (
        "【本轮唯一优先目标】首页路由 GET / 返回非 200：评测从首页进入再点控件"
        "走旅程，首页没有路由＝所有页面类用例一起判红，优先级高于其他任何冒烟"
        "失败。请把真实首页接上（渲染需求描述的功能 UI 与入口控件），并让需求"
        "点名的每个页面都有一条真路由、且从首页有可点入口可达；禁止用占位页或"
        "隐藏文本塞串充数。\n\n"
    )


def auto_repair(
    project_dir: Path, settings, max_rounds: int = 3,
    test_cmd: list[str] | None = None,
    extra_issue: str = "",
    verify_timeout: int | None = None,
    requirement: str = "",
    priority_note: str = "",
) -> tuple[bool, str]:
    """冒烟失败后的定向自动修复（RepoFixer 通道）。

    test_cmd 缺省 = 基础冒烟；旅程验收传入旅程脚本命令复用同一循环。
    extra_issue 非空时为锚点修复等非冒烟场景服务——冒烟通过也不早退，
    以 extra_issue 为主体构造修复指令。
    """
    from app.agents.repo_fixer import RepoFixer
    from app.utils.budget import BudgetExceededError, TaskCancelledError
    from app.utils.model_client import ModelClient

    project_dir = Path(project_dir).resolve()
    code_dir = project_dir / "code"
    mc = ModelClient(settings)

    def llm(system: str, user: str) -> str:
        # keep7 取证:此处曾有外层包装函数遮蔽同名内层且漏 return,
        # RepoFixer 拿到 None→空文本→rounds=0,修复通道整体静默失效。
        # 现扁平化:唯一 llm 即备胎链本体。
        models = tuple(settings.models[:3]) or ("openai/gpt-4o",)
        # 修复从开发模型起步(省主帅额度);主帅压轴
        chain = (models[1:] + models[:1]) if len(models) > 1 else models
        # 平台首单取证:验收修复阶段无备胎,pro 超时×3 崩穿 main
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        last_exc: Exception | None = None
        for m in chain:
            # 逐腿打点：墙钟 600s×3 腿最长 30 分钟无阶段切换，
            # 不打点会被排障者误判挂死（2026-09-19 本地首跑实测）
            _beat(project_dir, f"验收-修复LLM-{m}")
            try:
                content = mc.chat(m, messages).content or ""
            except (BudgetExceededError, TaskCancelledError):
                raise  # 总闸不换腿（见 _llm_from 同款守卫）
            except RuntimeError as exc:
                last_exc = exc
                continue
            if not content.strip():
                # gen-4 取证:空响应当失败,接力下一模型
                last_exc = RuntimeError(f"{m} 返回空内容")
                continue
            return content
        raise RuntimeError(f"验收 LLM 全链失败（{chain}）: {last_exc}")

    if extra_issue:
        # 非冒烟修复场景（锚点覆盖等）：冒烟通过也要修，指令即主体
        issue = (
            extra_issue
            + "\n\n" + _package_layout_section(code_dir)
            + "修复约束：页面必须是**需求描述的真实功能 UI**（含导航、"
            "表单、列表等真实交互元素），禁止用占位页或隐藏文本塞串充数"
            "（平台 v6-3 取证：占位壳页 + hidden textarea 塞串导致评测"
            "全盘落空）；禁止修改 tests/ 目录；禁止重构无关代码；保持既有"
            "路由与功能不回退。"
        )
    else:
        ok, report = run_smoke(code_dir)
        if ok:
            return True, report

        issue = (
            priority_note
            + "集成冒烟失败（评测方以「import 全部模块 + create_app() + "
            "GET /api/health 返回 200」验收），失败报告如下：\n"
            + report[-1500:]
            + "\n"
            + _package_layout_section(code_dir)
            + _interface_drift_section(code_dir, project_dir)
            + _seed_audit_section(code_dir, requirement)
            + _language_audit_section(code_dir, requirement)
            + "请最小化修复使冒烟通过：可新增缺失函数、注册缺失路由、"
            "补齐缺失页面——但页面必须是**需求描述的真实功能 UI**"
            "（含导航、表单、列表等真实交互元素），禁止用只含标题或"
            "「System is running」字样的占位页充数（平台 v6-3 取证：占位壳"
            "页 + 隐藏文本塞串导致评测全盘落空）。"
            "保证所有模块可导入、create_app 可用、健康检查 200。\n"
            "硬性约束（r8 取证）：**禁止删除或绕过 create_app 中已有的业务"
            "路由注册逻辑**（需求点名的业务端点——列表、详情、创建、"
            "更新、删除、查询——一个都不能少）——import 缺失用补建别名/垫片模块解决，"
            "而不是删减组装逻辑；修残应用的验收会被下游旅程门禁拒绝。"
            "禁止修改 tests/ 目录；禁止重构无关代码。"
        )
    if test_cmd is None:
        # 复测与判定同闸：基线冒烟 × 表单对账。判词里带着 [form] 红字而复测
        # 只看基线，循环就会朝「让基线绿」收敛（锚点闸同形取证：三轮分文未收敛）。
        test_cmd = [sys.executable, str(write_gate_scripts()), str(code_dir)]
    fixer = RepoFixer(
        llm, project_dir,
        test_cmd=test_cmd,
        max_rounds=max_rounds,
        **({"test_timeout": verify_timeout} if verify_timeout else {}),
    )
    result = fixer.fix(issue)
    ok, report = run_smoke(code_dir)
    tail = report[-300:]
    if result.ok and ok:
        return True, f"自动修复成功（{result.rounds} 轮）：{tail}"
    return False, f"自动修复未通过（{result.rounds} 轮）：{tail}"
