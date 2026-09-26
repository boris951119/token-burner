# -*- coding: utf-8 -*-
"""提交前硬闸：只服务打包工具链，不进提交包、不给 agent 运行时加复杂度。

A 包级静态（零 token）：正式档 config、import 遮蔽 AST、布局契约
B 启动冒烟（零 token）：假网关解包跑 main，无 Traceback + 墙钟内退出
C 微型端到端（flash，--full）：真跑微题面，检查 run_completed / 导出 / GET /

用法：
  python3 scripts/presubmit_gate.py --zip .tmp/submission-pack/v48.zip
  python3 scripts/presubmit_gate.py --zip … --full   # 上平台前必跑
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_submission import (  # noqa: E402
    assert_official_profile, _denied, ALLOW_ROOT,
)

_COMPETITION_BASE_HINTS = (
    "api.arc-bench.com",
    "arc-bench.com/v1",
)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    zip_path: str
    checks: list[Check] = field(default_factory=list)
    ok: bool = False
    mode: str = "AB"

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name, ok, detail))

    def finalize(self) -> bool:
        self.ok = all(c.ok for c in self.checks)
        return self.ok


# ---- A1: config ---------------------------------------------------------

def check_config_in_zip(zf: zipfile.ZipFile) -> Check:
    try:
        raw = json.loads(zf.read("config.json").decode("utf-8"))
    except Exception as exc:
        return Check("A.config", False, f"读 config.json 失败: {exc!r}")
    tmp = Path(tempfile.mkdtemp(prefix="presubmit-cfg-"))
    try:
        cfg = tmp / "config.json"
        cfg.write_text(json.dumps(raw, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        problems = assert_official_profile(cfg)
        if problems:
            return Check("A.config", False, "; ".join(problems))
        return Check("A.config", True, "正式档（cap=0 / specs / 非试跑编队）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- A2: import-shadow AST ---------------------------------------------

class _SkipNested(ast.NodeVisitor):
    def __init__(self) -> None:
        self.loads: list[tuple[int, str]] = []
        self.imports: list[tuple[int, str]] = []

    def visit_FunctionDef(self, node):  # noqa: N802
        return

    def visit_AsyncFunctionDef(self, node):  # noqa: N802
        return

    def visit_ClassDef(self, node):  # noqa: N802
        return

    def visit_Lambda(self, node):  # noqa: N802
        return

    def visit_ListComp(self, node):  # noqa: N802
        return

    def visit_SetComp(self, node):  # noqa: N802
        return

    def visit_DictComp(self, node):  # noqa: N802
        return

    def visit_GeneratorExp(self, node):  # noqa: N802
        return

    def visit_Import(self, node):  # noqa: N802
        for a in node.names:
            self.imports.append((node.lineno, (a.asname or a.name).split(".")[0]))

    def visit_ImportFrom(self, node):  # noqa: N802
        for a in node.names:
            if a.name != "*":
                self.imports.append((node.lineno, a.asname or a.name))

    def visit_Name(self, node):  # noqa: N802
        if isinstance(node.ctx, ast.Load):
            self.loads.append((node.lineno, node.id))


def find_import_shadows(source: str, *, path: str = "<src>") -> list[str]:
    """函数内后置 import 遮蔽前面引用 → UnboundLocalError（57e3）。"""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"{path}: 语法错误 {exc}"]
    hits: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params: set[str] = set()
        a = fn.args
        for x in list(a.args) + list(a.posonlyargs) + list(a.kwonlyargs) + [
                a.vararg, a.kwarg]:
            if x:
                params.add(x.arg)
        v = _SkipNested()
        for stmt in fn.body:
            v.visit(stmt)
        first: dict[str, int] = {}
        for ln, name in v.imports:
            first.setdefault(name, ln)
        for ln, name in v.loads:
            if name in params or name not in first:
                continue
            if ln < first[name]:
                hits.append(
                    f"{path}:{ln} {fn.name}() 使用 {name} 早于 import@{first[name]}"
                )
    return hits


def check_import_shadows_in_zip(zf: zipfile.ZipFile) -> Check:
    hits: list[str] = []
    for name in zf.namelist():
        if not name.endswith(".py"):
            continue
        if not (name == "main.py" or name.startswith("app/")):
            continue
        try:
            src = zf.read(name).decode("utf-8")
        except Exception:
            continue
        hits.extend(find_import_shadows(src, path=name))
    if hits:
        return Check("A.import_shadow", False, "; ".join(hits[:8]))
    return Check("A.import_shadow", True, "main.py+app/ 无后置 import 遮蔽")


# ---- A3: layout / deny -------------------------------------------------

def check_layout(zf: zipfile.ZipFile) -> Check:
    names = [n for n in zf.namelist() if not n.endswith("/")]
    if "main.py" not in names:
        return Check("A.layout", False, "缺少根目录 main.py")
    try:
        req = zf.read("requirements.txt").decode("utf-8")
    except KeyError:
        return Check("A.layout", False, "缺少 requirements.txt")
    if not req.strip():
        return Check("A.layout", False, "requirements.txt 为空")
    leaks = [n for n in names if _denied(n)]
    if leaks:
        return Check("A.layout", False, f"禁令残留: {leaks[:5]}")
    top = {n.split("/")[0] for n in names}
    bad_top = sorted(t for t in top if t not in ALLOW_ROOT)
    if bad_top:
        return Check("A.layout", False, f"非白名单顶层: {bad_top[:5]}")
    return Check("A.layout", True, f"{len(names)} 文件布局 OK")


def run_segment_a(zip_path: Path, report: Report) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        for fn in (check_config_in_zip, check_import_shadows_in_zip, check_layout):
            report.checks.append(fn(zf))


# ---- B: boot smoke -----------------------------------------------------

_MICRO_REQ = """\
## 模块：REQ-1 Notes
### REQ-1-1 Open（验收标准）
Open notes.
  - 场景：open
    GIVEN: home page
    WHEN: click "New note"
    THEN: the editor shows "Untitled"

### REQ-1-2 Save（验收标准）
Save note.
  - 场景：save
    GIVEN: home page with editor open
    WHEN: click "Save"
    THEN: a snackbar shows "Saved"

### REQ-1-3 List（验收标准）
List notes.
  - 场景：list
    GIVEN: home page
    WHEN: the user opens the note list
    THEN: the list shows "Untitled"
"""


def _write_micro_requirement(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    # 纯文本讨论稿也可；目录形态更接近平台
    yaml = dest / "requirements.yaml"
    # 最小 YAML 树（无 reference 图 → 不走 vision 网关）
    yaml.write_text(
        "name: micro\n"
        "type: FOLDER\n"
        "children:\n"
        "  - id: REQ-1\n"
        "    type: FOLDER\n"
        "    name: Notes\n"
        "    children:\n"
        "      - id: REQ-1.1\n"
        "        type: ATOMIC\n"
        "        name: Open\n"
        "        description: |\n"
        "          ### REQ-1-1 Open（验收标准）\n"
        "          Open notes.\n"
        "            - 场景：open\n"
        "              GIVEN: home page\n"
        '              WHEN: click "New note"\n'
        '              THEN: the editor shows "Untitled"\n'
        "      - id: REQ-1.2\n"
        "        type: ATOMIC\n"
        "        name: Save\n"
        "        description: |\n"
        "          ### REQ-1-2 Save（验收标准）\n"
        "          Save.\n"
        "            - 场景：save\n"
        "              GIVEN: home page\n"
        '              WHEN: click "Save"\n'
        '              THEN: shows "Saved"\n'
        "      - id: REQ-1.3\n"
        "        type: ATOMIC\n"
        "        name: List\n"
        "        description: |\n"
        "          ### REQ-1-3 List（验收标准）\n"
        "          List.\n"
        "            - 场景：list\n"
        "              GIVEN: home page\n"
        "              WHEN: open list\n"
        '              THEN: shows "Untitled"\n',
        encoding="utf-8",
    )
    return dest


def _unpack(zip_path: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    return dest


def run_segment_b(zip_path: Path, report: Report, *, timeout_s: int = 300) -> Path:
    """假网关启动：设计内快速失败可以，崩溃 Traceback 不行。"""
    work = Path(tempfile.mkdtemp(prefix="presubmit-b-"))
    try:
        root = _unpack(zip_path, work / "pkg")
        req = _write_micro_requirement(work / "req")
        out = work / "out"
        out.mkdir()
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = "sk-presubmit-fake"
        env["OPENAI_BASE_URL"] = "http://127.0.0.1:9"
        env["MODEL"] = "deepseek-v4-flash"
        env["ARCBENCH_OUTPUT_DIR"] = str(out)
        env["WATCHDOG_MINUTES"] = "5"
        env["DISCUSSION_MINUTES"] = "1"
        # 缩短墙钟，预检失败更快
        proc = subprocess.run(
            [sys.executable, "main.py", str(req), "-o", str(out), "--mode", "auto"],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        stderr = proc.stderr or ""
        stdout = proc.stdout or ""
        combined = stdout + "\n" + stderr
        # 崩溃特征：UnboundLocal / 未捕获栈顶在 main 看门狗等
        bad = bool(re.search(
            r"UnboundLocalError|NameError:.*not (defined|associated)",
            combined))
        # 允许设计内失败路径打印，但「裸崩」= Traceback 且不含预检/救件收口
        has_tb = "Traceback (most recent call last):" in stderr
        designed = any(s in combined for s in (
            "网关预检", "预检失败", "保底骨架", "末级救件", "快速止损",
        ))
        if bad:
            report.add("B.boot", False,
                       f"崩溃特征: {(stderr or stdout)[-400:]}")
        elif has_tb and not designed:
            report.add("B.boot", False,
                       f"意外 Traceback: {stderr[-400:]}")
        else:
            report.add(
                "B.boot", True,
                f"rc={proc.returncode} designed_fail={designed} "
                f"wall<{timeout_s}s")
        # 落现场供排障
        (work / "stdout.txt").write_text(stdout, encoding="utf-8")
        (work / "stderr.txt").write_text(stderr, encoding="utf-8")
        return work
    except subprocess.TimeoutExpired:
        report.add("B.boot", False, f"超过 {timeout_s}s 未退出（疑似挂死）")
        return work
    except Exception as exc:
        report.add("B.boot", False, f"B 段异常: {exc!r}")
        return work


# ---- C: mini e2e -------------------------------------------------------

def _refuse_competition_burn(env: dict) -> str | None:
    base = (env.get("OPENAI_BASE_URL")
            or env.get("OPENAI_API_BASE")
            or "").lower()
    for h in _COMPETITION_BASE_HINTS:
        if h in base:
            return (f"C 段拒绝使用比赛中转 ({base})——"
                    "请用私有 key / 百炼 dashscope 等试跑网关")
    if not (env.get("OPENAI_API_KEY") or "").strip():
        return "C 段需要环境变量 OPENAI_API_KEY（私有 key）"
    return None


def run_segment_c(zip_path: Path, report: Report, *, timeout_s: int = 1500) -> Path:
    work = Path(tempfile.mkdtemp(prefix="presubmit-c-"))
    root = _unpack(zip_path, work / "pkg")
    req = _write_micro_requirement(work / "req")
    out = work / "out"
    out.mkdir()
    env = os.environ.copy()
    # 强制 flash 编队，省钱
    env["MODEL"] = env.get("PRESUBMIT_MODEL") or "deepseek-v4-flash"
    env["ARCBENCH_OUTPUT_DIR"] = str(out)
    env["WATCHDOG_MINUTES"] = "25"
    env["DISCUSSION_MINUTES"] = "8"
    refuse = _refuse_competition_burn(env)
    if refuse:
        report.add("C.e2e", False, refuse)
        return work
    try:
        proc = subprocess.run(
            [sys.executable, "main.py", str(req), "-o", str(out), "--mode", "auto"],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        report.add("C.e2e", False, f"超过 {timeout_s}s 未退出（挂死）")
        return work
    (work / "stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (work / "stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")

    # run_completed 证据
    events = list(out.rglob("runner-events.jsonl")) + list(out.rglob("*.jsonl"))
    saw_completed = "run_completed" in combined or any(
        "run_completed" in p.read_text(encoding="utf-8", errors="ignore")
        for p in events[:20]
    )
    backend_main = out / "backend" / "main.py"
    export_ok = backend_main.is_file()
    home_ok = False
    home_detail = "未探测"
    if export_ok:
        # 起服探测：短时跑 backend main
        try:
            import urllib.request
            port = "3317"
            penv = env.copy()
            penv["PORT"] = port
            srv = subprocess.Popen(
                [sys.executable, "main.py"],
                cwd=str(out / "backend"),
                env=penv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.time() + 25
                last_err = ""
                while time.time() < deadline:
                    try:
                        with urllib.request.urlopen(
                                f"http://127.0.0.1:{port}/", timeout=2) as r:
                            home_ok = (200 <= r.status < 400)
                            home_detail = f"GET / → {r.status}"
                            break
                    except Exception as exc:
                        last_err = repr(exc)
                        time.sleep(0.5)
                else:
                    home_detail = f"起服超时: {last_err}"
            finally:
                srv.terminate()
                try:
                    srv.wait(timeout=5)
                except Exception:
                    srv.kill()
        except Exception as exc:
            home_detail = f"起服异常: {exc!r}"

    parts = []
    ok = True
    if not saw_completed:
        ok = False
        parts.append("未见 run_completed")
    else:
        parts.append("run_completed")
    if not export_ok:
        ok = False
        parts.append("缺 backend/main.py")
    else:
        parts.append("export OK")
    if not home_ok:
        ok = False
        parts.append(f"home 失败({home_detail})")
    else:
        parts.append(home_detail)
    parts.append(f"rc={proc.returncode}")
    report.add("C.e2e", ok, "; ".join(parts))
    return work


# ---- orchestrate -------------------------------------------------------

def run_gate(zip_path: Path, *, full: bool = False,
             report_dir: Path | None = None) -> Report:
    zip_path = zip_path.resolve()
    report = Report(zip_path=str(zip_path), mode="ABC" if full else "AB")
    if not zip_path.is_file():
        report.add("zip", False, f"不存在: {zip_path}")
        report.finalize()
        return report

    run_segment_a(zip_path, report)
    # A 失败仍跑 B（信息量），但最终 ok 会红
    b_work = run_segment_b(zip_path, report)
    c_work = None
    if full:
        c_work = run_segment_c(zip_path, report)

    report.finalize()
    out_dir = report_dir or (ROOT / ".tmp" / "presubmit" / zip_path.stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # 保留现场指针
    meta = {
        "b_work": str(b_work) if b_work else None,
        "c_work": str(c_work) if c_work else None,
    }
    (out_dir / "workspaces.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="提交前硬闸 A/B[/C]")
    ap.add_argument("--zip", required=True, help="待检提交包")
    ap.add_argument("--full", action="store_true",
                    help="加跑 C 段（上平台前必开；用私有 key）")
    ap.add_argument("--report-dir", default="",
                    help="报告目录（默认 .tmp/presubmit/<stem>）")
    a = ap.parse_args(argv)
    rd = Path(a.report_dir) if a.report_dir else None
    report = run_gate(Path(a.zip), full=a.full, report_dir=rd)
    for c in report.checks:
        mark = "PASS" if c.ok else "FAIL"
        print(f"[{mark}] {c.name}: {c.detail}", flush=True)
    print(f"[presubmit] mode={report.mode} overall="
          f"{'PASS' if report.ok else 'FAIL'}", flush=True)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
