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
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 试跑档位（v42-4 / v43）：硬帽 + 关 specs + 便宜三腿。随包交正式赛 =
# 不评分/半截断气温床；打包时硬失败，禁止「记得翻回去」靠人。
_TRIAL_MODEL_SETS = (
    frozenset({"openai/qwen3.7-plus", "openai/glm-5.3",
               "openai/deepseek-v4-flash"}),
    frozenset({"openai/deepseek-v4-flash", "openai/qwen3.7-plus",
               "openai/glm-5.3-flash"}),
)


def assert_official_profile(config_path: Path | None = None) -> list[str]:
    """正式提交包档位硬断言；返回问题列表（空 = 通过）。"""
    cfg_path = config_path or (ROOT / "config.json")
    problems: list[str] = []
    if not cfg_path.is_file():
        return [f"缺少 config.json: {cfg_path}"]
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"config.json 无法解析: {exc!r}"]
    if not isinstance(raw, dict):
        return ["config.json 根必须是对象"]
    cap = raw.get("max_task_tokens_cap", 0)
    try:
        cap_n = int(cap)
    except (TypeError, ValueError):
        problems.append(f"max_task_tokens_cap 非法: {cap!r}（正式包必须为 0）")
    else:
        if cap_n > 0:
            problems.append(
                f"试跑硬帽仍开启 max_task_tokens_cap={cap_n}"
                "（正式包必须为 0）")
    if raw.get("selftest_specs_enabled", True) is False:
        problems.append(
            "selftest_specs_enabled=false（正式包必须 true）")
    models = raw.get("models") or []
    if not isinstance(models, list) or not models:
        problems.append("models 为空或非法")
    else:
        norm = frozenset(str(m) for m in models)
        if norm in _TRIAL_MODEL_SETS:
            problems.append(
                f"编队仍是试跑档 {sorted(norm)}——"
                "正式包请用官方三腿（如 deepseek-v4-pro / "
                "deepseek-v4-flash / qwen3.7-max）")
    return problems

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
    # runtime 包早已切到 package-dir={"":"src"}，这份 build/lib 是 legacy
    # setuptools 构建的陈旧副本（与 src 逐字相同）：pip 永远不会读它，随包
    # 提交只是在评审者眼里变成「同一模块两份源码」。
    "arcbench-agent-runtime/build/",
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
          allow_drop: bool = False,
          allow_trial: bool = False,
          skip_presubmit: bool = False) -> int:
    if not allow_trial:
        profile_problems = assert_official_profile()
        if profile_problems:
            print("[build] 正式档位断言失败（试跑 config 禁止随包上正式赛）:")
            for p in profile_problems:
                print("  ", p)
            print("  翻回官方档后再打包；私有 key 压测若故意用试跑档，"
                  "加 --allow-trial")
            return 1
    else:
        print("[build] --allow-trial：跳过正式档位断言（仅限私有 key 压测包）")
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
    # 提交前硬闸 A+B（不进包；失败则拒出包）
    if not skip_presubmit:
        try:
            from scripts.presubmit_gate import run_gate
            report = run_gate(out_path, full=False)
            for c in report.checks:
                mark = "PASS" if c.ok else "FAIL"
                print(f"[presubmit] [{mark}] {c.name}: {c.detail}", flush=True)
            if not report.ok:
                print("[build] 提交前硬闸 A+B 失败 —— 拒绝出包。"
                      "上平台前另需: python3 scripts/presubmit_gate.py "
                      f"--zip {out_path} --full", flush=True)
                return 1
            print("[build] 提交前硬闸 A+B 通过"
                  f"（报告 .tmp/presubmit/{out_path.stem}/report.json；"
                  "上平台前请 --full 跑 C）", flush=True)
        except Exception as exc:
            print(f"[build] 硬闸执行异常（拒绝出包）: {exc!r}", flush=True)
            return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".tmp/submission-pack/v9.zip"))
    ap.add_argument("--base", default=str(ROOT / "token-burner-submission-v8.zip"))
    ap.add_argument("--blank", default=str(ROOT / "agent-blank-based.zip"),
                    help="官方 Blank Template 包：补齐工作树里不存在的脚手架")
    ap.add_argument("--allow-drop", action="store_true",
                    help="认可相比参考包的文件裁剪（默认硬失败）")
    ap.add_argument("--allow-trial", action="store_true",
                    help="允许试跑档 config 入包（仅私有 key 压测；"
                         "正式交分禁止）")
    ap.add_argument("--skip-presubmit", action="store_true",
                    help="跳过 A+B 硬闸（仅调试打包脚本本身）")
    a = ap.parse_args()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    base = Path(a.base)
    if not base.is_file():
        print(f"参考包不存在: {base}", file=sys.stderr)
        return 2
    return build(out, base, Path(a.blank),
                 allow_drop=a.allow_drop,
                 allow_trial=a.allow_trial,
                 skip_presubmit=a.skip_presubmit)


if __name__ == "__main__":
    sys.exit(main())
