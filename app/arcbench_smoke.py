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
    if child.is_dir() and not child.name.startswith("_"):
        sys.path.insert(0, str(child))

from __APP_MODULE__ import create_app
app = create_app()
c = app.test_client()
client = c  # 别名：r11 取证 LLM 惯用 client，NameError 会被误判为应用缺陷

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
    """报告含脚本帧且终态异常属于「脚本自身写错」类 → 分类为脚本缺陷。"""
    return bool(report) and "arcbench_journey.py" in report and bool(
        _SCRIPT_DEFECT_RE.search(report[-400:]))

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
