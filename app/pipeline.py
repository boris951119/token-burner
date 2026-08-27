"""端到端管线（规格文档 3.1 节主流程、10.1 节交互、15.3 保守降级）。

串联全部引擎：评估路由 → 组队 → 方案讨论 → spec 确认 →
模块拆分 → 接口契约 → 逐模块开发循环 → 交付物汇总。

职责边界：
- 决策全部走 LLM（评估、方案、spec、拆分、代码）；
- 校验与路由分发走程序（路由规则、模型互异、预算闸门、门禁）；
- 交互层（CLI，main.py）只做输入输出，不含流程逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.agents.dev_loop import DevLoopEngine, ModuleStatus
from app.agents.module_builder import ModuleBuilder
from app.config import Settings
from app.dashboard.cost_dashboard import CostDashboard
from app.execution.executor import Executor
from app.orchestrator import (
    DiscussionEngine,
    Route,
    RoutingResult,
    TaskRouter,
    TeamBuilder,
)
from app.tools.file_manager import FileManager
from app.tools.git_manager import GitManager
from app.utils.model_client import ModelClient


@dataclass
class PipelineResult:
    """管线执行结果（三种终点）。"""

    kind: str                          # direct_answer | direct_code | team_flow | needs_confirm | declined
    answer: str = ""                   # 直答/直出代码内容
    project_id: str | None = None
    project_dir: Path | None = None
    needs_user_confirm: bool = False
    deliverable_summary: str = ""
    frozen_modules: list[str] = field(default_factory=list)
    route: RoutingResult | None = None
    cost_dashboard: object | None = None  # CostDashboard（8.5 成本统计）


class Pipeline:
    """完整任务管线（交互无关，便于测试与未来 Web 层复用）。"""

    def __init__(
        self,
        llm: ModelClient,
        executor: Executor,
        settings: Settings,
        file_manager: FileManager,
        git_manager_factory=None,
    ):
        self.llm = llm
        self.executor = executor
        self.settings = settings
        self.file_manager = file_manager
        self._git_factory = git_manager_factory or GitManager

    def _git(self):
        """14 章：git 开启时提供管理器，关闭时返回 None。"""
        if not getattr(self.settings, "enable_git", False):
            return None
        return self._git_factory()

    def run(
        self,
        requirement: str,
        confirmed_as_coding: bool | None = None,
        models: tuple[str, str, str] | None = None,
        mode: str = "safe",
        auto_mode_confirmed: bool = False,
        spec_confirm: str = "确认",
        user_feedback: str = "",
    ) -> PipelineResult:
        """执行完整管线。交互参数由外层（CLI）收集后传入。"""
        router = TaskRouter(self.llm, self.settings.models[0], self.settings)
        route = router.route(requirement)

        # 15.3 保守降级：解析失败 → 视作编程 + 用户确认
        if route.needs_user_confirm:
            if confirmed_as_coding is None:
                return PipelineResult(
                    kind="needs_confirm", needs_user_confirm=True, route=route
                )
            if not confirmed_as_coding:
                return PipelineResult(kind="declined", route=route)

        # 3.2 路由分发
        if route.route is Route.DIRECT_OUTPUT:
            answer = self.llm.chat(
                self.settings.models[0],
                [
                    {"role": "system", "content": "你是助理，直接回答用户问题，简洁准确。"},
                    {"role": "user", "content": requirement},
                ],
            ).content
            return PipelineResult(kind="direct_answer", answer=answer, route=route)

        if route.route is Route.DIRECT_SIMPLE_CODING:
            answer = self.llm.chat(
                self.settings.models[0],
                [
                    {"role": "system",
                     "content": "你是工程师，直接给出单文件 Python 代码，仅输出代码。"},
                    {"role": "user", "content": requirement},
                ],
            ).content
            return PipelineResult(kind="direct_code", answer=answer, route=route)

        # TEAM_FLOW：组队（3.3 / 11.0）
        if models is None:
            models = ("gpt-4o", "deepseek-chat", "claude-3-5-sonnet")
        team = TeamBuilder(self.file_manager, self.settings).build(
            requirement=requirement,
            main_model=models[0],
            dev_model=models[1],
            test_model=models[2],
            mode=mode,
            auto_mode_confirmed=auto_mode_confirmed,
        )

        # 方案讨论（3.4 / 11.1 / 11.3 / 11.5）
        discussion = DiscussionEngine(
            llm=self.llm,
            main_model=team.main_model,
            dev_model=team.dev_model,
            test_model=team.test_model,
            settings=self.settings,
            file_manager=self.file_manager,
            project_id=team.project_id,
        )
        outcome = discussion.run_discussion(requirement, team.project_id)
        confirm = discussion.confirm_spec(outcome, spec_confirm)
        final_spec = confirm.spec_md

        # 14 章：git init + spec 确认后阶段提交
        git = self._git()
        project_root = self.file_manager.get_project(team.project_id).root
        if git is not None:
            git.init(project_root)
            git.commit_stage(project_root, "spec", "spec 确认，方案定稿")

        # 模块拆分 + 接口契约（3.5 / 12.1 / 12.2）
        builder = ModuleBuilder(
            llm=self.llm, main_model=team.main_model,
            settings=self.settings, file_manager=self.file_manager,
        )
        plans = builder.split_spec(final_spec, project_id=team.project_id)
        interfaces = builder.generate_interfaces(plans, project_id=team.project_id)
        order = builder.build_order(plans)

        # 逐模块开发循环（3.5 / 3.7 / 11.4）
        dev_loop = DevLoopEngine(
            llm=self.llm,
            dev_model=team.dev_model,
            test_model=team.test_model,
            executor=self.executor,
            settings=self.settings,
            file_manager=self.file_manager,
        )
        module_results = {}
        for name in order:
            plan = next(p for p in plans if p.name == name)
            module_results[name] = dev_loop.run_module(
                name,
                project_id=team.project_id,
                responsibility=plan.responsibility,
                contract=interfaces.get(name),
                project_modules=set(order),
                user_feedback=user_feedback,
            )
            # 14 章：每模块完成后阶段提交（含冻结模块——保留现场）
            if git is not None:
                status = "完成" if module_results[name].status is ModuleStatus.SUCCESS else "冻结"
                git.commit_stage(
                    project_root, f"module:{name}",
                    f"模块 {name} {status}（修复 {module_results[name].fix_attempts} 次）",
                )

        # 交付物汇总（10.1 尾段）
        summary = self._deliverable_summary(team, module_results, mode)
        # 8.5 成本统计：从 call_log 构建仪表盘并落盘 logs/
        dashboard = None
        if hasattr(self.llm, "call_log"):
            dashboard = CostDashboard.from_call_log(
                self.llm.call_log,
                budget_tokens=self.settings.task_token_budget(mode),
            )
            handle = self.file_manager.get_project(team.project_id)
            if handle is not None:
                dashboard.persist(handle.root / "logs")
        # 14 章：集成（交付汇总 + 成本报告）后最终提交
        if git is not None:
            git.commit_stage(project_root, "integration", "集成完成，交付物汇总")
        return PipelineResult(
            kind="team_flow",
            project_id=team.project_id,
            project_dir=self.file_manager.get_project(team.project_id).root,
            deliverable_summary=summary,
            frozen_modules=[
                n for n, r in module_results.items() if r.status is ModuleStatus.FROZEN
            ],
            route=route,
            cost_dashboard=dashboard,
        )

    # ------------------------------------------------------------------

    def _deliverable_summary(
        self, team, module_results: dict, mode: str
    ) -> str:
        """交付物汇总：目录、模块清单、状态、运行指引（10.1）。"""
        root = self.file_manager.get_project(team.project_id).root
        lines = [
            "========== 交付物汇总 ==========",
            f"项目目录: {root}",
            f"执行模式: {'安全审阅（手动运行）' if mode == 'safe' else '自动验证'}",
            "",
            "模块清单:",
        ]
        for name, result in module_results.items():
            status = "完成" if result.status is ModuleStatus.SUCCESS else "冻结（修复上限）"
            fix = f"，修复 {result.fix_attempts} 次" if result.fix_attempts else ""
            lines.append(f"  - {name}: {status}{fix}")
        lines += [
            "",
            "文件结构: spec.md / modules/ / interfaces.json / code/ / tests/ / changelog/（验证与修复记录）",
        ]
        if mode == "safe":
            lines += [
                "",
                "手动运行指引:",
                f"  cd {root / 'code' / name if module_results else root}",
                f"  python {name}.py    # 逐模块运行（文件与模块同名，可同进程导入）",
                "  python -m pytest tests/<模块>/ -v",
                "  运行后请将结果反馈给系统以继续修复循环（如需要）。",
            ]
        frozen = [n for n, r in module_results.items() if r.status is ModuleStatus.FROZEN]
        if frozen:
            lines += [
                "",
                "已知问题（11.4 修复上限，交用户决定）:",
                f"  冻结模块: {', '.join(frozen)}",
                "  详见 changelog/<模块>/fix_history.md 与 validation.md",
            ]
        return "\n".join(lines)
