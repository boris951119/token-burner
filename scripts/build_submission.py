# -*- coding: utf-8 -*-
"""构建平台提交包：基线包清单 ∪ 当前工作区 git 跟踪文件，灌入当前内容。

取证（2026-09-20）：提交包 = token-burner 产品本体（app/ + main.py +
config.json + skills/ + template/ 等），不是 frontend/backend 交付布局
（那是平台跑内部产物）。内容全部取当前 HEAD（含当晚全部修复）。

取证（2026-09-21，Qoder 交叉审查）：纯基线清单做骨架会整体静默漏打
工作区新增模块——v7 实测缺 mechanical_assembly.py / selftest_gate.py /
model_ledger.py，v8 上平台后这些模块只剩被 except 吞掉的 ImportError，
无声降级。故清单改为「基线 ∪ git ls-files（限基线已有顶层前缀）」：
新文件自动并入，包顶层结构与已跑通过的 runner 保持兼容；logs/.tmp/
dist 等未跟踪噪声天然排除（gitignored 不会被 ls-files 列出）。

用法:
    python scripts/build_submission.py [--out token-burner-submission-v8.zip]
"""
from __future__ import annotations

import argparse
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "token-burner-submission.zip"


def _tracked_names(tops: set[str]) -> list[str]:
    """当前工作区 git 跟踪文件，只保留基线包已有的顶层前缀。"""
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=str(ROOT), capture_output=True,
            text=True, encoding="utf-8", timeout=60,
        ).stdout
    except Exception:
        return []
    names: list[str] = []
    for line in out.splitlines():
        name = line.strip().replace("\\", "/")
        if not name or name.split("/", 1)[0] not in tops:
            continue
        if "/logs/" in f"/{name}":   # 误跟踪的运行日志不进包
            continue
        names.append(name)
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="token-burner-submission-v8.zip")
    ap.add_argument("--baseline", default=str(BASELINE),
                    help="作为结构骨架的已验证提交包")
    args = ap.parse_args()

    base = Path(args.baseline)
    if not base.is_file():
        print(f"[pack] 基线包不存在: {base}")
        return 2
    with zipfile.ZipFile(base) as z:
        base_names = [n for n in z.namelist() if not n.endswith("/")]
    tops = {n.split("/", 1)[0] for n in base_names}
    added = [n for n in _tracked_names(tops) if n not in set(base_names)]
    names = base_names + added

    out = ROOT / args.out
    missing: list[str] = []
    fallback: list[str] = []
    with zipfile.ZipFile(base) as base_z, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in names:
            src = ROOT / name
            if src.is_file():
                z.write(src, name)
                continue
            # 工作区缺失（如 skills/ 平台运行时技能）→ 回退基线包字节，
            # 保证包完整； these files 平台 runner 需要不可缺。
            missing.append(name)
            try:
                z.writestr(name, base_z.read(name))
                fallback.append(name)
            except KeyError:
                pass
    print(f"[pack] {out} 共 {len(names)} 文件"
          f"（基线 {len(base_names)} + 新增 {len(added)}；"
          f"工作区缺失 {len(missing)}，其中 {len(fallback)} 已从基线回补）")
    for m in added[:15]:
        print("  added:", m)
    for m in missing[:10]:
        print("  missing:", m)
    return 0 if not (set(missing) - set(fallback)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
