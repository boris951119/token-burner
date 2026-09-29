# -*- coding: utf-8 -*-
"""行走骨架（刀L，Walking Skeleton）：链路连通从交付祈祷变成开发段不变量。

病灶取证（81bc / v55-github / v48）：
- 集成断裂在交付段冒烟才第一次见面——首页 HTTPError 静默 4 小时、
  自测 86/89 史上最好但 /login 由错误模块渲染、择优选错门整跑 0 分。
  官方评测是一只从大门进来的浏览器：链不通不是打折，是清零。

方案：契约冻结后、任何业务模块开发前，机械装配一个**活着的**应用骨架
（复用 mechanical_assembly.assemble——双框架、幂等、坏模块隔离、语法
自证），起服冒烟 health+首页；此后每完成一个依赖层重新装配 + 起服探活，
路由数趋势即集成进度硬读数。

所有权口径（与既有保底策略对齐，不新增择优规则）：
- 开发段：骨架（app_main）就是唯一入口——本模块直接起它，无竞争；
- 交付段：app_main 带 `__arcbench_assembled__` 标记，作者入口在场时
  让位（mechanical_assembly 既定口径），仅作"无活入口"的保底。
- 单模块任务不建骨架：单模块本身就是链，别为仪式感烧起服成本。

只增不改：骨架文件为系统所有（content hash 一致则跳过写盘）；业务
模块文件永不触碰。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from app.utils.mechanical_assembly import assemble

SKELETON_LOG = "skeleton_smoke.md"

_SHELL_PKG = "skeleton_shell"

_SHELL_INIT = "from skeleton_shell.shell import bp  # noqa: F401\n"

_SHELL_TEMPLATE = '''\
# -*- coding: utf-8 -*-
"""行走骨架诊断壳（walking_skeleton 生成，系统所有，勿手改）。

只挂非冲突路由（/api/__skeleton/status），不碰 `/`——首页归属作者 UI，
保底首页由 app_main 机械补挂。导入期零业务依赖：坏模块不连坐。
"""
from __future__ import annotations

__arcbench_assembled__ = True  # 系统壳：永不作为入口候选（与 app_main 同规）

EXPECTED_MODULES = {expected!r}
BUILT_AT = {built_at!r}

from flask import Blueprint, current_app, jsonify

bp = Blueprint("skeleton_shell", __name__)


@bp.route("/api/__skeleton/status")
def skeleton_status():
    rules = list(current_app.url_map.iter_rules())
    return jsonify(
        ok=True,
        routes=len(rules),
        expected_modules=EXPECTED_MODULES,
        built_at=BUILT_AT,
    )
'''


def should_build_skeleton(plans: list) -> bool:
    """单模块直出路径不建骨架（单模块本身就是链）。"""
    return len(plans) > 1


def build_skeleton(code_dir: Path, plans: list) -> dict:
    """（重新）装配行走骨架：app_main 吃进当前全部可挂载模块 + 诊断壳。

    幂等：assemble 重复调用覆盖同文件；壳 content 变了才重写。
    返回 assemble 摘要（framework/blueprints/coverage 等）。
    """
    code_dir = Path(code_dir)
    code_dir.mkdir(parents=True, exist_ok=True)
    summary = assemble(code_dir, scaffold=False)
    expected = [p.name for p in plans]
    pkg = code_dir / _SHELL_PKG
    shell = pkg / "shell.py"
    content = _SHELL_TEMPLATE.format(
        expected=expected, built_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    # 壳必须是**无下划线前缀的包**：scan_surfaces 只扫包目录（_ 前缀与
    # 根级 .py 一律跳过），否则诊断壳永远挂不进 app_main。
    if not shell.is_file() or shell.read_text(encoding="utf-8") != content:
        pkg.mkdir(parents=True, exist_ok=True)
        init = pkg / "__init__.py"
        if not init.is_file():
            init.write_text(_SHELL_INIT, encoding="utf-8")
        shell.write_text(content, encoding="utf-8")
        # 壳落地/更新后重装一次：让 app_main 把诊断壳挂上（assemble 幂等）
        summary = assemble(code_dir, scaffold=False)
    return summary


def smoke_skeleton(code_dir: Path, port: int = 5077,
                   deadline_s: float = 25.0) -> dict:
    """起服骨架并探活：/api/health + / + 诊断 status（路由数）。

    返回 {ok, health, home, routes, error, log_tail}——ok=False 时
    log_tail 是排障唯一线索，绝不静默。
    """
    code_dir = Path(code_dir).resolve()
    port = int(os.environ.get("SKELETON_SMOKE_PORT", port))
    for candidate in range(port, port + 40):
        try:
            import socket

            with socket.socket() as s:
                s.bind(("127.0.0.1", candidate))
                port = candidate
                break
        except OSError:
            continue
    boot = (
        "import os, sys\n"
        f"sys.path.insert(0, {str(code_dir)!r})\n"
        "from app_main.app_main import create_app\n"
        "create_app().run(host='127.0.0.1', threaded=True,\n"
        f"                 port=int(os.environ.get('PORT', {port!r})))\n"
    )
    env = dict(os.environ, PORT=str(port))
    proc = subprocess.Popen(
        [sys.executable, "-c", boot], cwd=str(code_dir), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"

    def _get(path: str, timeout: float = 3.0):
        try:
            with urllib.request.urlopen(base + path, timeout=timeout) as r:
                return r.status, r.read(65536)
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    rep: dict = {"ok": False, "health": None, "home": None,
                 "routes": None, "status": None, "error": "", "log_tail": ""}
    end = time.time() + deadline_s
    health = None
    while time.time() < end:
        if proc.poll() is not None:
            break  # 进程死了：日志里找死因
        health, _ = _get("/api/health", timeout=2.0)
        if health == 200:
            break
        time.sleep(0.5)
    rep["health"] = health
    if health == 200:
        home, _ = _get("/")
        rep["home"] = home
        status_code, body = _get("/api/__skeleton/status")
        try:
            parsed = json.loads(body) if status_code == 200 else None
        except Exception:
            parsed = None
        rep["status"] = parsed
        rep["routes"] = parsed.get("routes") if parsed else None
        rep["ok"] = rep["home"] == 200
    else:
        rep["error"] = f"health={health}（{deadline_s:.0f}s 内未就绪或进程已退出）"
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    if not rep["ok"]:
        try:
            out = proc.stdout.read().decode("utf-8", errors="replace")
            rep["log_tail"] = out[-1200:]
        except Exception:
            pass
    return rep


def layer_smoke(code_dir: Path, plans: list, layer_no: int,
                sessions_dir: Path | None = None,
                last_routes: int | None = None) -> dict:
    """层收尾冒烟：重新装配（吃进新完成模块）+ 起服探活 + 留痕。

    路由数较上层只增不减是健康信号；回退 = 新层破坏了既有挂载，
    红字当场显形（修复路由决策见 pipeline 调用侧）。
    """
    summary = build_skeleton(Path(code_dir), plans)
    rep = smoke_skeleton(Path(code_dir))
    rep["layer"] = layer_no
    rep["framework"] = summary.get("framework")
    rep["blueprints"] = summary.get("blueprints")
    rep["bp_coverage"] = summary.get("bp_coverage")
    rep["routes_delta"] = (
        None if last_routes is None or rep.get("routes") is None
        else rep["routes"] - last_routes)
    if sessions_dir is not None:
        line = (
            f"- 层{layer_no}: ok={rep['ok']} health={rep['health']} "
            f"home={rep['home']} routes={rep['routes']}"
            f"（Δ{rep['routes_delta']}） "
            f"framework={rep['framework']} bp={rep['blueprints']}\n")
        try:
            sessions_dir = Path(sessions_dir)
            sessions_dir.mkdir(parents=True, exist_ok=True)
            with open(sessions_dir / SKELETON_LOG, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass  # 留痕失败不阻塞主流程
    return rep
