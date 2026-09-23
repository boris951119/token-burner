# -*- coding: utf-8 -*-
"""自测交付闸（v8 原则三）：需求 → Playwright 自测 → 修复环 → 交付。

取证链（2026-09-20）：平台跑的修复信号只有弱自检（冒烟/锚点/旅程），
行为缺陷不可见 → 平台双题仅个位数分；本地有官方真题信号后修复环显著提分。
平台拿不到官方题，解法=从需求 GIVEN/WHEN/THEN 自生成同形态测试，
交付前自测+定向修复——通用能力，任何题适用。

防自证正确：测试只从需求文本生成（不给实现代码）；生成一次后持久化
（tests/selftest/），修复轮只重跑不重写。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

GRADE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "official_grade"

# None=未探测；""=可用；其余=不可用原因（进程内缓存，探测只花一次）
_node_probe: str | None = None


def node_unavailable_reason() -> str:
    """node 侧依赖前置探测。

    取证（2026-09-23 Linux 全真演练）：交付容器无 npx 时，本闸先生成
    specs（真金白银的 LLM 调用）再在 lint 处抛 FileNotFoundError，
    被上层 except 降级——钱花了、specs 全废、行为验收静默缺席。
    探测必须前置到生成之前，缺 node 就一分钱不花地跳过。
    """
    global _node_probe
    if _node_probe is not None:
        return _node_probe
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        _node_probe = "环境无 npx（node 未安装）"
        return _node_probe
    try:
        r = subprocess.run([npx, "playwright", "--version"],
                           cwd=str(GRADE_DIR), capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=120)
        if r.returncode == 0:
            _node_probe = ""
        else:
            err = ((r.stderr or "") or (r.stdout or "")).strip()
            _node_probe = f"playwright CLI 不可用: {err[:120]}"
    except Exception as exc:
        _node_probe = f"playwright 探测失败 {exc!r}"[:160]
    return _node_probe

# 自测轮的动作等待上限（毫秒）。9/23 计时取证：一轮 32 用例跑 16 分钟，
# 13 条 timedOut 各自把 60s test 预算整条耗光，全部挂在 locator.fill
# 等不到元素上——等 15s 拿到的报错与等 60s 一字不差，每轮净省 ~9 分钟。
# 修复环能跑几轮是被墙钟预算卡死的，省下的钟点就是多出的修复轮。
# 15s 的选值与官方口径核对过：官方提交侧配置是 test 60s / expect 10s，
# 断言等元素只给 10 秒，动作等待卡在 15s 只比那条线松 5 秒——判红方向
# 与官方一致，不是我们自己另立更严的规矩。
SPEC_ACTION_TIMEOUT_MS = 15000

# 起服就绪预算（秒），照抄官方 runner 的健康轮询常量。
HEALTH_DEADLINE_S = 60


def _spec_env(project_dir: Path, port: int, specs_dir) -> dict[str, str]:
    """自测 playwright 子进程的环境（config 按这些变量取值）。

    单独成函数是因为动作超时是本轮墙钟的主旋钮，而它长在起服流程深处
    ——不外提就只能靠真跑取证。"""
    return dict(os.environ,
                TARGET_URL=f"http://127.0.0.1:{port}",
                GRADE_REPORT=str(Path(project_dir) / "selftest-report.json"),
                PLAYWRIGHT_TEST_DIR=str(specs_dir),
                PLAYWRIGHT_ACTION_TIMEOUT=str(SPEC_ACTION_TIMEOUT_MS),
                PLAYWRIGHT_OUTPUT_DIR=str(Path(project_dir) / "selftest-results"))

_GEN_SYSTEM = (
    "你是资深测试工程师。根据需求文档编写 Playwright 验收测试。"
    "规则：\n"
    "1. 只输出一个 JSON 对象（不要围栏）："
    '{"tests": [{"req_id": "REQ-2.1", "name": "Note Listing", '
    '"code": "完整 spec 文件内容"}]}\n'
    "2. 每个 code 是完整的 .spec.ts 文件：顶部 "
    "import { test, expect } from '@playwright/test';\n"
    "3. 用相对路径导航（test 的 baseURL 由运行环境注入），"
    "如 page.goto('/');\n"
    "4. 定位只允许可访问性通道（官方评测 helpers 实测只走这条路，"
    "CSS 选择器与 data-testid 零使用）：交互控件按需求语义选角色并"
    "严格断言——按钮 getByRole('button',{name})、链接 'link'、菜单 "
    "'menuitem'、切换 'tab'、勾选 'checkbox'/'radio'、下拉 'combobox'+"
    "'option'、弹窗 'dialog'、表格 'row'/'cell'/'columnheader'、"
    "标题 'heading'；需求点名的区域（侧栏/导航/列表/卡片）要断对应"
    "地标角色（'complementary'/'navigation'/'article'），需求没点名的"
    "不要凭空造；禁止 page.locator('css')/#id/.class/[data-testid]；"
    "getByText 只用于非交互的结果文本，不得用它点按钮；\n"
    "4b. 填输入框按官方 fillField 的四级通道原样写：getByLabel(需求"
    "原文标签) → getByPlaceholder(同标签) → getByRole('textbox') → "
    "getByRole('searchbox')，用 .or() 串成一个定位器（任一命中即可，"
    "不要比官方更严——只有 placeholder 没有 label 的输入框官方照样能"
    "填上，逼它补 label 只是白烧一轮修复）；也禁止反过松：不许用 "
    "getByText 定位输入框，官方没有这条兜底；\n"
    "4c. 操作反馈按官方兜底口径断言：getByRole('alert') 或 "
    "getByRole('status') 或结果文本 getByText（.or() 串起来，"
    "任一命中即通过）——不要比官方更严；\n"
    "4d. 可见文本逐字断言（保持需求原文语言与大小写）；\n"
    "5. 需求中的 Seed data 是评测夹具：断言这些数据在页面上可见；\n"
    "6. 交互流（创建/删除/编辑）必须真实执行并断言结果（列表变化/"
    "通知文案），不许只断言元素存在；\n"
    "7. 每个 test 一个场景，test.describe 分组；禁止 sleep/等待魔法数"
    "（用 expect 的自动等待）；禁止访问外部网络。\n"
    "8. 只为 user 消息中列出的需求节点生成测试（其余节点由其他批次"
    "覆盖），每个节点至少一组场景；每条场景独立可跑。"
)

_NODE_HEADER_RE = re.compile(r"^###\s+(\S+)")
_NODE_BATCH_MAX = 8
_NODE_BATCH_CHARS = 15000


def _split_atomic_nodes(requirement: str) -> tuple[list[tuple[str, str]], str]:
    """管线需求文本 → ([(req_id, 节点原文含模块上下文)], 全局契约段)。

    节点级重试的地基：按 ingest 渲染的「### <REQ id> …（验收标准）」切
    节点，每批自带「## 模块」上下文；夹具契约等非模块章节作为全局段随
    每批发给 LLM。无 ### 结构返回空表（调用方回落整段单批）。"""
    nodes: list[tuple[str, str]] = []
    global_parts: list[str] = []
    folder_ctx: list[str] = []
    cur_id: str | None = None
    cur_lines: list[str] = []
    mode = "pre"

    def flush() -> None:
        nonlocal cur_id, cur_lines
        if cur_id is not None:
            nodes.append((cur_id, "\n".join(cur_lines).strip()))
        cur_id, cur_lines = None, []

    for ln in requirement.splitlines():
        if ln.startswith("## "):
            flush()
            if ln[3:].strip().startswith("模块"):
                mode = "folder"
                folder_ctx = [ln]
            else:
                mode = "other"
                folder_ctx = []
                global_parts.append(ln)
        elif ln.startswith("### ") and mode in ("folder", "node", "other"):
            flush()
            m = _NODE_HEADER_RE.match(ln)
            cur_id = m.group(1) if m else "?"
            cur_lines = folder_ctx + [ln]
            mode = "node"
        elif cur_id is not None:
            cur_lines.append(ln)
        elif mode == "folder":
            folder_ctx.append(ln)
        elif mode == "other":
            global_parts.append(ln)
    flush()
    return nodes, "\n".join(global_parts).strip()


def _batch_nodes(nodes: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """节点 → 有序小批（保模块邻接；单节点超窗自成一批不截断）。"""
    batches: list[list[tuple[str, str]]] = []
    cur: list[tuple[str, str]] = []
    size = 0
    for nid, text in nodes:
        if cur and (len(cur) >= _NODE_BATCH_MAX
                    or size + len(text) > _NODE_BATCH_CHARS):
            batches.append(cur)
            cur, size = [], 0
        cur.append((nid, text))
        size += len(text)
    if cur:
        batches.append(cur)
    return batches


def _parse_gen_payload(raw: str) -> list[tuple[str, str, str]]:
    """LLM 响应 → [(req_id, name, code)]（生成内容卫生闸保留原语义）。"""
    body = raw.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        body = "\n".join(lines[1:-1]) if len(lines) > 2 else body
    data = json.loads(body)
    tests = data.get("tests") or []
    specs = [(str(t.get("req_id") or "REQ"),
              str(t.get("name") or "scenario"),
              str(t.get("code") or "")) for t in tests]
    specs = [(a, b, c) for a, b, c in specs if "@playwright/test" in c]
    cleaned: list[tuple[str, str, str]] = []
    for a, b, c in specs:
        text = c.strip()
        # 生成内容卫生（2026-09-20 取证：LLM 曾输出带行号前缀的
        # "1 | import ..."——一个坏 spec 让 Playwright 整体收集
        # 失败，0/0 被误判通过）
        if not text.startswith("import"):
            continue
        if re.search(r"^\s*\d+\s*\|", text, re.MULTILINE):
            continue
        cleaned.append((a, b, text))
    if not cleaned:
        raise ValueError("生成结果无有效 spec")
    return cleaned


def _write_specs(specs_dir: Path, cleaned: list[tuple[str, str, str]],
                 batch_no: int) -> int:
    n = 0
    for k, (rid, name, code) in enumerate(cleaned):
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_"
                       for ch in f"{rid}_{name}")[:60]
        (specs_dir / f"{safe or f'test_b{batch_no}_{k}'}.spec.ts").write_text(
            code, encoding="utf-8")
        n += 1
    return n


def _covered_ids(specs_dir: Path) -> set[str]:
    """已落盘 specs 覆盖的 req_id 集（文件名前缀 = sanitize 后的 req_id）。"""
    if not specs_dir.is_dir():
        return set()
    return {f.stem.split("_", 1)[0] for f in specs_dir.glob("*.spec.ts")}


def ensure_selftests(project_dir: Path, requirement: str,
                     settings) -> Path | None:
    """自测 specs 生成——节点级批量版（9/22 keep-r0 取证：整应用单次
    LLM 调用全有或全无，配额瞬断一次即报废整闸）。

    按 ATOMIC 节点切批逐批生成：单批失败只作废该批，收尾对失败批重试
    一轮；specs 按 req_id 前缀持久化，重入只补缺失节点（断点续生成）。
    部分覆盖 > 零覆盖。已存在 specs 不重写（修复轮只重跑纪律不变）。"""
    project_dir = Path(project_dir)
    specs_dir = project_dir / "tests" / "selftest"
    from app.utils.budget import BudgetExceededError, TaskCancelledError
    from app.utils.model_client import ModelClient
    from app.utils.requirement_anchors import collect_anchors_from_text

    nodes, global_ctx = _split_atomic_nodes(requirement)
    covered = _covered_ids(specs_dir)
    if nodes:
        pending = [(nid, text) for nid, text in nodes if nid not in covered]
        if not pending:
            return specs_dir
    else:
        # 无节点结构（非 ingest 渲染的题面文本）：回落整段单批
        if covered:
            return specs_dir
        pending = [("__all__", requirement[:90000])]

    mc = ModelClient(settings)
    models = tuple(settings.models[:2]) or ("openai/gpt-4o",)

    def gen_batch(batch_no: int, batch: list[tuple[str, str]]) -> bool:
        if batch[0][0] == "__all__":
            body, anchor_src = batch[0][1], batch[0][1]
        else:
            body = "\n\n".join(text for _, text in batch)
            anchor_src = body + "\n" + global_ctx
        # 精确文案注入（2026-09-20 取证：需求截断到 14k 导致生成器
        # "凭想象"写定位器——期望 'Search notes' 而需求原文是 'Search'）
        try:
            buckets = collect_anchors_from_text(anchor_src)
            anchors = sorted({a for lst in buckets.values() for a in lst})
        except Exception:
            anchors = []
        anchor_lines = "\n".join(f"- {a!r}" for a in anchors[:60])
        prompt = (
            "下面列出本批需求节点。请按系统规则为这些节点生成 "
            "Playwright 验收测试。\n\n"
            "## 本批需求逐字文案（定位器必须使用这些精确字符串，"
            "禁止改写、禁止凭印象造词如 'Search notes'）\n"
            + anchor_lines
            + ("\n\n## 全局夹具契约（种子精确字符串以此为准）\n"
               + global_ctx[:6000] if global_ctx else "")
            + "\n\n## 本批需求节点原文\n" + body
        )
        last: Exception | None = None
        for model in models:
            try:
                raw = mc.chat(model, [
                    {"role": "system", "content": _GEN_SYSTEM},
                    {"role": "user", "content": prompt},
                ]).content or ""
                cleaned = _parse_gen_payload(raw)
                specs_dir.mkdir(parents=True, exist_ok=True)
                _write_specs(specs_dir, cleaned, batch_no)
                return True
            except (BudgetExceededError, TaskCancelledError):
                raise  # 总闸不是「这条腿废了」：换腿续跑＝把中止改成多烧几腿
            except Exception as exc:  # 逐模型接力
                last = exc
        ids = " ".join(nid for nid, _ in batch)
        print(f"[selftest] 批{batch_no}（{ids}）生成失败: {last!r}"[:240])
        return False

    batches = _batch_nodes(pending)
    failed = [(i, b) for i, b in enumerate(batches)
              if not gen_batch(i, b)]
    for i, b in failed:  # 节点级重试：收尾补跑一轮失败批
        gen_batch(i, b)
    still = [nid for nid, _ in pending if nid not in _covered_ids(specs_dir)
             and nid != "__all__"]
    if nodes:
        print(f"[selftest] 节点覆盖 {len(nodes) - len(still)}/{len(nodes)}"
              + (f"，仍缺: {' '.join(still[:12])}" if still else ""))
    if not _covered_ids(specs_dir):
        print("[selftest] 生成失败（所有批无一落盘）")
        return None
    lint_specs(specs_dir, project_dir)
    return specs_dir


def _ensure_node_modules_link(specs_dir: Path) -> None:
    """specs 目录可能不在 GRADE_DIR 之下（如项目 tests/selftest/），
    '@playwright/test' 的模块解析会失败——建 junction 指向 GRADE_DIR
    的 node_modules（Windows 目录联接免管理员权限）。"""
    link = specs_dir / "node_modules"
    target = GRADE_DIR / "node_modules"
    if not target.is_dir() or link.exists():
        return
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    else:
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError:
            pass


def lint_specs(specs_dir: Path, project_dir: Path | None = None) -> int:
    """lint 门：逐文件 --list，解析失败的 spec 移入 _rejected/（保留
    诊断现场）。教训（2026-09-20 首版误伤）：整目录 --list 的正常输出
    会列出全部文件路径，按文件名正则剔除=把好文件全倒掉。"""
    npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
    if not shutil.which("npx") and not shutil.which("npx.cmd"):
        # 无 node 时 lint 无从判起：宁可全留（跑不了自然由闸头探测拦下），
        # 也不能把好 spec 当坏 spec 删掉
        print(f"[selftest] lint SKIP: {node_unavailable_reason()}，specs 全保留",
              flush=True)
        return len(list(specs_dir.glob("*.spec.ts")))
    env = dict(os.environ, PLAYWRIGHT_TEST_DIR=str(specs_dir))
    _ensure_node_modules_link(specs_dir)
    rejected = specs_dir.parent / "selftest_rejected"
    survivors = 0
    for f in sorted(specs_dir.glob("*.spec.ts")):
        try:
            pt = subprocess.run(
                [npx, "playwright", "test", f.name, "--list"],
                cwd=str(GRADE_DIR), env=env,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=180)
        except (subprocess.TimeoutExpired, OSError):
            # 判不动就保留：lint 的目的是隔离坏 spec，一次 npx 卡死不构成
            # 「该 spec 是坏的」的证据——上抛还会把整道自测闸一起作废。
            survivors += 1
            continue
        ok = pt.returncode == 0 and "No tests found" not in (pt.stdout or "")
        if ok:
            survivors += 1
            continue
        if project_dir is not None:
            rejected.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(rejected / f.name))
        else:
            f.unlink()
        first_err = ((pt.stderr or "") or (pt.stdout or "")).strip().splitlines()
        print(f"[selftest] lint 剔除 {f.name}: "
              + (first_err[0][:120] if first_err else "unknown"))
    return survivors


def _free_port(prefer: int) -> int:
    import socket

    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", prefer))
        return prefer
    except OSError:
        sock.close()
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port


def _wait_health(url: str, deadline_s: float = HEALTH_DEADLINE_S,
                 proc=None) -> bool:
    """起服就绪探针——预算与放弃条件都照官方 runner 的口径。

    9/23 对表官方启动脚本：健康等待是硬编码 60 次×1s，且服务进程一退出
    就立刻 break。我们此前等 90s 且不看进程死活，两头都错在危险的方向上：
    起服即死的应用白等满 90 秒（修复轮就是这么烧掉的），61-90s 才就绪的
    慢启动应用在本地判绿、到平台判 runtime_unhealthy 全场零分。"""
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        if proc is not None and proc.poll() is not None:
            return False
        time.sleep(1)
    return False


def run_selftests(project_dir: Path, specs_dir: Path,
                  port_hint: int = 3411,
                  requirements_dir: Path | None = None
                  ) -> tuple[int, int, list[str], str]:
    """导出布局 → 起服 → 编译清单 HTTP 判分（可选）→ 跑自测 specs
    → (passed, failed, failures, tail)。"""
    from app.platform_export import export_platform_layout

    project_dir = Path(project_dir).resolve()
    # 时间戳模板目录（2026-09-20 取证：Windows 下上一轮服务子进程句柄
    # 未释放会让固定目录 rmtree 崩溃；新目录天然避开锁，旧目录尽力清理）
    template = project_dir / f".selftest_template_{int(time.time())}"
    for old in sorted(project_dir.glob(".selftest_template*"))[:-3]:
        try:
            shutil.rmtree(old, ignore_errors=True)
        except Exception:
            pass
    if template.exists():
        shutil.rmtree(template)
    template.mkdir(parents=True)
    export_platform_layout(template, project_dir)
    backend = template / "backend"
    if not (backend / "main.py").is_file():
        # 计数必须与 failures 一致：旧实现返回 0/0 却带一条失败，
        # 闸口按"零信号"报废——起服即死（平台 0 分头号死因）的诊断
        # 信息被丢弃，且修复环拿不到这条最该修的失败。
        return 0, 1, ["导出缺 backend/main.py"], ""
    port = _free_port(port_hint)
    # 起服日志必须落盘：健康探针超时时，后端 traceback 是修复环唯一
    # 看得见的死因（旧实现 stdout/stderr 全进 DEVNULL——只剩一句
    # "健康探针超时"，修复 LLM 无从下手）
    boot_log = template / "backend-boot.log"
    boot_fp = open(boot_log, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [sys.executable, str(backend / "main.py")],
        cwd=str(backend), env=dict(os.environ, PORT=str(port)),
        stdout=boot_fp, stderr=subprocess.STDOUT)
    try:
        if not _wait_health(f"http://127.0.0.1:{port}/api/health",
                            proc=proc):
            boot_fp.flush()
            why = ""
            try:
                why = boot_log.read_text(
                    encoding="utf-8", errors="replace").strip()[-1200:]
            except Exception:
                pass
            rc = proc.poll()
            dead = (f"（服务进程已退出 rc={rc}，官方 runner 同口径会在第一时间"
                    f"判 runtime_unhealthy）" if rc is not None else
                    f"（{HEALTH_DEADLINE_S}s 内未就绪，官方预算同样为 "
                    f"{HEALTH_DEADLINE_S}s）")
            return 0, 1, [f"健康探针超时{dead}，后端输出尾部：\n{why}"], why
        # 编译清单判分（零 LLM、秒级）：需求逐字事实 × 活服。失败串以
        # REQ id 开头，与自测失败同清单进修复环即为定向指令。
        csum: dict = {"passed": 0, "failures": []}
        notes_c = ""
        if requirements_dir:
            try:
                from app.utils.acceptance_judge import judge_requirements
                csum = judge_requirements(
                    requirements_dir, f"http://127.0.0.1:{port}")
            except Exception as exc:
                notes_c = f"[compiled] 判分异常降级 {exc!r}"[:120]
                csum = {"passed": 0, "failures": [], "note": notes_c}
            notes_c = notes_c or str(
                csum.get("skipped") or csum.get("note") or "")
        cfail = list(csum.get("failures") or [])
        cpassed = int(csum.get("passed") or 0)
        # 判分器的降级原因必须见于报告：否则「0/0 零信号」与「JS 壳射程外
        # 跳过」两种截然不同的结论在日志里长得一模一样。
        jnote = f"\n[compiled] {notes_c}" if notes_c else ""
        specs = None
        if specs_dir is not None and Path(specs_dir).is_dir():
            specs = list(Path(specs_dir).glob("*.spec.ts"))
        if specs is None:
            # Playwright 段缺席（环境无 node / specs 生成失败）时，前面的
            # 导出布局→起服→健康探针→编译判分依然全部有效：布局违约与
            # 起服死亡两大死因从来不需要 node。旧实现在此处抛错把整闸
            # （连同这些 node-free 检查）一起报废。
            return (cpassed, len(cfail), list(cfail),
                    "[playwright] SKIP（无可用 specs：环境无 node 或生成失败）"
                    + jnote)
        if not specs:
            # 目录在、spec 全被 lint 剔除 = 零信号，不得被编译判分掩盖
            return (cpassed, 1 + len(cfail),
                    ["自测 specs 零收集（lint 全数剔除）"] + cfail,
                    "[playwright] SKIP（specs 目录空）" + jnote)
        report = project_dir / "selftest-report.json"
        env = _spec_env(project_dir, port, specs_dir)
        _ensure_node_modules_link(specs_dir)
        npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
        try:
            pt = subprocess.run(
                [npx, "playwright", "test"], cwd=str(GRADE_DIR), env=env,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=1800)
        except subprocess.TimeoutExpired:
            # 1800s 熔断也必须给修复环一条信号。上抛的代价是整道自测闸作废
            # （调用方只能记一句"异常"），而超时本身多半就是可修的缺陷：
            # 某个旅程用例挂起（服务无响应 / 选择器一路等到超时）。
            return (cpassed, 1 + len(cfail),
                    ["自测执行超时（1800s 熔断）：存在挂起的旅程用例"] + cfail,
                    "[playwright] TIMEOUT 1800s")
        except OSError as exc:
            return (cpassed, 1 + len(cfail),
                    [f"playwright 启动失败: {exc!r}"] + cfail,
                    f"[playwright] 启动失败 {exc!r}")
        (project_dir / "selftest-run.log").write_text(
            (pt.stdout or "") + "\n===== STDERR =====\n" + (pt.stderr or ""),
            encoding="utf-8")
        if not report.is_file():
            return (cpassed, 1 + len(cfail),
                    ["无自测报告"] + cfail, (pt.stdout or "")[-800:])
        data = json.loads(report.read_text(encoding="utf-8"))
        passed = failed = 0
        failures: list[str] = []

        def walk(suite):
            nonlocal passed, failed
            for s in suite.get("suites", []):
                walk(s)
            for spec in suite.get("specs", []):
                t = (spec.get("tests") or [{}])[0]
                results = (t.get("results") or [{}])
                if all(r.get("status") == "passed" for r in results):
                    passed += 1
                else:
                    failed += 1
                    failures.append(spec.get("title", "?"))
        for s in data.get("suites", []):
            walk(s)
        if passed + failed == 0 and cpassed + len(cfail):
            # specs 零收集单独留信号——编译判分再绿也掩盖不了坏 spec 连坐
            failures = ["自测 specs 零收集（坏 spec 连坐？）"]
            failed = 1
        return (passed + cpassed, failed + len(cfail),
                failures + cfail, (pt.stdout or "")[-1500:] + jnote)
    finally:
        # Windows：terminate 不杀孙进程（Flask reload/子线程句柄），锁死
        # 模板目录——taskkill /T 连树击杀，兜底 terminate/kill
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        try:
            boot_fp.close()   # Windows：句柄不关会锁死下一轮模板目录清理
        except Exception:
            pass


def selftest_gate(project_dir: Path, requirement: str, settings,
                  max_rounds: int = 2,
                  requirements_dir: Path | None = None) -> tuple[bool, str]:
    """自测闸：生成（首次）→ 跑 → 失败定向修复 → 复跑。有界，可止损。"""
    from app.arcbench_smoke import _beat, auto_repair

    # 测试/降级开关：ARCBENCH_SELFTEST=off 时整闸跳过（测试环境无
    # 真实网关，生成会挂死真实网络调用）
    if os.environ.get("ARCBENCH_SELFTEST", "").lower() in {"off", "0", "no"}:
        return False, "自测闸关闭（ARCBENCH_SELFTEST=off）"
    project_dir = Path(project_dir).resolve()
    reason = node_unavailable_reason()
    specs_dir: Path | None = None
    if reason:
        # specs 生成要先烧 LLM token，跑它却需要 node——缺 node 时一分钱
        # 不花，直接走 node-free 判分段（导出布局+起服+编译清单）
        print(f"[selftest] SKIP 生成: {reason}（仍跑 node-free 判分）",
              flush=True)
    else:
        _beat(project_dir, "自测闸-生成")
        specs_dir = ensure_selftests(project_dir, requirement, settings)
        if specs_dir is None:
            # 生成全批失败不再报废整闸：前面的活服起服/健康/编译判分
            # 与 node 无关，是"布局违约=主死因"的唯一机械抓手
            print("[selftest] 生成失败（所有批无一落盘）→ 仅跑 node-free 判分",
                  flush=True)
    passed, failed, failures, tail = run_selftests(
        project_dir, specs_dir, requirements_dir=requirements_dir)
    notes: list[str] = []
    notes.append(f"[selftest] 首轮 {passed}/{passed + failed}")
    if tail:
        # 判分器的降级/跳过原因随身携带：「零信号」与「JS 壳射程外」在
        # 计数上长得一样，结论却相反（前者该修，后者不该修）。
        notes.append(tail[:400])
    if passed + failed == 0:
        # 真空真值漏洞（2026-09-20 取证）：坏 spec 连坐收集失败 → 0/0
        # 曾被判 PASS——零信号=零证据=FAIL
        _beat(project_dir, "自测闸-零信号")
        env_note = f"（{reason}，且无 requirements_dir 可判）" if reason else ""
        return False, "\n".join(
            notes + [f"自测零信号：specs 未收集到任何用例{env_note}"])
    if not failed:
        _beat(project_dir, "自测闸-通过")
        return True, "\n".join(notes)
    # 定向修复：失败清单 + 页面真实快照（error-context 含 Playwright
    # 抓的 DOM 形态——修复 LLM 看得见"实际长什么样"才能对齐定位器）
    snapshots: list[str] = []
    results_dir = project_dir / "selftest-results"
    for ctx in sorted(results_dir.glob("*/error-context.md"))[:3]:
        try:
            text = ctx.read_text(encoding="utf-8", errors="replace")
            i = text.find("# Page snapshot")
            if i > -1:
                snapshots.append(text[i:i + 900])
        except Exception:
            continue
    issue = (
        "自生成验收测试失败（交付闸，失败即用户需求未满足）：\n"
        + "\n".join(f"- {f}" for f in failures[:20])
        + "\n\n测试输出尾部：\n" + tail[-1500:]
        + "\n\n页面真实快照（前 3 个失败用例，Playwright 实测 DOM）：\n"
        + "\n---\n".join(snapshots)
        + "\n\n修复要求：让失败场景按需求语义真实通过——补交互行为/"
        "修正导航与表单/对齐可见文案；需求原文引号内的逐字文案（按钮/"
        "占位符/标签/种子名等）必须精确出现在对应控件上；"
        "禁止修改 tests/selftest/ 与 tests/ 目录；禁止删路由；"
        "最小化修改。"
    )
    for rnd in range(1, max_rounds + 1):
        _beat(project_dir, f"自测闸-修复R{rnd}")
        try:
            ok, _rep = auto_repair(
                project_dir, settings, max_rounds=1,
                requirement=requirement,
                verify_timeout=1800,
                # 修复验证信号=自测运行器本尊（RepoFixer 逐轮真实复测）
                test_cmd=[sys.executable, str(Path(__file__).resolve()),
                          "--run", "--project-dir", str(project_dir),
                          *(["--requirements-dir", str(requirements_dir)]
                            if requirements_dir else [])],
                extra_issue=issue)
        except Exception as exc:
            notes.append(f"[selftest][R{rnd}] 修复异常 {exc!r}"[:160])
            break
        passed, failed, failures, tail = run_selftests(
            project_dir, specs_dir, requirements_dir=requirements_dir)
        notes.append(f"[selftest][R{rnd}] {passed}/{passed + failed}")
        if passed + failed == 0:
            notes.append("[selftest][R{r}] 零信号止损".format(r=rnd))
            break
        if not failed:
            _beat(project_dir, "自测闸-通过")
            return True, "\n".join(notes)
        issue = ("自生成验收测试仍有失败：\n"
                 + "\n".join(f"- {f}" for f in failures[:20])
                 + "\n\n输出尾部：\n" + tail[-1200:])
    _beat(project_dir, "自测闸-尽力交付")
    return False, "\n".join(notes)


def _cli() -> int:
    """CLI：--run 模式供 RepoFixer 作 test_cmd（exit 0=自测全过）。"""
    import argparse

    ROOT = Path(__file__).resolve().parents[2]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--requirements-dir", default=None,
                    help="需求目录（含 requirements.yaml）：启用编译清单判分")
    args = ap.parse_args()
    project_dir = Path(args.project_dir)
    specs_dir = project_dir / "tests" / "selftest"
    if not specs_dir.is_dir():
        print("[selftest] specs 目录缺失")
        return 2
    passed, failed, failures, tail = run_selftests(
        project_dir, specs_dir,
        requirements_dir=(Path(args.requirements_dir)
                          if args.requirements_dir else None))
    print(f"[selftest] {passed}/{passed + failed} passed")
    for f in failures[:20]:
        print(f"  FAIL {f}")
    print(tail[-600:])
    return 0 if not failed and passed else 1


if __name__ == "__main__":
    sys.exit(_cli())
