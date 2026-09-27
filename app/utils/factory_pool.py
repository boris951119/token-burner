# -*- coding: utf-8 -*-
"""作者 create_app 池试装（v53 刀B）。

045fe：webui_app.create_app 因 seed_db 缺参 TypeError，择优落到
机械壳 app_main，export-probe 仍 health+home 绿 → probe-fast 直交。
本函数在快车道前对 code/ 内非机械壳工厂做一次真实 create_app()；
任一作者工厂炸 → 退出快车道走完整验收。
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


def probe_author_factories(code_dir: Path) -> list[str]:
    """试装所有作者 create_app；返回失败描述（空=作者工厂均可起或没有）。

    v53.1（批次#78 评审 #1）：基础设施异常**不得**返回空列表——空=快车道
    放行，守卫失败开放就是假绿后门。探测自身出错时返回带
    `probe基础设施失败` 前缀的非空红项，调用方据此退出快车道（fail-closed）。
    """
    code_dir = Path(code_dir).resolve()
    if not code_dir.is_dir():
        return []

    # 保证包可导入（与导出布局同构：子目录入 path）
    inserted: list[str] = []
    root_s = str(code_dir)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
        inserted.append(root_s)
    for child in sorted(code_dir.iterdir()):
        if (child.is_dir() and not child.name.startswith(("_", "."))
                and not (child / "__init__.py").exists()):
            s = str(child)
            if s not in sys.path:
                sys.path.insert(0, s)
                inserted.append(s)

    failures: list[str] = []
    tried = 0
    try:
        for child in sorted(code_dir.iterdir()):
            if not child.is_dir() or child.name.startswith(("_", ".")):
                continue
            py = child / f"{child.name}.py"
            if not py.is_file():
                continue
            mod_name_dotted = f"{child.name}.{child.name}"
            mod = None
            last_exc: Exception | None = None
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
                continue  # 机械壳不计入作者池
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
    finally:
        # 不主动 sys.path.remove——避免扰动同进程后续导入；测试进程短命可接受
        pass

    if tried == 0:
        return []  # 无作者工厂：不据此拦快车道（骨架/单文件另论）
    return failures


def probe_author_factories_safe(code_dir: Path) -> tuple[list[str], bool]:
    """带基础设施隔离的试装包装：探测自身异常 ≠「无工厂」。

    返回 (issues, infra_failed)。infra_failed=True 时调用方必须视为
    fail-closed（退出快车道），不得当作绿。
    """
    try:
        return probe_author_factories(code_dir), False
    except Exception as exc:
        return ([f"probe基础设施失败: {type(exc).__name__}: {exc!r}"[:200]],
                True)
