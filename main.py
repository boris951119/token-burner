"""ArcBench 参赛入口（factory26）——平台 runner 以固定 CLI 启动本文件。

契约对齐官方 Blank Template（2026-09-08 从平台任务页下载核对）：
- 位置参数 requirement_path：需求目录（含 requirements.yaml），
  缺省取环境变量 ARCBENCH_TASK_DIR；
- --output-dir：输出工作区，缺省取 ARCBENCH_OUTPUT_DIR；
- --type：任务类型（web/cli/android），缺省取 ARCBENCH_TASK_TYPE；
- 模型环境由 runner 注入：OPENAI_API_KEY / OPENAI_BASE_URL / MODEL
  （OpenAI 兼容网关，单模型）。

管线全程 headless，进度经 ArcBenchBridge 上报平台（本地无 SDK 时
自动 no-op，桥接层已随 requirements.txt 的 ./arcbench-agent-runtime
路径依赖安装）。
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path

from app.arcbench_bridge import ArcBenchBridge
from app.arcbench_ingest import (
    load_fixture_hint,
    load_requirement_tree,
    render_requirement_text,
)
from app.config import load_settings
from app.execution.factory import build_executor
from app.pipeline import Pipeline
from app.tools.file_manager import FileManager
from app.utils.model_client import ModelClientFactory

# 交付型终点（可运行代码）；declined / budget_exceeded / needs_confirm 均视为失败
_SUCCESS_KINDS = frozenset({"team_flow", "direct_code"})


def _find_resumable_project(file_manager) -> str | None:
    """中断恢复：查找「有恢复快照且未完成」的项目（最新优先）。

    r4 取证：interruption.md 只在协作式 Ctrl+C 路径落盘，平台 runner
    超时硬杀进程时不存在——恢复判据放宽为 pipeline_state.json 存在
    且无 completed.json 完成标记；协作式中断的项目优先（标记更可信）。
    """
    root = file_manager.projects_root
    if not root.is_dir():
        return None
    sessions_of = lambda p: p / "sessions"  # noqa: E731
    candidates = [
        p for p in root.iterdir()
        if sessions_of(p).joinpath("pipeline_state.json").is_file()
        and not sessions_of(p).joinpath("completed.json").exists()
    ]
    if not candidates:
        return None
    interrupted_first = [
        p for p in candidates
        if sessions_of(p).joinpath("interruption.md").is_file()
    ] or candidates
    return max(interrupted_first, key=lambda p: p.stat().st_mtime).name


def _align_gateway_env() -> dict:
    """runner 注入 OPENAI_BASE_URL；litellm 的 openai/* 前缀读 OPENAI_API_BASE。

    另剥除代理环境变量：httpx（openai SDK 底层）默认 trust_env，会走
    HTTP_PROXY/HTTPS_PROXY——沙箱代理只放行包仓库时，网关连接必然
    Connection error（r2 平台彩排两次同因失败）。

    返回网关环境自诊断（掩码）。
    """
    base = os.environ.get("OPENAI_BASE_URL", "").strip()
    if base and not os.environ.get("OPENAI_API_BASE", "").strip():
        os.environ["OPENAI_API_BASE"] = base
    if base:
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                    "http_proxy", "https_proxy", "all_proxy"):
            os.environ.pop(var, None)
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("MODEL", "").strip()
    return {
        "base": base or "(未注入)",
        "key": f"{key[:6]}…({len(key)}字符)" if key else "(未注入)",
        "model": model or "(未注入)",
    }


def _gateway_preflight(settings) -> None:
    """网关连通性预检：最小用例，失败即带精确原因快速失败。

    用降配副本（1 次重试 + 15s 超时）——默认 6 次重试 × 15s 退避会让
    一次失败拖十几分钟才暴露（快速诊断的要求正好相反）。
    """
    import dataclasses

    from app.utils.model_client import ModelClient

    fast = dataclasses.replace(
        settings, llm_max_retries=1, llm_timeout_seconds=15
    ) if dataclasses.is_dataclass(settings) else settings
    mc = ModelClient(fast)
    model = tuple(settings.models[:3])[0]
    mc.chat(model, [{"role": "user", "content": "ping"}])
    print("[gateway] preflight OK", flush=True)


_KNOWN_RELAY_FALLBACKS = ("openai/minimax-m3", "openai/glm-5.3")


def _apply_runner_model(settings) -> None:
    """平台 runner 注入 MODEL（OpenAI 兼容网关，litellm 需 openai/ 前缀）。

    缺省：单模型模式（settings.models=[m] + single_model_mode），
    三角色同模由管线 _model_triplet 补位。
    config `platform_multi_model=true`（r6 探测：网关为多模型中转，
    单 key 11 模型全通可并发）：注入模型任主 LLM，开发/测试副 LLM
    取 config 预设中与其互异的前两个；预设不足或全同自然回落单模型。

    generation-5 取证（官方容器 CWD≠提交目录 → config.json 可能不
    生效 → 编制退化为注入单模型、备胎链为空 → 任何一次网关超时
    崩穿）：官方中转站上编制不足三模型时，用已知可用编队自动补全
    ——备胎链的存在不再依赖 config.json 是否存活。
    """
    model = os.environ.get("MODEL", "").strip()
    if not model:
        return
    litellm_name = model if model.startswith("openai/") else f"openai/{model}"
    if getattr(settings, "platform_multi_model", False):
        preset = [m for m in settings.models if m != litellm_name]
        settings.models = [litellm_name] + preset[:2]
        settings.single_model_mode = len(set(settings.models)) < 3
    else:
        settings.models = [litellm_name]
        # TeamBuilder 互异校验放行（三角色同模）；预设列表校验仍生效
        settings.single_model_mode = True
    # 官方中转站编制补全：仅当注入端点确为 arc-bench 中转站且编制
    # 不足三模型（config.json 未生效等）时启用
    base = (os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("OPENAI_API_BASE") or "")
    if ("arc-bench.com" in base and settings.single_model_mode
            and len(settings.models) < 3):
        for fb in _KNOWN_RELAY_FALLBACKS:
            if fb != litellm_name and fb not in settings.models \
                    and len(settings.models) < 3:
                settings.models.append(fb)
        settings.single_model_mode = len(set(settings.models)) < 3
        print(f"[config] 单模型编制自动补全 → {list(settings.models)}",
              flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="token-burner-arcbench",
        description="token-burner：requirements.yaml → 可运行 Web 应用",
    )
    parser.add_argument(
        "requirement_path",
        nargs="?",
        default=os.environ.get("ARCBENCH_TASK_DIR", "requirements"),
        help="需求目录（含 requirements.yaml）",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=os.environ.get("ARCBENCH_OUTPUT_DIR", "."),
        help="输出工作区（缺省 ARCBENCH_OUTPUT_DIR）",
    )
    parser.add_argument(
        "--type",
        dest="task_type",
        default=os.environ.get("ARCBENCH_TASK_TYPE", "web"),
        help="任务类型（web/cli/android）；当前仅实现 web",
    )
    parser.add_argument(
        "--mode",
        choices=("safe", "auto"),
        default="auto",
        help="执行模式；平台提交固定 auto（真实执行，交付须可运行验收）",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="恢复 workdir 下最近的中断项目（sessions/pipeline_state.json）",
    )
    args = parser.parse_args(argv)

    req_dir = Path(args.requirement_path)
    fixture_warning = ""
    requirement_brief = None
    if req_dir.is_dir():
        tree, _ = load_requirement_tree(req_dir)
        fixture_hint = load_fixture_hint(req_dir)
        if not fixture_hint:
            # r4 取证：夹具放错层级会静默丢种子契约（搜索/种子漂移根因），
            # 探测三布局仍无 → 显式告警进诊断事件，不许无声失败
            fixture_warning = (
                "; [fixture] tests/helpers.ts 未找到（三布局探测均落空）——"
                "种子字符串契约缺失，生成数据易与评测断言漂移"
            )
        requirement = render_requirement_text(tree, fixture_hint=fixture_hint)
        # 规模工程（keep1 取证：32 需求全量文本令讨论超墙钟）：
        # 讨论阶段吃 FOLDER 摘要（26% 体量），拆分/开发阶段吃全文
        from app.arcbench_ingest import render_folder_summary

        requirement_brief = render_folder_summary(tree)
        # 视觉转写通道（初赛裁决：参考截图会提供）：需求树内嵌
        # reference/*.png 时用视觉模型转写为结构化描述并注入——
        # 主力模型拒图（r17 探测 glm-5.3 HTTP 400），管线保持纯文本。
        # 摘要与全文都注入（缓存命中，不重复计费）。
        from app.utils.vision import enrich_requirement

        vkey = os.environ.get("OPENAI_API_KEY", "")
        vbase = (os.environ.get("OPENAI_BASE_URL")
                 or os.environ.get("OPENAI_API_BASE", ""))
        requirement = enrich_requirement(
            requirement, req_dir, tree, key=vkey, base=vbase)
        requirement_brief = enrich_requirement(
            requirement_brief, req_dir, tree, key=vkey, base=vbase)
    else:
        tree = None
        # 非目录输入：文本文件或内联需求文本（本地调试用）
        requirement = (
            req_path.read_text(encoding="utf-8")
            if (req_path := Path(args.requirement_path)).is_file()
            else args.requirement_path
        )

    workdir = Path(args.output_dir).resolve()
    # 桥接层 SDK 以 ARCBENCH_OUTPUT_DIR 定位 workspace（.arc/ 事件流与
    # traceability 落点）；runner 只传 --output-dir 时兜底对齐，事件不落错目录
    os.environ.setdefault("ARCBENCH_OUTPUT_DIR", str(workdir))
    # r10 取证：stdout 重定向到文件时全程打印滞留缓冲，进程终局后日志
    # 只剩两行——平台排障与本地复盘都依赖 stdout，行缓冲必须打开
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(line_buffering=True)
        except Exception:
            pass
    diag = _align_gateway_env()
    # 配置三重锚定（generation-5 取证：平台 CWD≠提交目录，CWD/config.json
    # 找不到 → 静默回退默认值 → 单模型无备胎 → 四连败同源）：config 跟随
    # 提交包，与 CWD 解耦
    config_file = Path(__file__).resolve().parent / "config.json"
    settings = load_settings(config_file=config_file)
    _apply_runner_model(settings)
    # 诊断实证：配置实况打印进容器 stdout——平台侧故障的第一手证据
    print(f"[config] file={config_file} exists={config_file.is_file()} "
          f"models={list(settings.models)} "
          f"multi={settings.platform_multi_model} "
          f"single={settings.single_model_mode} "
          f"wall_clock={settings.llm_wall_clock_seconds} "
          f"budget={settings.max_task_tokens}", flush=True)
    # 网关长挂防御：单请求实测可挂 25 分钟+（httpx read timeout 是字节
    # 间隙口径，滴字续命永不触发）；墙钟 600s 超时走退避重试
    if settings.llm_wall_clock_seconds <= 0:
        settings.llm_wall_clock_seconds = 600
    # 平台侧提交统一走 runtime.git（桥接层），双 git 会互相污染提交历史
    settings.enable_git = False
    print(f"[config] 最终编制: models={list(settings.models)} "
          f"multi={settings.platform_multi_model} "
          f"single={settings.single_model_mode} "
          f"wall_clock={settings.llm_wall_clock_seconds} "
          f"budget={settings.max_task_tokens}", flush=True)

    # 看门狗线程（keep5 取证：进程楔死在墙钟保护之外 7.7h 零取证）——
    # 全局进度时间戳超阈值 → 全线程栈 dump 落盘 → 非零退出。
    # 阈值需覆盖合法长窗口（1200s 墙钟 × 3 重试 × 3 模型 ≈ 3h），故默认 200 分钟。
    _watchdog_min = float(os.environ.get("WATCHDOG_MINUTES", "200") or 0)
    if _watchdog_min > 0:
        import time as _time
        import traceback as _tb
        from app import pipeline as _pl

        def _watchdog():
            while True:
                _time.sleep(60)
                idle = _time.time() - _pl.LAST_PROGRESS
                if idle <= _watchdog_min * 60:
                    continue
                dump_path = (Path(os.environ.get("ARCBENCH_OUTPUT_DIR",
                             str(workdir))) / "logs" / "watchdog_dump.txt")
                try:
                    dump_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(dump_path, "w", encoding="utf-8") as fh:
                        fh.write(f"watchdog: no progress {idle/60:.0f} min\n")
                        for tid, frame in sys._current_frames().items():
                            fh.write(f"\n--- thread {tid} ---\n")
                            fh.write("".join(_tb.format_stack(frame)))
                except Exception:
                    pass
                print(f"[watchdog] {idle/60:.0f} 分钟无进展，楔死强制退出"
                      f"（现场: {dump_path}）", flush=True)
                os._exit(75)

        threading.Thread(target=_watchdog, daemon=True).start()
        print(f"[watchdog] 已启动（阈值 {_watchdog_min:.0f} 分钟）", flush=True)

    bridge = ArcBenchBridge()
    # 诊断信息走 SDK 事件流（runner_event_lines 可见；stdout 采集不全）
    bridge.run_started(
        f"[gateway] base={diag['base']} key={diag['key']} model={diag['model']}"
        f"{fixture_warning}"
    )
    _gateway_preflight(settings)
    pipeline = Pipeline(
        llm=None,
        llm_factory=ModelClientFactory(settings),
        settings=settings,
        file_manager=FileManager(projects_root=workdir / "projects"),
        executor=build_executor(args.mode, settings),
        on_event=bridge.handle,
    )
    try:
        if tree is not None:
            bridge.store_tree(tree)
        if args.resume:
            project_id = _find_resumable_project(pipeline.file_manager)
            if project_id is None:
                raise RuntimeError(
                    f"{workdir / 'projects'} 下没有可恢复的中断项目"
                )
            result = pipeline.resume(project_id)
        else:
            result = pipeline.run(
                requirement,
                # 不传 models 时管线会退到硬编码默认三模型（无对应密钥），
                # headless 必须显式传配置里的模型
                models=tuple(settings.models[:3]),
                mode=args.mode,
                auto_mode_confirmed=True,
                spec_confirm="确认",
                project_dirname="arcbench-app",
                requirement_brief=requirement_brief,
            )
    except Exception as exc:  # 平台需要明确的失败终态
        import traceback

        traceback.print_exc()  # 平台侧也需可追溯；本地调试靠 stderr
        # stdout 重定向丢失时仍有现场（keep7 取证：traceback 只进
        # stderr 曾导致尸检无崩溃证据）
        try:
            crash = Path(workdir) / "logs" / "crash.txt"
            crash.parent.mkdir(parents=True, exist_ok=True)
            crash.write_text(
                traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        bridge.run_failed(f"管线异常: {exc}")
        return 1

    if result.kind in _SUCCESS_KINDS:
        # 不变量：交付成功必须有完成标记（r10 取证：budget_exceeded 曾
        # 以退出码 0 上报——终态以落盘标记与退出码双重锚定，宁可误报
        # 失败不可假报成功）
        marker_ok = (
            result.project_dir is None
            or (Path(result.project_dir) / "sessions" / "completed.json").exists()
        )
        if not marker_ok:
            bridge.run_failed("管线报成功但 completed.json 缺失（终态矛盾）")
            return 1
        # 交付两段式验收（r2/r4 演练取证：逐模块门禁覆盖不了组装级缺陷；
        # 基础冒烟覆盖不了旅程级缺陷——评测方是 Playwright 走用户旅程）
        if result.project_dir is not None:
            from app.arcbench_smoke import verify_delivery

            ok, report = verify_delivery(
                result.project_dir, requirement, settings
            )
            print(f"[verify] {'PASS' if ok else 'FAIL'}", flush=True)
            print(f"[verify] {report[-600:]}", flush=True)
            if not ok:
                bridge.run_failed("交付验收未通过（见 verify 报告）")
                return 1
        bridge.run_completed(result.deliverable_summary or "交付完成")
        return 0
    bridge.run_failed(f"管线终点: {result.kind}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
