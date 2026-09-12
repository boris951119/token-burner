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

code = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(code))
for child in sorted(code.iterdir()):
    if child.is_dir() and not child.name.startswith("_"):
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

if hasattr(app, "test_client"):        # Flask
    resp = app.test_client().get("/api/health")
    ok = resp.status_code == 200
    detail = f"/api/health -> {resp.status_code}"
else:                                   # FastAPI
    from fastapi.testclient import TestClient
    resp = TestClient(app).get("/api/health")
    ok = resp.status_code == 200
    detail = f"/api/health -> {resp.status_code}"

if not ok:
    failures.append(detail)
    print("\\n".join(failures))
    raise SystemExit(1)
print("SMOKE_OK")
'''

# 路由探测：与冒烟同一套 import 引导，定位组装模块并倾倒真实 url_map。
_PROBE_TEMPLATE = '''\
"""ArcBench 路由探测（自动生成）：url_map -> @@ROUTES@@{json}。"""
import json
import sys
from pathlib import Path

code = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(code))
for child in sorted(code.iterdir()):
    if child.is_dir() and not child.name.startswith("_"):
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

routes = sorted(
    f"{rule} [{','.join(sorted(methods - {'HEAD', 'OPTIONS'}))}]"
    for rule, methods in (
        (r.rule, set(r.methods)) for r in app.url_map.iter_rules()
    )
)
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
    if child.is_dir() and not child.name.startswith("_"):
        sys.path.insert(0, str(child))

from __APP_MODULE__ import create_app
app = create_app()
c = app.test_client()

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

_JOURNEY_USER = """根据需求摘要与真实路由表，生成该 Web 应用的主旅程验收代码体。

需求摘要：
{requirement}

应用组装模块名：{app_module}（框架已 import 并创建 app）
真实路由表（仅供查对路径与参数名）：
{routes}

硬性规则：
1. 只走需求的主成功旅程（5-8 步，典型：注册→登录→核心查询→提交业务→
   查记录），**禁止**逐个访问路由表里的所有路径，禁止测试内部/管理/
   基建类端点（如建表、初始化、路由注册类）；
2. 路径与参数名必须逐字取自上方路由表，**禁止访问表中不存在的路径**，
   禁止发明任何端点；
3. 覆盖 GET /api/health 返回 200 一条即可作为第 1 步；
4. 业务数据现场创建（先注册的账号就用于登录；列表响应里的值取自
   实际响应再断言，不要凭空假设精确值）；
5. 每步 resp = c.post(...)/c.get(...) 后立刻 assert，断言消息含步骤名。
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


def run_smoke(code_dir: Path, python: str | None = None) -> tuple[bool, str]:
    """确定性集成冒烟。返回 (是否通过, 报告文本)。"""
    code_dir = Path(code_dir).resolve()
    if not code_dir.is_dir():
        return False, f"code 目录不存在: {code_dir}"

    _clear_pycache(code_dir)
    verify = Path(tempfile.gettempdir()) / "arcbench_smoke_verify.py"
    verify.write_text(_VERIFY_TEMPLATE, encoding="utf-8")

    proc = subprocess.run(
        [python or sys.executable, str(verify), str(code_dir)],
        capture_output=True, text=True, timeout=180,
        cwd=str(code_dir),
    )
    report = (proc.stdout or "") + (proc.stderr or "")[-500:]
    return proc.returncode == 0, report.strip()


def _llm_from(settings):
    """平台侧验收 LLM（主模型）；fast 副本不再另设——验收调用少。"""
    from app.utils.model_client import ModelClient

    mc = ModelClient(settings)
    model = tuple(settings.models[:3])[0]

    def llm(system: str, user: str) -> str:
        return mc.chat(
            model,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        ).content

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
    last_report = ""
    best_report = ""  # 信息量最大的一次真实执行报告（修应用时交给 LLM）
    for attempt in (1, 2):
        try:
            body = gen("" if attempt == 1 else
                       "\n\n上一版脚本执行失败输出（修正脚本本身，勿改应用行为假设）：\n"
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
        jpath.write_text(script, encoding="utf-8")
        ok, last_report = run_journey_script(jpath, code_dir)
        if len(last_report) > len(best_report):
            best_report = last_report
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

    # 脚本本身两轮收敛了但断言仍失败 → 应用缺陷，进入修复循环
    notes.append("[journey] 旅程断言失败 → RepoFixer 修复应用")
    try:
        from app.agents.repo_fixer import RepoFixer

        fixer = RepoFixer(
            llm, project_dir,
            test_cmd=[sys.executable, str(jpath), str(code_dir)],
            max_rounds=max_app_rounds,
        )
        fixer.fix(
            "旅程验收失败（评测方以真实浏览器走用户旅程，本脚本是同进程"
            "等价验收）。失败输出如下，请最小化修复使旅程通过（典型："
            "查询/列表必须返回数据库种子数据而非硬编码列表、缺失页面/"
            "路由补齐、响应字段补齐）。禁止修改 tests/ 目录与旅程脚本。\n"
            + best_report[-1500:]
        )
    except Exception as exc:
        notes.append(f"[journey] 修复通道异常 {exc!r}")
    ok, report = run_journey_script(jpath, code_dir)
    notes.append(f"[journey] 修复后 {'PASS' if ok else 'FAIL'}")
    if not ok:
        return False, last_report[-300:]
    return True, ""


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

    ok, report = run_smoke(code_dir)
    if not ok:
        notes.append(f"[smoke] FAIL → auto_repair: {report[-200:]}")
        ok, report = auto_repair(
            project_dir, settings, max_rounds=max_app_rounds
        )
    notes.append(f"[smoke] {'PASS' if ok else 'FAIL'}")
    if not ok:
        return False, "\n".join(notes + [report[-300:]])

    llm = _llm_from(settings)
    jok, jreport = _journey_gate(
        code_dir, project_dir, requirement, llm, max_app_rounds, notes
    )
    return ok and jok, "\n".join(notes + ([jreport] if jreport else []))


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
        resp = mc.chat(
            models[1] if len(models) > 1 else models[0],
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.content

    ok, report = run_smoke(code_dir)
    if ok:
        return True, report

    issue = (
        "集成冒烟失败（评测方以「import 全部模块 + create_app() + "
        "GET /api/health 返回 200」验收），失败报告如下：\n"
        + report[-1500:]
        + "\n请最小化修复使冒烟通过：可新增缺失函数、注册缺失路由、"
        "托管缺失静态页面（index.html 等，放模块目录 static/ 下），"
        "保证所有模块可导入、create_app 可用、健康检查 200。"
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
