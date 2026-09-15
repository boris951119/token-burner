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
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
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

app = None
for mod in mods:
    if hasattr(mod, "create_app"):
        app = mod.create_app()
        print(f"create_app <- {mod.__name__}")
        break
if app is None:
    failures.append("没有任何模块提供 create_app")
    print("\\n".join(failures))
    raise SystemExit(1)

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

if not ok:
    failures.append(detail)
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
import sys
from pathlib import Path

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
app = None
for mod in mods:
    if hasattr(mod, "create_app"):
        app = mod.create_app()
        break
if app is None:
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
        pages[p] = r.data.decode("utf-8", "replace")[:4000]
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
                except Exception:
                    pass

app = None
app_module = ""
for mod in mods:
    if hasattr(mod, "create_app"):
        app = mod.create_app()
        app_module = mod.__name__
        break
if app is None:
    raise SystemExit("没有任何模块提供 create_app")

routes = []
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
    "禁止 import json/re 之外的模块；禁止 os/sys/subprocess/socket/requests。"
)

# 旅程步数计数（缩水检测：c.get/c.post/c.put/c.delete 调用数）
_JOURNEY_STEP_RE = re.compile(r"c\.(?:get|post|put|delete|patch)\(")

# 脚本自身缺陷分类（r11 取证）：这些异常 + 脚本帧 = 脚本从未跑到断言，
# 是脚本 bug 而非应用缺陷（AssertionError 排除——那可能是真断言失败）
_SCRIPT_DEFECT_RE = re.compile(
    r"\b(NameError|UnboundLocalError|AttributeError|KeyError|IndexError"
    r"|TypeError|SyntaxError|IndentationError)\b\s*:")


def _anchor_coverage_section(code_dir: Path, requirement: str) -> str:
    """锚点覆盖探针段（gen-6 取证家族通用化）：需求承诺的锚点文案
    在页面响应中的覆盖情况——机械校验，零 LLM。

    通过子进程探针（_ANCHOR_COVERAGE_TEMPLATE）采集全部 GET 页面响应
    样本，再与需求文本机械提取的锚点做覆盖比对。返回 markdown 段
    （无锚点/全覆盖/异常返回空串——宁漏不误）。
    """
    try:
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
        proc = subprocess.run(
            [sys.executable, str(probe), str(code_dir)],
            capture_output=True, text=True, timeout=240, cwd=str(code_dir))
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
            lines.append(f"- 需求锚点 {a!r} 未出现在任何页面响应中——"
                         "请在对应页面原文补齐该文案/区块")
        for a, hits in sorted(cov["where"].items())[:8]:
            lines.append(f"- 需求锚点 {a!r} 已出现在: {', '.join(hits[:2])}")
        return "\n".join(lines) + "\n\n"
    except Exception:
        return ""

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
   提交业务→查记录），**禁止**逐个访问路由表里的所有路径，禁止测试
   内部/管理/基建类端点（如建表、初始化、路由注册类）；
2. 路径、HTTP 方法与查询参数名必须逐字取自上方路由表，**禁止访问
   表中不存在的路径**，禁止发明任何端点或参数；
3. 覆盖 GET /api/health 返回 200 一条即可作为第 1 步；
4. 成功路径的状态码断言用 `resp.status_code in (200, 201)`（合法实现
   可能返回 200 或 201，硬编码单一值会误杀正确应用）；失败分支断言
   `in (400, 401, 403, 409)` 区间；
5. 业务数据现场创建（先注册的账号就用于登录；列表响应里的值取自
   实际响应再断言，不要凭空假设精确值）；
6. 每步 resp = c.post(...)/c.get(...) 后立刻 assert，断言消息含步骤名。

行为探针（除主旅程外必须包含，各 1-2 步即可）：
A. 重复注册拒绝：用已注册成功的同一用户名再注册一次，断言
   `resp.status_code in (400, 401, 403, 409)`——需求几乎总是要求
   重复注册被拒绝，200/201 属于静默成功违约（r15 实证）；
B. 种子字符串断言：需求给出的精确数据（如车次号、站点名、用户名）
   若出现在查询/列表响应中，用这些精确字符串断言存在性——这是
   评测方 e2e 夹具的断言方式；
C. 错误密码登录：断言 `resp.status_code in (400, 401, 403)`，
   不得放行 2xx。
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
        if child.name.startswith(("_", ".")) or child.name == "tests":
            continue
        if child.is_dir() and (child / "__init__.py").exists():
            real[child.name] = child
        elif child.suffix == ".py":
            real[child.stem] = child
    if not real:
        return []

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
            if name in real or name in missing:
                continue
            missing[name] = set()
        for m in re.finditer(
                r"^\s*from\s+(\w+)\s+import\s+([^\n#]+)", src, re.MULTILINE):
            pkg, syms = m.group(1), m.group(2)
            if pkg in real:
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
                if p.endswith("_" + name) or p.startswith(name) or name in p]
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
    verify = Path(tempfile.gettempdir()) / "arcbench_smoke_verify.py"
    verify.write_text(_VERIFY_TEMPLATE, encoding="utf-8")

    proc = subprocess.run(
        [python or sys.executable, str(verify), str(code_dir)],
        capture_output=True, text=True, timeout=180,
        cwd=str(code_dir),
    )
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
    return ok, report.strip()


def _parse_mem_peak(report: str) -> float:
    """从冒烟报告中解析 @@MEM@@ 峰值内存；缺失返回 -1（不判罚）。"""
    m = re.search(r"@@MEM@@(-?\d+(?:\.\d+)?)", report or "")
    return float(m.group(1)) if m else -1.0


def _llm_from(settings):
    """平台侧验收 LLM。模型级备胎链（平台首单取证：验收修复阶段
    pro 超时×3 全灭且无备胎，RuntimeError 崩穿 main → 平台 exit 1）
    ——主模型失败后依 settings.models 逐备胎，全灭上抛由调用方容错。"""
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


def _probe_routes(code_dir: Path) -> tuple[str, list[str]] | None:
    """定位组装模块并倾倒真实路由表；(app_module, routes) / None。"""
    code_dir = Path(code_dir).resolve()
    _clear_pycache(code_dir)
    probe = Path(tempfile.gettempdir()) / "arcbench_probe_routes.py"
    probe.write_text(_PROBE_TEMPLATE, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(probe), str(code_dir)],
            capture_output=True, text=True, timeout=180,
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
            cmd, capture_output=True, text=True, timeout=timeout,
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

    def gen(user_extra: str = "") -> str:
        return _extract_body(llm(
            _JOURNEY_SYSTEM,
            _JOURNEY_USER.format(
                requirement=requirement[:4000],
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
            from app.execution.local_executor import scan_dangerous
            dangers = scan_dangerous(candidate)
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
    except Exception:
        pass
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


def verify_delivery(
    project_dir: Path,
    requirement: str,
    settings,
    max_app_rounds: int = 3,
) -> tuple[bool, str]:
    """交付两段式验收：基础冒烟 + 旅程级验收。返回 (是否通过, 报告)。"""
    project_dir = Path(project_dir).resolve()
    code_dir = project_dir / "code"
    notes: list[str] = []
    _beat(project_dir, "验收-冒烟")

    ok, report = run_smoke(code_dir)
    if not ok:
        notes.append(f"[smoke] FAIL → auto_repair: {report[-200:]}")
        _beat(project_dir, "验收-冒烟修复")
        try:
            ok, report = auto_repair(
                project_dir, settings, max_rounds=max_app_rounds
            )
        except Exception as exc:
            # 平台首单取证：验收修复阶段的 LLM 异常曾崩穿 main →
            # 平台 exit 1 + 无报告。优雅 FAIL：保留现场，绝不崩穿。
            ok = False
            report = f"自动修复通道异常（优雅降级）: {exc!r}"[:400]
    notes.append(f"[smoke] {'PASS' if ok else 'FAIL'}")
    if not ok:
        return False, "\n".join(notes + [report[-300:]])

    _beat(project_dir, "验收-旅程")
    llm = _llm_from(settings)
    try:
        jok, jreport = _journey_gate(
            code_dir, project_dir, requirement, llm, max_app_rounds, notes
        )
    except Exception as exc:
        # 同上：旅程闸门内部异常（含 LLM 全链失败）优雅降级为 FAIL
        jok, jreport = False, f"旅程闸门异常（优雅降级）: {exc!r}"[:400]
    _beat(project_dir, "验收-完成", "PASS" if ok and jok else "FAIL")
    return ok and jok, "\n".join(notes + ([jreport] if jreport else []))


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


def auto_repair(
    project_dir: Path, settings, max_rounds: int = 3,
    test_cmd: list[str] | None = None,
) -> tuple[bool, str]:
    """冒烟失败后的定向自动修复（RepoFixer 通道）。

    test_cmd 缺省 = 基础冒烟；旅程验收传入旅程脚本命令复用同一循环。
    """
    from app.agents.repo_fixer import RepoFixer
    from app.utils.model_client import ModelClient

    project_dir = Path(project_dir).resolve()
    code_dir = project_dir / "code"
    mc = ModelClient(settings)

    def llm(system: str, user: str) -> str:
        models = tuple(settings.models[:3]) or ("openai/gpt-4o",)
        # 原语义:修复从开发模型起步(省主帅额度);备胎链补齐全员
        chain = (models[1:] + models[:1]) if len(models) > 1 else models

        def llm(system: str, user: str) -> str:
            # 平台首单取证:验收修复阶段无备胎,pro 超时×3 崩穿 main
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            last_exc: Exception | None = None
            for m in chain:
                try:
                    content = mc.chat(m, messages).content or ""
                except RuntimeError as exc:
                    last_exc = exc
                    continue
                if not content.strip():
                    # gen-4 取证:空响应当失败,接力下一模型
                    last_exc = RuntimeError(f"{m} 返回空内容")
                    continue
                return content
            raise RuntimeError(f"验收 LLM 全链失败（{chain}）: {last_exc}")

    ok, report = run_smoke(code_dir)
    if ok:
        return True, report

    issue = (
        "集成冒烟失败（评测方以「import 全部模块 + create_app() + "
        "GET /api/health 返回 200」验收），失败报告如下：\n"
        + report[-1500:]
        + "\n"
        + _package_layout_section(code_dir)
        + "请最小化修复使冒烟通过：可新增缺失函数、注册缺失路由、"
        "托管缺失静态页面（index.html 等，放模块目录 static/ 下），"
        "保证所有模块可导入、create_app 可用、健康检查 200。\n"
        "硬性约束（r8 取证）：**禁止删除或绕过 create_app 中已有的业务"
        "路由注册逻辑**（register/login/search/booking 等真实业务端点"
        "一个都不能少）——import 缺失用补建别名/垫片模块解决，"
        "而不是删减组装逻辑；修残应用的验收会被下游旅程门禁拒绝。"
        "禁止修改 tests/ 目录；禁止重构无关代码。"
    )
    if test_cmd is None:
        test_cmd = [
            sys.executable,
            str(Path(tempfile.gettempdir()) / "arcbench_smoke_verify.py"),
            str(code_dir),
        ]
    fixer = RepoFixer(
        llm, project_dir,
        test_cmd=test_cmd,
        max_rounds=max_rounds,
    )
    result = fixer.fix(issue)
    ok, report = run_smoke(code_dir)
    tail = report[-300:]
    if result.ok and ok:
        return True, f"自动修复成功（{result.rounds} 轮）：{tail}"
    return False, f"自动修复未通过（{result.rounds} 轮）：{tail}"
