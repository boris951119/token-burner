# -*- coding: utf-8 -*-
"""评分→定向修复→复评 循环驱动（通用，任何任务）。

每轮：官方全量评分 → 失败清单+错误上下文 → auto_repair（验证信号=
official_probe 跑失败子集）→ 复评。到全过/轮次耗尽/无进展为止。

回滚保险（keep7 取证：修复轮把好状态改坏且无路可退）：每轮修复前
快照整个项目目录；下一轮评分若低于修复前，先存 diff 取证再整体还原
——分数逐轮单调不降。（bookstack 取证：git checkout 整体回滚未先
diff，可能丢了有益的未提交改动，故 diff 必须先于还原落盘。）

用法:
    python scripts/grade_repair_loop.py --project-dir <projects/xxx> \
        --task keep --rounds 4
退出码: 0=全过, 1=有剩余失败, 2=参数/环境故障。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GRADE_DIR = ROOT / "scripts" / "official_grade"

# 快照/还原都跳过的缓存与自测产物（体积大且与源码态无关）
_SNAP_IGNORE = ("__pycache__", ".selftest_template", "selftest-results",
                "test-results", "node_modules", ".pytest_cache")


def _snapshot(project_dir: Path) -> Path:
    """修复前快照整个项目目录（排除缓存/自测产物），返回快照路径。"""
    dst = Path(tempfile.mkdtemp(prefix="grl_snap_")) / "snap"
    shutil.copytree(project_dir, dst,
                    ignore=shutil.ignore_patterns(*_SNAP_IGNORE))
    return dst


def _rmtree_hard(path: Path, attempts: int = 5) -> None:
    # Windows 句柄锁（WinError 32）重试退避；持续失败必须炸出来，
    # 静默半还原态比不还原更糟。
    for i in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(1.5 * (i + 1))


def _archive_diff_and_restore(project_dir: Path, snap: Path,
                              label: str) -> Path:
    """先存「快照→现状」diff 到仓库级日志，再整体还原项目目录。

    diff 落在 ROOT/logs/repair_rollback/（项目目录外），还原不会
    覆盖它。git diff --no-index 比较两个目录，退出码 1=有差异。
    """
    out_dir = ROOT / "logs" / "repair_rollback"
    out_dir.mkdir(parents=True, exist_ok=True)
    patch = out_dir / f"{project_dir.name}_{label}_{time.strftime('%H%M%S')}.patch"
    # git diff --no-index 比较两个目录，退出码 1=有差异（此处不算失败）
    r = subprocess.run(
        ["git", "diff", "--no-index", "--src-prefix=修复前/", "--dst-prefix=修复后/",
         str(snap), str(project_dir)],
        capture_output=True, timeout=120,
    )
    patch.write_bytes(r.stdout or b"")
    for child in list(project_dir.iterdir()):
        if child.name in _SNAP_IGNORE:
            continue
        _rmtree_hard(child) if child.is_dir() else child.unlink()
    shutil.copytree(snap, project_dir, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*_SNAP_IGNORE))
    return patch


class GradeEnvError(RuntimeError):
    """评分环境故障（起服失败/无报告）——summary 是陈旧数据不可用。"""


def _run_grade(project_dir: Path, task: str) -> tuple[int, int, list[str]]:
    from scripts.local_grade import main as grade_main  # 复用同进程评分

    sys.argv = ["local_grade.py", "--project-dir", str(project_dir),
                "--task", task]
    rc = grade_main()
    if rc == 2:
        # 9/20 取证：起服失败时读陈旧 summary，把上上轮战绩当本轮
        # 失败清单喂修复器纯烧 token——环境故障必须炸出来重试
        raise GradeEnvError("评分环境故障（rc=2：起服失败/并发锁/无报告）")
    summary = GRADE_DIR / "grade-summary.json"
    data = json.loads(summary.read_text(encoding="utf-8"))
    return data.get("passed", 0), data.get("total", 0), data.get("failures", [])


def _failure_contexts(project_dir: Path, failures: list[str],
                      limit: int = 3) -> list[str]:
    """从 test-results 抓前 N 个失败的页面真实快照。"""
    out: list[str] = []
    results = GRADE_DIR / "test-results"
    if not results.is_dir():
        return out
    import time

    cutoff = time.time() - 6 * 3600
    for ctx in sorted(results.glob("*/error-context.md"),
                      key=lambda p: p.stat().st_mtime, reverse=True):
        if ctx.stat().st_mtime < cutoff or len(out) >= limit:
            continue
        try:
            text = ctx.read_text(encoding="utf-8", errors="replace")
            i = text.find("# Page snapshot")
            if i > -1:
                out.append(text[i:i + 900])
        except Exception:
            continue
    return out


def _req_fragments(failures: list[str], limit: int = 6) -> list[str]:
    """失败题名 → official_probe 的 spec 片段（REQ-N 前缀）。"""
    frags = []
    for f in failures:
        m = re.match(r"(REQ-[\d.]+)", f)
        if m and m.group(1) not in frags:
            frags.append(m.group(1))
        if len(frags) >= limit:
            break
    return frags


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--task", default="keep")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--model", default=None, help="覆盖主刀模型（默认 pro）")
    ap.add_argument("--no-rollback", action="store_true",
                    help="关闭回滚保险（调试用）")
    args = ap.parse_args()

    from app.arcbench_smoke import auto_repair
    from app.config import load_settings

    settings = load_settings(config_file=ROOT / "config.json")
    settings.models = ((args.model,) if args.model
                       else ("openai/deepseek-v4-pro",))

    project_dir = Path(args.project_dir)

    def _grade_with_guard(prev_passed, prev_failures, snap, label):
        """评分（环境故障重试一次）；若低于修复前则回滚（diff 先行存档），
        沿用修复前战绩。"""
        for attempt in (1, 2):
            try:
                passed, total, failures = _run_grade(project_dir, args.task)
                break
            except GradeEnvError as exc:
                if attempt == 2:
                    raise
                print(f"[loop] {exc}，清场 90s 后重试一次", flush=True)
                time.sleep(90)
        # 快照缺失（当轮快照失败且修复未跑）时不触发回滚，防 None 还原
        if (not args.no_rollback and prev_passed is not None
                and snap is not None and passed < prev_passed):
            patch = _archive_diff_and_restore(project_dir, snap, label)
            print(f"[loop] 评分回退 {prev_passed}→{passed}，已回滚本轮修复"
                  f"（diff: {patch.name}）", flush=True)
            passed, failures = prev_passed, prev_failures
        return passed, total, failures

    prev_passed: int | None = None
    prev_failures: list[str] = []
    snap: Path | None = None
    for rnd in range(1, args.rounds + 1):
        print(f"[loop] === 第 {rnd}/{args.rounds} 轮 ===", flush=True)
        passed, total, failures = _grade_with_guard(
            prev_passed, prev_failures, snap, f"round{rnd}")
        print(f"[loop] 官方: {passed}/{total}", flush=True)
        if not failures:
            print("[loop] 全过，收工")
            return 0
        contexts = _failure_contexts(project_dir, failures)
        frags = _req_fragments(failures)
        issue = (
            "官方验收测试失败（评测方用 Playwright 按 ARIA 语义逐字断言，"
            "失败即用户需求未满足）。失败清单：\n"
            + "\n".join(f"- {f}" for f in failures[:25])
            + "\n\n页面真实快照（Playwright 实测 DOM，前 3 个失败）：\n"
            + "\n---\n".join(contexts)
            + "\n\n修复要求：\n"
            "1. 失败场景按需求语义真实通过——补交互行为/对齐逐字文案"
            "（按钮/占位符/通知原文）/修导航；\n"
            "2. 页面快照显示 'Not Found' = 该页面不存在：按需求实现"
            "真实页面（真实数据渲染+真实交互），禁止占位壳——"
            "缺失页面是本任务最大失分源，优先补齐；\n"
            "3. 禁止修改 tests/ 目录与官方 specs；禁止删已有路由；"
            "最小化修改。"
        )
        # 修复可能半途而废：战绩与快照都在修复动作前定格
        prev_passed, prev_failures = passed, failures
        try:
            test_cmd = [sys.executable, str(ROOT / "scripts" / "official_probe.py"),
                        "--project-dir", str(project_dir), "--task", args.task,
                        "--specs", *frags] if frags else None
            if not args.no_rollback:
                snap = _snapshot(project_dir)
            auto_repair(project_dir, settings, max_rounds=1,
                        verify_timeout=1800, test_cmd=test_cmd,
                        extra_issue=issue)
        except Exception as exc:
            print(f"[loop] 修复异常: {exc!r}"[:300], flush=True)
    # 末轮复评（同样过回滚闸）
    passed, total, failures = _grade_with_guard(
        prev_passed, prev_failures, snap, "final")
    print(f"[loop] 最终: {passed}/{total}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
