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


def _apply_runner_model(settings) -> None:
    """平台 runner 注入 MODEL（OpenAI 兼容网关，litellm 需 openai/ 前缀）。

    缺省：单模型模式（settings.models=[m] + single_model_mode），
    三角色同模由管线 _model_triplet 补位。
    config `platform_multi_model=true`（r6 探测：网关为多模型中转，
    单 key 11 模型全通可并发）：注入模型任主 LLM，开发/测试副 LLM
    取 config 预设中与其互异的前两个；预设不足或全同自然回落单模型。
    """
    model = os.environ.get("MODEL", "").strip()
    if not model:
        return
    litellm_name = model if model.startswith("openai/") else f"openai/{model}"
    if getattr(settings, "platform_multi_model", False):
        preset = [m for m in settings.models if m != litellm_name]
        settings.models = [litellm_name] + preset[:2]
        settings.single_model_mode = len(set(settings.models)) < 3
        return
    settings.models = [litellm_name]
    # TeamBuilder 互异校验放行（三角色同模）；预设列表校验仍生效
    settings.single_model_mode = True


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
    diag = _align_gateway_env()
    settings = load_settings()
    _apply_runner_model(settings)
    # 网关长挂防御：单请求实测可挂 25 分钟+（httpx read timeout 是字节
    # 间隙口径，滴字续命永不触发）；墙钟 600s 超时走退避重试
    if settings.llm_wall_clock_seconds <= 0:
        settings.llm_wall_clock_seconds = 600
    # 平台侧提交统一走 runtime.git（桥接层），双 git 会互相污染提交历史
    settings.enable_git = False

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
            )
    except Exception as exc:  # 平台需要明确的失败终态
        import traceback

        traceback.print_exc()  # 平台侧也需可追溯；本地调试靠 stderr
        bridge.run_failed(f"管线异常: {exc}")
        return 1

    if result.kind in _SUCCESS_KINDS:
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
