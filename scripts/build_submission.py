# -*- coding: utf-8 -*-
"""构建平台提交包：以上一次已验证的提交包文件清单为骨架，灌入当前工作区内容。

取证（2026-09-20）：提交包 = token-burner 产品本体（app/ + main.py +
config.json + skills/ + template/ 等），不是 frontend/backend 交付布局
（那是平台跑内部产物）。沿用 16:22 版 zip 的 197 文件清单，保证与已
跑通过的 runner 兼容；内容全部取当前 HEAD（含当晚全部修复）。

用法:
    python scripts/build_submission.py [--out token-burner-submission-v7.zip]
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "token-burner-submission.zip"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="token-burner-submission-v7.zip")
    ap.add_argument("--baseline", default=str(BASELINE),
                    help="作为文件清单骨架的已验证提交包")
    args = ap.parse_args()

    base = Path(args.baseline)
    if not base.is_file():
        print(f"[pack] 基线包不存在: {base}")
        return 2
    with zipfile.ZipFile(base) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]

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
          f"（工作区缺失 {len(missing)}，其中 {len(fallback)} 已从基线回补）")
    for m in missing[:10]:
        print("  missing:", m)
    return 0 if not (set(missing) - set(fallback)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
