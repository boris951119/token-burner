# -*- coding: utf-8 -*-
"""本地闭环一条命令：生成 → 官方评分 → 失败明细落盘。

用户质询取证（2026-09-19）：本地生成与平台生成的 LLM token 成本完全
相同（同一中转 key），但本地失败可以免费无限迭代，平台失败 = 白扔
5-6 小时 + 评分历史留痕。默认工作流必须本地先跑通、平台只做确认。

用法:
    python scripts/local_loop.py --requirement <requirements目录> [--task keep]
    python scripts/local_loop.py --resume <output-dir>   # 断点续跑生成

流程: main.py 本地生成(中转 key) → local_grade.py 导出+起服+官方真题
→ grade-summary.json(通过率+逐题失败)。退出码 0=全过, 1=有失败。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PY = sys.executable


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--requirement", help="需求目录（官方 tasks 的 requirements）")
    ap.add_argument("--resume", help="已有 output-dir，断点续跑生成阶段")
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--name", default="local-loop")
    ap.add_argument("--task", default="keep")
    ap.add_argument("--grade-only", help="跳过生成，直接对已有项目评分")
    args = ap.parse_args()

    stamp = time.strftime("%m%d-%H%M")
    out_dir = args.output_dir or str(ROOT / ".tmp" / f"local-loop-{args.name}-{stamp}")
    project_dir = None

    if args.grade_only:
        project_dir = args.grade_only
    else:
        # ---- 生成（与平台同一 main.py、同一中转配置）----
        gen_cmd = [PY, str(ROOT / "main.py")]
        if args.resume:
            gen_cmd += [args.resume, "--resume", "--output-dir",
                        str(Path(args.resume).parent)]
            # main.py --resume 语义: 需求路径 + --resume；输出目录继承
            gen_cmd = [PY, str(ROOT / "main.py"), args.resume,
                       "--resume", "--output-dir",
                       args.output_dir or str(Path(args.resume) / "..")]
        else:
            if not args.requirement:
                print("[loop] 需要 --requirement 或 --resume 或 --grade-only")
                return 2
            gen_cmd += [args.requirement, "--output-dir", out_dir,
                        "--type", "web", "--mode", "auto"]
        print(f"[loop] 生成开始: {' '.join(gen_cmd)}", flush=True)
        t0 = time.time()
        rc = subprocess.call(gen_cmd, cwd=str(ROOT))
        print(f"[loop] 生成结束 rc={rc} 用时 {(time.time()-t0)/60:.0f} 分钟",
              flush=True)
        if rc != 0:
            print("[loop] 生成失败——交付策略下 rc=0 才代表产物落盘")
            return 1

    # ---- 定位项目目录（最新含 code/ 的项目）----
    projects = ROOT / ".tmp"
    candidates = sorted(
        (p for p in Path(out_dir or projects).glob("projects/*")
         if (p / "code").is_dir()),
        key=lambda p: p.stat().st_mtime, reverse=True)
    if args.grade_only:
        target = Path(args.grade_only)
    elif candidates:
        target = candidates[0]
    else:
        print("[loop] 找不到含 code/ 的项目目录")
        return 2
    print(f"[loop] 评分对象: {target}", flush=True)

    # ---- 官方评分 ----
    grade = subprocess.run(
        [PY, str(ROOT / "scripts" / "local_grade.py"),
         "--project-dir", str(target), "--task", args.task],
        cwd=str(ROOT))
    summary = ROOT / "scripts" / "official_grade" / "grade-summary.json"
    if summary.is_file():
        print("[loop] 评分摘要:", summary.read_text(encoding="utf-8"))
    return grade.returncode


if __name__ == "__main__":
    sys.exit(main())
