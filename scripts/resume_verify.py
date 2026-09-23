# -*- coding: utf-8 -*-
"""对「生成已完成、验证未通过」的历史项目做 verify-only 断点续跑。

keep7 取证：completed.json 在生成阶段末尾写入（pipeline.py:744），
此类项目走不进 main.py --resume 的查找通道（要求无完成标记）；
而验证失败的项目需要的只是「修复后的 verify 闭环」，不是重烧生成。
本驱动零生成 token，直接 verify_delivery 到终局。

用法:
    python scripts/resume_verify.py --output-dir .tmp/rehearsal-keep7
    python scripts/resume_verify.py --project-dir <projects/xxx 绝对路径>
    python scripts/resume_verify.py --project-dir ... --report-only \\
        --requirements-dir <题面目录>     # 零消费读数（含编译自评分环）

终局落盘: <project>/sessions/verify_final.json  {ok, report, ts}
退出码: 0=PASS, 1=FAIL（供接力脚本判别）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings  # noqa: E402
from app.arcbench_smoke import verify_delivery  # noqa: E402


def _find_project(output_dir: Path) -> Path | None:
    """output-dir 下最新含 code/ 与 requirements 的项目。"""
    root = output_dir / "projects"
    if not root.is_dir():
        return None
    cands = [
        p for p in root.iterdir()
        if (p / "code").is_dir()
        and (p / "sessions" / "requirements.md").is_file()
    ]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--project-dir", default=None)
    ap.add_argument("--max-app-rounds", type=int, default=3)
    ap.add_argument("--max-verify-rounds", type=int, default=3)
    ap.add_argument("--requirements-dir", default=None,
                    help="题面目录：喂给编译自评分环当验收清单来源")
    ap.add_argument("--report-only", action="store_true",
                    help="只出确定性审计读数，零消费：装一把已耗尽的活动护栏，"
                         "验收段所有 LLM 通道（修复／自测生成）据此自行跳过")
    args = ap.parse_args()

    if args.project_dir:
        project = Path(args.project_dir).resolve()
    else:
        found = _find_project(Path(args.output_dir).resolve())
        if found is None:
            print(f"[resume-verify] {args.output_dir}/projects 下没有"
                  "可验证项目（缺 code/ 或 requirements.md）")
            return 1
        project = found
    print(f"[resume-verify] 项目: {project}", flush=True)

    settings = load_settings(
        config_file=Path(__file__).resolve().parents[1] / "config.json")
    requirement = (project / "sessions" / "requirements.md").read_text(
        encoding="utf-8", errors="replace")

    t0 = time.time()
    if args.report_only:
        # 复用交付闸自己的开工前体检：护栏既已耗尽，_repair_blocked() 对每个
        # LLM 通道都返回不可开工 → 这份读数与真跑同口径，但不花一分钱
        from app.utils.budget import BudgetGuard, set_active_budget_guard

        g = BudgetGuard(budget_tokens=1_000, repair_reserve_ratio=0.25)
        g.record(1_001)
        set_active_budget_guard(g)
        print("[resume-verify] report-only：护栏置为已耗尽 → "
              "冒烟/锚点 LLM 修复与自测生成分支全部跳过", flush=True)
    ok, report = verify_delivery(
        project, requirement, settings,
        max_app_rounds=args.max_app_rounds,
        max_verify_rounds=args.max_verify_rounds,
        requirements_dir=(Path(args.requirements_dir).resolve()
                          if args.requirements_dir else None),
    )
    report_full = report if len(report) <= 4000 else report[:2000] + \
        "\n...\n" + report[-2000:]
    print(f"[verify] {'PASS' if ok else 'FAIL'}", flush=True)
    print(report_full, flush=True)

    out = project / "sessions" / "verify_final.json"
    out.write_text(json.dumps({
        "ok": ok,
        "report": report_full,
        "seconds": round(time.time() - t0, 1),
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[resume-verify] 终局已落盘: {out}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
