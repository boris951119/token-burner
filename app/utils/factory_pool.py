# -*- coding: utf-8 -*-
"""作者 create_app 池试装（v53 刀B → v54 P1-3 子进程隔离）。

045fe：webui_app.create_app 因 seed_db 缺参 TypeError，择优落到
机械壳 app_main，export-probe 仍 health+home 绿 → probe-fast 直交。
本函数在快车道前对 code/ 内非机械壳工厂做一次真实 create_app()；
任一作者工厂炸 → 退出快车道走完整验收。

v54（批次#78 P1-3）：父进程严禁 import 生成代码 / del sys.modules /
插 code 进 sys.path——生成包叫 app/config 时会逐出 agent 自身模块。
改由子进程试装，JSON 回传 {failures, tried, infra_error}。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

_PROBE_TIMEOUT_S = 240

# 子进程 runner：只在隔离解释器里 import 生成代码。
_RUNNER_SRC = textwrap.dedent(r'''
import importlib
import json
import sys
from pathlib import Path

code_dir = Path(sys.argv[1]).resolve()
failures: list[str] = []
tried = 0
infra_error = False

try:
    if not code_dir.is_dir():
        print(json.dumps({"failures": [], "tried": 0, "infra_error": False},
                         ensure_ascii=False))
        raise SystemExit(0)

    root_s = str(code_dir)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    for child in sorted(code_dir.iterdir()):
        if (child.is_dir() and not child.name.startswith(("_", "."))
                and not (child / "__init__.py").exists()):
            s = str(child)
            if s not in sys.path:
                sys.path.insert(0, s)

    for child in sorted(code_dir.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        py = child / f"{child.name}.py"
        if not py.is_file():
            continue
        mod_name_dotted = f"{child.name}.{child.name}"
        mod = None
        mod_name = child.name
        last_exc = None
        for cand in (mod_name_dotted, child.name):
            try:
                for key in list(sys.modules):
                    if key == child.name or key.startswith(child.name + "."):
                        del sys.modules[key]
                mod = importlib.import_module(cand)
                mod_name = cand
                break
            except Exception as exc:
                last_exc = exc
                mod = None
        if mod is None:
            try:
                src = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "def create_app" in src and "__arcbench_assembled__" not in src:
                failures.append(
                    f"{child.name}: import失败 "
                    f"{type(last_exc).__name__}: {last_exc}"[:160]
                )
            continue
        if getattr(mod, "__arcbench_assembled__", False):
            continue
        create = getattr(mod, "create_app", None)
        if not callable(create):
            continue
        tried += 1
        try:
            app = create()
        except Exception as exc:
            failures.append(
                f"{mod_name}.create_app: {type(exc).__name__}: {exc}"[:200]
            )
            continue
        if app is None:
            failures.append(f"{mod_name}.create_app: 返回 None")
except Exception as exc:
    infra_error = True
    failures = [f"probe基础设施失败: {type(exc).__name__}: {exc!r}"[:200]]
    tried = 0

print(json.dumps(
    {"failures": failures, "tried": tried, "infra_error": infra_error},
    ensure_ascii=False,
))
''')


def probe_author_factories(code_dir: Path) -> dict:
    """子进程试装所有作者 create_app。

    返回 ``{failures: list[str], tried: int, infra_error: bool}``。
    - failures 非空 → 作者工厂炸（退出快车道）
    - tried=0 且无 failures → 无作者工厂，不据此拦快车道
    - infra_error=True 或子进程超时/非 JSON → 探测自身失败（fail-closed）
    """
    code_dir = Path(code_dir).resolve()
    if not code_dir.is_dir():
        return {"failures": [], "tried": 0, "infra_error": False}

    try:
        proc = subprocess.run(
            [sys.executable, "-c", _RUNNER_SRC, str(code_dir)],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
            env={
                **{k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
    except subprocess.TimeoutExpired:
        return {
            "failures": [
                f"probe基础设施失败: TimeoutExpired "
                f"(timeout={_PROBE_TIMEOUT_S}s)"
            ],
            "tried": 0,
            "infra_error": True,
        }
    except OSError as exc:
        return {
            "failures": [
                f"probe基础设施失败: {type(exc).__name__}: {exc!r}"[:200]
            ],
            "tried": 0,
            "infra_error": True,
        }

    lines = [ln for ln in (proc.stdout or "").strip().splitlines() if ln]
    if not lines:
        detail = (proc.stderr or "").strip()[:120] or f"rc={proc.returncode}"
        return {
            "failures": [f"probe基础设施失败: 子进程无输出 ({detail})"],
            "tried": 0,
            "infra_error": True,
        }
    try:
        data = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return {
            "failures": [
                f"probe基础设施失败: JSONDecodeError: {exc!r}"[:200]
            ],
            "tried": 0,
            "infra_error": True,
        }
    if not isinstance(data, dict):
        return {
            "failures": ["probe基础设施失败: 子进程输出非 dict"],
            "tried": 0,
            "infra_error": True,
        }
    failures = [str(x) for x in (data.get("failures") or [])]
    tried = int(data.get("tried") or 0)
    infra_error = bool(data.get("infra_error"))
    return {"failures": failures, "tried": tried, "infra_error": infra_error}


def probe_author_factories_safe(code_dir: Path) -> tuple[list[str], bool]:
    """带基础设施隔离的试装包装：探测自身异常 ≠「无工厂」。

    返回 (issues, infra_failed)。infra_failed=True 时调用方必须视为
    fail-closed（退出快车道），不得当作绿。
    """
    try:
        result = probe_author_factories(code_dir)
    except Exception as exc:
        return ([f"probe基础设施失败: {type(exc).__name__}: {exc!r}"[:200]],
                True)
    if result.get("infra_error"):
        issues = list(result.get("failures") or [])
        if not issues or not any("probe基础设施失败" in x for x in issues):
            issues = [
                "probe基础设施失败: " + (issues[0] if issues else "unknown")
            ]
        return issues, True
    return list(result.get("failures") or []), False
