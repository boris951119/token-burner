# -*- coding: utf-8 -*-
"""自测交付闸（v8 原则三）：需求 → Playwright 自测 → 修复环 → 交付。

取证链（2026-09-20）：平台跑的修复信号只有弱自检（冒烟/锚点/旅程），
行为缺陷不可见 → Keep 9.4 / BookStack 8.8；本地有官方真题信号修到 5/32。
平台拿不到官方题，解法=从需求 GIVEN/WHEN/THEN 自生成同形态测试，
交付前自测+定向修复——通用能力，任何题适用。

防自证正确：测试只从需求文本生成（不给实现代码）；生成一次后持久化
（tests/selftest/），修复轮只重跑不重写。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

GRADE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "official_grade"

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
    "4. 断言必须严格且面向用户可见行为：getByRole/button/link/heading/"
    "placeholder + 可见文本逐字断言（保持需求原文语言与大小写）；\n"
    "5. 需求中的 Seed data 是评测夹具：断言这些数据在页面上可见；\n"
    "6. 交互流（创建/删除/编辑）必须真实执行并断言结果（列表变化/"
    "通知文案），不许只断言元素存在；\n"
    "7. 每个 test 一个场景，test.describe 分组；禁止 sleep/等待魔法数"
    "（用 expect 的自动等待）；禁止访问外部网络。\n"
    "8. 覆盖所有 REQ 的核心场景；每条场景独立可跑。"
)


def ensure_selftests(project_dir: Path, requirement: str,
                     settings) -> Path | None:
    """自测 specs 生成（持久化：已存在则跳过，修复轮不重写）。"""
    project_dir = Path(project_dir)
    specs_dir = project_dir / "tests" / "selftest"
    if specs_dir.is_dir() and any(specs_dir.glob("*.spec.ts")):
        return specs_dir
    from app.utils.model_client import ModelClient

    mc = ModelClient(settings)
    prompt = (
        "需求文档如下（可能截断）。请按系统规则生成覆盖核心场景的 "
        "Playwright 验收测试。\n\n"
        + "## 需求文档\n" + requirement[:14000]
    )
    models = tuple(settings.models[:2]) or ("openai/gpt-4o",)
    last: Exception | None = None
    for model in models:
        try:
            raw = mc.chat(model, [
                {"role": "system", "content": _GEN_SYSTEM},
                {"role": "user", "content": prompt},
            ]).content or ""
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
            if not specs:
                raise ValueError("生成结果无有效 spec")
            specs_dir.mkdir(parents=True, exist_ok=True)
            for k, (rid, name, code) in enumerate(specs):
                safe = "".join(ch if ch.isalnum() or ch in "._-" else "_"
                               for ch in f"{rid}_{name}")[:60]
                (specs_dir / f"{safe or f'test_{k}'}.spec.ts").write_text(
                    code, encoding="utf-8")
            return specs_dir
        except Exception as exc:  # 逐模型接力
            last = exc
    print(f"[selftest] 生成失败: {last!r}")
    return None


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


def _wait_health(url: str, deadline_s: float = 90) -> bool:
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def run_selftests(project_dir: Path, specs_dir: Path,
                  port_hint: int = 3411) -> tuple[int, int, list[str], str]:
    """导出布局 → 起服 → 跑自测 specs → (passed, failed, failures, tail)。"""
    from app.platform_export import export_platform_layout

    project_dir = Path(project_dir)
    template = project_dir / ".selftest_template"
    if template.exists():
        shutil.rmtree(template)
    template.mkdir(parents=True)
    export_platform_layout(template, project_dir)
    backend = template / "backend"
    if not (backend / "main.py").is_file():
        return 0, 0, ["导出缺 backend/main.py"], ""
    port = _free_port(port_hint)
    proc = subprocess.Popen(
        [sys.executable, str(backend / "main.py")],
        cwd=str(backend), env=dict(os.environ, PORT=str(port)),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not _wait_health(f"http://127.0.0.1:{port}/api/health"):
            return 0, 0, ["健康探针超时"], ""
        report = project_dir / "selftest-report.json"
        env = dict(os.environ,
                   TARGET_URL=f"http://127.0.0.1:{port}",
                   GRADE_REPORT=str(report),
                   PLAYWRIGHT_TEST_DIR=str(specs_dir),
                   PLAYWRIGHT_OUTPUT_DIR=str(project_dir / "selftest-results"))
        npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
        pt = subprocess.run(
            [npx, "playwright", "test"], cwd=str(GRADE_DIR), env=env,
            capture_output=True, text=True, timeout=1800)
        (project_dir / "selftest-run.log").write_text(
            (pt.stdout or "") + "\n===== STDERR =====\n" + (pt.stderr or ""),
            encoding="utf-8")
        if not report.is_file():
            return 0, 0, ["无自测报告"], (pt.stdout or "")[-800:]
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
        return passed, failed, failures, (pt.stdout or "")[-1500:]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def selftest_gate(project_dir: Path, requirement: str, settings,
                  max_rounds: int = 2) -> tuple[bool, str]:
    """自测闸：生成（首次）→ 跑 → 失败定向修复 → 复跑。有界，可止损。"""
    from app.arcbench_smoke import _beat, auto_repair

    # 测试/降级开关：ARCBENCH_SELFTEST=off 时整闸跳过（测试环境无
    # 真实网关，生成会挂死真实网络调用）
    if os.environ.get("ARCBENCH_SELFTEST", "").lower() in {"off", "0", "no"}:
        return False, "自测闸关闭（ARCBENCH_SELFTEST=off）"
    project_dir = Path(project_dir)
    _beat(project_dir, "自测闸-生成")
    specs_dir = ensure_selftests(project_dir, requirement, settings)
    if specs_dir is None:
        return False, "自测 specs 生成失败（降级：跳过自测闸）"
    passed, failed, failures, tail = run_selftests(project_dir, specs_dir)
    notes = [f"[selftest] 首轮 {passed}/{passed + failed}"]
    if not failed:
        _beat(project_dir, "自测闸-通过")
        return True, "\n".join(notes)
    # 定向修复：失败清单 + 自测运行器作验证信号
    issue = (
        "自生成验收测试失败（交付闸，失败即用户需求未满足）：\n"
        + "\n".join(f"- {f}" for f in failures[:20])
        + "\n\n测试输出尾部：\n" + tail[-1500:]
        + "\n修复要求：让失败场景按需求语义真实通过——补交互行为/"
        "修正导航与表单/对齐可见文案；禁止修改 tests/selftest/ 与 "
        "tests/ 目录；禁止删路由；最小化修改。"
    )
    for rnd in range(1, max_rounds + 1):
        _beat(project_dir, f"自测闸-修复R{rnd}")
        try:
            ok, _rep = auto_repair(
                project_dir, settings, max_rounds=1,
                # 修复验证信号=自测运行器本尊（RepoFixer 逐轮真实复测）
                test_cmd=[sys.executable, str(Path(__file__).resolve()),
                          "--run", "--project-dir", str(project_dir)],
                extra_issue=issue)
        except Exception as exc:
            notes.append(f"[selftest][R{rnd}] 修复异常 {exc!r}"[:160])
            break
        passed, failed, failures, tail = run_selftests(
            project_dir, specs_dir)
        notes.append(f"[selftest][R{rnd}] {passed}/{passed + failed}")
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
    args = ap.parse_args()
    project_dir = Path(args.project_dir)
    specs_dir = project_dir / "tests" / "selftest"
    if not specs_dir.is_dir():
        print("[selftest] specs 目录缺失")
        return 2
    passed, failed, failures, tail = run_selftests(project_dir, specs_dir)
    print(f"[selftest] {passed}/{passed + failed} passed")
    for f in failures[:20]:
        print(f"  FAIL {f}")
    print(tail[-600:])
    return 0 if not failed and passed else 1


if __name__ == "__main__":
    sys.exit(_cli())
