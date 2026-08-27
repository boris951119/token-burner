"""系统入口 CLI（规格文档 10.1 节交互流程、17 章第四阶段）。

交互流程：
需求输入 → 评估显示 → [编程] 模型选择（三模型逗号分隔）→
模式选择（默认安全审阅）→ 讨论与开发过程展示 → spec 确认 →
交付物汇总（含手动运行指引）。

交互层不含流程逻辑：全部编排经 Pipeline 完成（便于测试与 Web 复用）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.config import Settings
from app.execution.safe_executor import SafeExecutor
from app.pipeline import Pipeline
from app.tools.file_manager import FileManager
from app.utils.model_client import ModelClient

BANNER = """
========================================
  Token 消耗器 · AI 多智能体项目团队系统
  （MVP：安全审阅模式）
========================================
"""


def main() -> None:
    print(BANNER)
    settings = Settings()

    projects_root = Path.cwd() / "projects"
    file_manager = FileManager(projects_root=projects_root)
    llm = ModelClient(settings)
    executor = SafeExecutor()

    pipeline = Pipeline(
        llm=llm, executor=executor, settings=settings, file_manager=file_manager
    )

    requirement = input("你好，我是 Jarvis，请描述你的需求：\n> ").strip()
    if not requirement:
        print("需求为空，退出。")
        return

    print("\n评估中...")
    # 先路由，展示评估结果；needs_confirm 时就地确认（15.3）
    from app.orchestrator import Route, TaskRouter

    router = TaskRouter(llm, settings.models[0], settings)
    route = router.route(requirement)

    print(
        f"\n[评估结果] 类型: {route.task_type} | 难度: "
        f"{route.difficulty_score}（{route.difficulty_level}）"
    )
    if route.rechecked:
        print("（边界护栏复核已触发）")
    print(f"理由: {route.reason}")

    confirmed = None
    if route.needs_user_confirm:
        reply = input(
            "\n评估不确定，已保守视作编程任务。确认按编程处理？(y/n)\n> "
        ).strip().lower()
        confirmed = reply in ("y", "yes", "是", "确认")

    if route.route is Route.TEAM_FLOW and not (
        route.needs_user_confirm and confirmed is False
    ):
        # 10.1：模型选择与模式选择
        models = _select_models(settings)
        mode = _select_mode()
        auto_confirmed = False
        if mode == "auto":
            print("\n[警示] 自动验证模式预算为标准预算 ×"
                  f"{settings.auto_mode_budget_multiplier}，"
                  f"当前任务预算 {settings.task_token_budget('auto')} token。")
            reply = input("确认使用自动模式？(y/n)\n> ").strip().lower()
            auto_confirmed = reply in ("y", "yes", "是", "确认")
            if not auto_confirmed:
                mode = "safe"
                print("已回退安全审阅模式。")
        spec_confirm = input(
            "\n方案讨论与 spec 生成后将请求确认。预设回复（直接回车=确认）:\n> "
        ).strip() or "确认"

        print("\n开始团队流程（讨论 → spec → 拆分 → 开发循环）...\n")
        result = pipeline.run(
            requirement,
            confirmed_as_coding=confirmed,
            models=models,
            mode=mode,
            auto_mode_confirmed=auto_confirmed,
            spec_confirm=spec_confirm,
        )
    else:
        result = pipeline.run(requirement, confirmed_as_coding=confirmed)

    _print_result(result)


def _select_models(settings: Settings) -> tuple[str, str, str]:
    """10.1：主 LLM / 开发副 / 测试副三模型选择（逗号分隔）。"""
    print(f"\n可用模型: {', '.join(settings.models)}")
    while True:
        raw = input("请选择模型（主, 开发副, 测试副；直接回车用默认三模型）:\n> ").strip()
        if not raw:
            return tuple(settings.models[:3])  # type: ignore[return-value]
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if len(parts) != 3:
            print("需要恰好 3 个模型（逗号分隔），请重试。")
            continue
        bad = [p for p in parts if p not in settings.models]
        if bad:
            print(f"不在预设列表: {', '.join(bad)}，请重试。")
            continue
        if len(set(parts)) != 3:
            print("三个模型必须互不相同，请重试。")
            continue
        return parts[0], parts[1], parts[2]


def _select_mode() -> str:
    print("\n执行模式: [1] 安全审阅模式（默认）  [2] 自动验证模式")
    choice = input("> ").strip()
    return "auto" if choice == "2" else "safe"


def _print_result(result) -> None:
    print("\n" + "=" * 40)
    if result.kind == "direct_answer":
        print("[直接回答]\n")
        print(result.answer)
    elif result.kind == "direct_code":
        print("[简单编程 · 单文件直出]\n")
        print(result.answer)
        print("\n（简单任务已节流，未组建团队——11.6 省 token 模式）")
    elif result.kind == "declined":
        print("任务未按编程处理（用户否认），流程结束。")
    elif result.kind == "needs_confirm":
        print("评估不确定，等待用户确认（本次会话未继续）。")
    elif result.kind == "team_flow":
        print(result.deliverable_summary)
        if result.cost_dashboard is not None:
            print()
            print(result.cost_dashboard.text_summary())
    print("=" * 40)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(1)
