# -*- coding: utf-8 -*-
"""提交包构建器（v9 起禁止手工 zip）。

取证（2026-09-23）：v8 包是手工攒出来的——仓库里没有打包脚本，而 git
跟踪集里混着 187 个本机产物（release/token-burner.exe 86MB、projects/、
logs/、_docgen/）。手工攒包在下一次赶时间时必然带出这些残留（体积、
泄漏彩排现场、甚至官方题面/ARC 编译器素材=合规事故）。本脚本把
"包内清单"固化为 v8 已验证的白名单形状，并对残留物做硬断言。

用法：python3 scripts/build_submission.py [--out <zip>] [--base <参考包 v8>]
                                         [--blank <官方模板包>] [--allow-drop]
（skills/ 与 template/ 只存在于官方 Blank Template，工作树里没有，必须
由 --blank 补齐；漏掉即官方脚手架不完整。）
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 允许进入提交包的顶层条目（v8 实测形状）
ALLOW_ROOT = {
    "main.py", "requirements.txt", "config.json", "README.md",
    "app", "arcbench-agent-runtime", "template", "skills", "examples",
}
# 官方脚手架：工作树里根本不存在，只能来自 Blank Template 包
SCAFFOLD_ONLY = ("template/", "skills/")
# 任何情况下都不得入包（本机产物 / 敏感 / 合规）
DENY_ANYWHERE = (
    "__pycache__", ".venv", "node_modules", ".pytest_cache", ".git/",
    "release/", "projects/", "logs/", "media/", "_docgen/", ".tmp/",
    "tests/", "docs/", "assets/",
)
# 合规红线：ARC 编译器与官方题面素材只许本地，不得随包提交
DENY_COMPLIANCE = (
    "arc-bench", "agentic-requirement-compiler", "helpers.ts",
    "requirements.yaml", ".env",
)
DENY_SUFFIX = (".exe", ".pyc", ".log", ".zip", ".pdf", ".ico", ".jpg")


def _denied(rel: str) -> str | None:
    low = rel.lower()
    for d in DENY_ANYWHERE:
        # 以 / 结尾的条目=目录前缀（只挡顶层目录，examples/logscan/tests
        # 这类随 example 一起交付的嵌套 tests 是合法内容）；
        # 其余=任意位置子串（__pycache__、node_modules 等）
        if d.endswith("/"):
            if low.startswith(d.lower()):
                return d
        elif d.lower() in low:
            return d
    for d in DENY_COMPLIANCE:
        if ("/" + d.lower()) in ("/" + low) and not (
                d == ".env" and low.endswith(".env.example")):
            return f"合规:{d}"
    if low.endswith(DENY_SUFFIX):
        return "后缀"
    return None


def manifest_from_base(base_zip: Path) -> list[str]:
    with zipfile.ZipFile(base_zip) as zf:
        return [n for n in zf.namelist() if not n.endswith("/")][:]


# 包内**内容**扫描：文件名过禁令不等于没有泄漏（配置里写死 key、
# 彩排残留把官方仓库地址印进日志，都在包内文件里而不是包名上）。
_SECRET_RE = re.compile(
    r"(?i)\b(?:openai[_-]?)?(?:api[_-]?key|secret|access[_-]?token|password)"
    r"['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{8,}(?![A-Za-z0-9_\-]*\())"
    r"|(?<![\w-])((?:sk|ak|ghp|xoxb)[-_][A-Za-z0-9]{12,})")
# 占位符白名单：文档/示例里的假值，命中即放行。值的字符集已排掉
# os.environ[...] / ${VAR} 这类代码引用，这里只兜住 "your-key-here" 形态。
_PLACEHOLDER = re.compile(
    r"(?i)^(?:your[-_]|xxx+|placeholder|example|dummy|changeme|"
    r"sk-?x{3,}|ak_?x{3,}|test[-_]?\w*|fake[-_]?)")
_COMPLIANCE_BODY = (
    "code-philia", "agentic-requirement-compiler",
)


def _content_leaks(zf: zipfile.ZipFile) -> list[str]:
    out: list[str] = []
    for info in zf.infolist():
        rel = info.filename
        if rel.endswith("/") or rel.endswith((".png", ".jpg", ".gif", ".ico",
                                              ".woff", ".woff2", ".zip")):
            continue
        try:
            txt = zf.read(rel).decode("utf-8", "replace")
        except Exception:
            continue
        for m in _SECRET_RE.finditer(txt):
            val = (m.group(1) or m.group(2) or "").strip()
            if not val or _PLACEHOLDER.match(val):
                continue
            # 真实密钥的形态：带数字或足够长。少这一道，`"api_key":
            # mask_key(...)` 这类代码引用会被当成泄漏（首版实测误报）。
            if len(val) < 16 and not any(c.isdigit() for c in val):
                continue
            # 只印前缀+长度：命中详情本身可能就是密钥，不得回显进日志
            out.append(f"{rel}: 疑似真实密钥 {val[:3]}…(len={len(val)})")
            break
        low = txt.lower()
        for d in _COMPLIANCE_BODY:
            if d in low:
                out.append(f"{rel}: 含官方素材引用 {d}")
    return out


def build(out_path: Path, base_zip: Path, blank_zip: Path,
          allow_drop: bool = False) -> int:
    base_names = manifest_from_base(base_zip)
    # 以参考包清单为准，再补上"允许根目录下新增的文件"（防新模块漏包）
    picked = set(base_names)
    for rel in sorted(p for p in ROOT.rglob("*") if p.is_file()):
        r = rel.relative_to(ROOT).as_posix()
        if r.split("/")[0] not in ALLOW_ROOT and r not in ALLOW_ROOT:
            continue
        if _denied(r):
            continue
        if r.startswith(("app/", "arcbench-agent-runtime/", "template/",
                         "skills/", "examples/")) or r in ALLOW_ROOT:
            picked.add(r)
    # 官方 Blank Template 脚手架（skills/ 与 template/ 只存在于官方包，
    # 工作树里没有）：漏掉=模板不完整，官方判分吃过这个亏
    blank_members: dict[str, bytes] = {}
    if blank_zip.is_file():
        with zipfile.ZipFile(blank_zip) as zf:
            for n in zf.namelist():
                if n.endswith("/") or n.split("/")[0] not in ALLOW_ROOT:
                    continue
                if _denied(n):      # 模板包同样过禁令，否则它绕过 picked 过滤
                    continue
                blank_members[n] = zf.read(n)
    # 纯脚手架目录即使参考清单里没有也必须补齐（参考包本身漏过一次）
    picked |= {n for n in blank_members if n.startswith(SCAFFOLD_ONLY)}
    problems: list[str] = []
    missing: list[str] = []
    from_template = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in sorted(picked):
            deny = _denied(rel)
            if deny:
                problems.append(f"{rel} ← {deny}")
                continue
            src = ROOT / rel
            if src.is_file():
                zf.write(src, rel)
            elif rel in blank_members:
                zf.writestr(rel, blank_members[rel])
                from_template += 1
            else:
                missing.append(rel)
    if from_template:
        print(f"[build] 官方脚手架自 Blank Template 补齐: {from_template} 文件")
    if problems:
        print("拒绝入包（命中禁令）:")
        for p in problems[:20]:
            print("  ", p)
    if missing:
        print(f"参考清单里有 {len(missing)} 个文件工作树已不存在（跳过）:")
        for m in missing[:10]:
            print("  ", m)
    with zipfile.ZipFile(out_path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
    print(f"\n[build] {out_path.name}: {len(names)} 文件 "
          f"{out_path.stat().st_size / 1024:.0f}KB")
    added = sorted(set(names) - set(base_names))
    dropped = sorted(set(base_names) - set(names))
    for tag, lst in (("新增", added), ("剔除", dropped)):
        if lst:
            print(f"  {tag} {len(lst)}: {', '.join(lst[:6])}"
                  + ("…" if len(lst) > 6 else ""))
    # 自检：包内不得出现禁令词
    with zipfile.ZipFile(out_path) as zf:
        leak = [n for n in zf.namelist() if _denied(n)]
        body_leak = _content_leaks(zf) if not leak else []
    if leak:
        print(f"[build] 合规自检失败 {len(leak)}: {leak[:5]}")
        return 1
    if body_leak:
        print(f"[build] 内容自检失败 {len(body_leak)}（真密钥/官方素材）:")
        for b in body_leak[:10]:
            print("  ", b)
        return 1
    if dropped and not allow_drop:
        # v8 是 206 文件参考形状：缩水只可能是漏打包（第一次跑就静默丢了
        # 45 个——skills/+template/ 不在工作树）。宁可报错也不出静默瘦包。
        print(f"[build] 相比参考包少了 {len(dropped)} 个文件，逐个核对后"
              f"加 --allow-drop 认可：\n  " + "\n  ".join(dropped))
        return 1
    print("[build] 合规自检通过（无官方题面/ARC 素材/本机产物/密钥文件）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".tmp/submission-pack/v9.zip"))
    ap.add_argument("--base", default=str(ROOT / "token-burner-submission-v8.zip"))
    ap.add_argument("--blank", default=str(ROOT / "agent-blank-based.zip"),
                    help="官方 Blank Template 包：补齐工作树里不存在的脚手架")
    ap.add_argument("--allow-drop", action="store_true",
                    help="认可相比参考包的文件裁剪（默认硬失败）")
    a = ap.parse_args()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    base = Path(a.base)
    if not base.is_file():
        print(f"参考包不存在: {base}", file=sys.stderr)
        return 2
    return build(out, base, Path(a.blank), allow_drop=a.allow_drop)


if __name__ == "__main__":
    sys.exit(main())
