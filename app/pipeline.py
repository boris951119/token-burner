"""端到端管线（规格文档 3.1 节主流程、10.1 节交互、15.3 保守降级）。

串联全部引擎：评估路由 → 组队 → 方案讨论 → spec 确认 →
模块拆分 → 接口契约 → 逐模块开发循环 → 交付物汇总。

职责边界：
- 决策全部走 LLM（评估、方案、spec、拆分、代码）；
- 校验与路由分发走程序（路由规则、模型互异、预算闸门、门禁）；
- 交互层（CLI，main.py）只做输入输出，不含流程逻辑。
"""

from __future__ import annotations

import threading
import time

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.agents.dev_loop import (
    DevLoopEngine,
    ModelChainExhausted,
    ModuleStatus,
)
from app.agents.module_builder import ModuleBuilder, SplitError, should_modularize
from app.agents.researcher import (
    ResearchCache,
    Researcher,
    should_research,
)
from app.agents.web_research import fetch_web_material
from app.utils.shared_check import find_shared_dependents
from app.config import Settings
from app.dashboard.cost_dashboard import CostDashboard
from app.execution.executor import Executor
from app.orchestrator import (
    DiscussionEngine,
    Route,
    RoutingResult,
    TaskRouter,
    TeamBuilder,
    assessment_model,
    route_models,
    tier_map,
)
from app.tools.file_manager import FileManager
from app.tools.git_manager import GitManager
from app.utils.budget import (
    BudgetExceededError,
    BudgetGuard,
    TaskCancelledError,
    TaskDeadlineError,
)

# 看门狗数据源：全局最近进度时间戳（keep5 取证：进程可楔死在墙钟
# 保护之外的子进程/库内部，心跳冻结数小时无法取证——由 main.py 的
# 看门狗线程消费；Pipeline._emit 每个事件都会刷新它）
LAST_PROGRESS = time.time()


def touch_progress() -> None:
    """刷新全局最近进度时间戳（看门狗阈值判断依据）。"""
    global LAST_PROGRESS
    LAST_PROGRESS = time.time()


from app.utils.model_client import ModelClient, _is_timeout, _is_transient, leg_chain
from app.utils.untrusted import sanitize_untrusted


def _sum_tokens(entries: list[dict]) -> int:
    """从调用日志条目累计 token 用量（11.0：input + output）。"""
    return sum(
        int(e.get("input_tokens", 0)) + int(e.get("output_tokens", 0))
        for e in entries
    )


def _model_triplet(models) -> tuple[str, str, str]:
    """三角色模型解析；不足 3 个时同模补位。

    ARC-Bench 平台按单模型下发（MODEL 环境变量），headless 传入 1 元组
    属合法形态（互异校验是 web 层规格 3.3 的职责，管线不重复设卡）。
    """
    models = tuple(models) or ("gpt-4o", "deepseek-chat", "claude-3-5-sonnet")
    return (
        models[0],
        models[1] if len(models) > 1 else models[0],
        models[2] if len(models) > 2 else models[0],
    )


@dataclass
class PipelineResult:
    """管线执行结果（终点类型）。"""

    kind: str                          # direct_answer | direct_code | team_flow | needs_confirm | declined | budget_exceeded
    answer: str = ""                   # 直答/直出代码内容
    project_id: str | None = None
    project_dir: Path | None = None
    needs_user_confirm: bool = False
    deliverable_summary: str = ""
    frozen_modules: list[str] = field(default_factory=list)
    pending_modules: list[str] = field(default_factory=list)  # 11.0 预算中止时的未完成清单
    route: RoutingResult | None = None
    cost_dashboard: object | None = None  # CostDashboard（8.5 成本统计）
    declined_reply: str = ""  # M9-3：快判拒答的友好文案（仅闲聊/无意义出口填充）
    # M10-2 条件③：修复失败 ≥2 轮的模块 → 建议 Researcher 调研
    #（仅建议，不自动激活——4.5「由用户确认后激活」，总则 D.1）
    research_suggestions: list[str] = field(default_factory=list)


# M9-3：declined 友好文案（确定性程序职责，不调 LLM——拒答本身就是为了省
# token）。按快判 intent 取文案；未知类型走默认兜底。固定文案不拼需求原文，
# 规避不可信文本进入 UI 的转义问题。
DECLINED_REPLIES = {
    "闲聊": "这里是 Token 消耗器——把软件需求变成可运行代码的多智能体开发系统。"
            "闲聊模式暂不开放～想开发一个软件、写个小工具或分析一份资料，"
            "直接告诉我你的需求即可。",
    "无意义": "未能识别出有效的软件需求。请描述你想开发的内容"
              "（例如：写一个记账脚本、做一个数据看板），我会为你组建智能体团队完成它。",
}
_DECLINED_DEFAULT_REPLY = "该输入未进入开发流程。请描述明确的软件需求。"


class Pipeline:
    """完整任务管线（交互无关，便于测试与未来 Web 层复用）。"""

    def __init__(
        self,
        llm: ModelClient | None,
        executor: Executor,
        settings: Settings,
        file_manager: FileManager,
        git_manager_factory=None,
        llm_factory=None,
        on_event: Callable[[str, dict], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ):
        # M8-1：llm 与 llm_factory 二选一——
        # - 直传 llm：单任务模式（CLI / 测试注入），原样使用；
        # - llm_factory：每任务经 create() 新建实例（budget_guard /
        #   call_log 天然隔离），run/resume 开始时解析（见 _resolve_llm）。
        if llm is None and llm_factory is None:
            raise ValueError("llm 与 llm_factory 至少提供一个（M8-1）")
        self.llm = llm
        self._llm_factory = llm_factory
        # M8-4：任务进度事件回调（kind, data）——异步任务的进度源，
        # 未挂接零开销；回调失败不影响任务本身
        self._on_event = on_event
        # M12-1：协作式取消旗标检查（复用 BudgetGuard 检查点，见 run/resume）
        self._cancel_check = cancel_check
        self.executor = executor
        self.settings = settings
        self.file_manager = file_manager
        self._git_factory = git_manager_factory or GitManager
        # 11.0 任务级基线：看板只统计本任务切片（跨任务不污染，问题 7）
        self._task_baseline = 0
        # v1.2 S0:并行模块开发下事件派发互斥(多 worker 同时 module_done)
        self._emit_lock = threading.Lock()
        # factory26 r4:headless 长跑可观测性（stdout 缓冲期间的黑盒诊断）
        self._heartbeat_root: Path | None = None
        self._heartbeat_stage = ""

    def _beat(self, event_type: str, data: dict) -> None:
        """心跳落盘 sessions/heartbeat.json（每次 LLM 调用/阶段变更都会刷新）。

        背景：headless 平台运行 stdout 全缓冲，单次调用可挂数分钟——
        有时间戳的心跳让「慢」与「死」一眼可辨。失败静默，不影响任务。
        """
        root = self._heartbeat_root
        if root is None:
            return
        try:
            import json as _json
            import time as _time

            if event_type == "stage":
                self._heartbeat_stage = str(data.get("stage") or "")
            payload = {
                "timestamp": _time.strftime("%Y-%m-%d %H:%M:%S"),
                "stage": self._heartbeat_stage,
                "last_event": event_type,
                "module": data.get("module") or "",
            }
            (root / "sessions" / "heartbeat.json").write_text(
                _json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass

    def _emit(self, event_type: str, **data) -> None:
        """M8-4：发进度事件（轻量钩子，不改编排逻辑）。

        v1.2 S0:并行开发下多 worker 同时发事件 → 派发互斥。
        """
        touch_progress()
        self._beat(event_type, data)
        with self._emit_lock:
            if self._on_event is None:
                return
            try:
                self._on_event(event_type, data)
            except Exception:
                pass  # 进度回调失败不影响任务

    def _resolve_models(
        self, route: RoutingResult, models: tuple[str, str, str] | None
    ) -> tuple[str, str, str]:
        """三模型解析（M3-2 评估后动态选模）。

        优先级：用户显式选择 > 智能路由（按难度分选档）> v0.3.1 缺省。
        路由关闭时行为与 v0.3.1 完全一致（回归保证）。
        """
        if models is not None:
            return models
        if self.settings.model_routing_enabled:
            return route_models(route.difficulty_score, self.settings)
        return ("gpt-4o", "deepseek-chat", "claude-3-5-sonnet")

    def _direct_chat(self, system: str, requirement: str) -> str:
        """直出路径的单次调用：一条腿瞬态故障就换下一条腿。

        批次#21 同族取证：直出是整条管线最便宜的出口，原先却最脆——团队
        流程有重试环与备胎链，直出一次网关超时就是异常直穿。缺密钥这类配置
        错误与预算/取消总闸不在此列，照旧直穿。
        """
        chain = leg_chain(None, self.settings.models)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": requirement},
        ]
        last: RuntimeError | None = None
        for model in chain:
            try:
                return self.llm.chat(model, messages).content
            except (BudgetExceededError, TaskCancelledError):
                raise
            except RuntimeError as exc:
                if not (_is_transient(exc) or _is_timeout(exc)):
                    raise
                last = exc
        # 链非空由 Settings 校验保证（models 非空且无空名）
        raise last  # type: ignore[misc]

    def _resolve_llm(self) -> ModelClient:
        """M8-1：任务开始时解析本任务的 ModelClient。

        约束：一个 Pipeline 实例同一时间只承载一个任务（server 每请求
        新建 Pipeline）；factory 存在则覆写 self.llm，后续编排代码
        （self.llm.*）零改动——只换「谁持有客户端」，不动管线逻辑。
        """
        if self._llm_factory is not None:
            self.llm = self._llm_factory.create()
        assert self.llm is not None
        # M8-4：每次 LLM 调用后回报 token 用量（经 on_call 钩子）
        if self._on_event is not None:
            def _on_call(entry: dict) -> None:
                self._emit(
                    "tokens",
                    tokens=int(entry.get("input_tokens", 0))
                    + int(entry.get("output_tokens", 0)),
                    model=entry.get("model", ""),
                )
            try:
                self.llm.on_call = _on_call
            except AttributeError:
                pass  # 测试桩无此属性时静默跳过
        return self.llm

    def _git(self):
        """14 章：git 开启时提供管理器，关闭时返回 None。"""
        if not getattr(self.settings, "enable_git", False):
            return None
        return self._git_factory()

    @staticmethod
    def _dependency_layers(order: list[str], interfaces: dict) -> list[list[str]]:
        """v1.2 S0:按契约依赖把拓扑序切分为可并行的层。

        order 为拓扑序;模块的层号 = 其全部依赖层号最大值 + 1。
        同层模块相互无依赖,可安全并发开发。
        """
        layer_of: dict[str, int] = {}
        layers: list[list[str]] = []
        for name in order:
            deps = [d for d in (interfaces.get(name) or {}).get("dependencies", [])
                    if d in layer_of]
            lvl = max((layer_of[d] for d in deps), default=-1) + 1
            layer_of[name] = lvl
            if lvl >= len(layers):
                layers.append([])
            layers[lvl].append(name)
        return layers

    def run(
        self,
        requirement: str,
        confirmed_as_coding: bool | None = None,
        models: tuple[str, str, str] | None = None,
        mode: str = "safe",
        auto_mode_confirmed: bool = False,
        spec_confirm: str = "确认",
        user_feedback: str = "",
        feedback_fn: Callable[[str], str] | None = None,
        route: RoutingResult | None = None,
        research: str = "off",
        research_material: str = "",
        budget_override: int | None = None,
        project_dirname: str | None = None,
        requirement_brief: str | None = None,
    ) -> PipelineResult:
        """执行完整管线。交互参数由外层（CLI）收集后传入。

        feedback_fn（3.8 反馈交互闭环）：prompt → 用户输入的回调，
        安全模式交付后循环征询手动运行反馈（成功确认 / 报错修复 /
        exit 手动停止），由 Pipeline 编排（交互层不含流程逻辑）。

        route：外部已完成的路由评估（如 CLI 展示用）→ 直接复用，
        避免二次评估浪费 token；缺省时内部自评估（兼容）。

        M10 Researcher（v0.5 Beta，researcher_enabled 缺省关闭）：
        research = "on"（用户显式要求调研）/ "auto"（评估 reason 命中
        陌生技术栈时自动触发）/ "off"（缺省，零行为变化）；
        research_material = 用户提供的资料文本（4.6 降级模式的输入）。

        M12-4：budget_override = 任务级预算覆盖（插件设置页透传；
        None/缺省 = team 档位预算，≤0 视为非法）。
        """
        # 11.0：基线——本任务开始前的调用日志长度（用量只计本任务）
        self._resolve_llm()  # M8-1：factory 模式下每任务新建客户端
        baseline = len(getattr(self.llm, "call_log", []))
        self._task_baseline = baseline  # 看板切片依据（问题 7）
        if route is None:
            # M9-5：评估/复核固定降档主力档（确定性选模，见 assessment_model）
            router = TaskRouter(
                self.llm, assessment_model(self.settings), self.settings
            )
            route = router.route(requirement)

        # 15.3 保守降级：解析失败 → 视作编程 + 用户确认
        if route.needs_user_confirm:
            if confirmed_as_coding is None:
                return PipelineResult(
                    kind="needs_confirm", needs_user_confirm=True, route=route
                )
            if not confirmed_as_coding:
                return PipelineResult(kind="declined", route=route)

        # M9-3：快判高置信闲聊/无意义 → declined 真实意图出口（附友好文案）
        if route.route is Route.DECLINED:
            return PipelineResult(
                kind="declined",
                route=route,
                declined_reply=DECLINED_REPLIES.get(
                    route.task_type, _DECLINED_DEFAULT_REPLY
                ),
            )

        # 3.2 路由分发
        if route.route is Route.DIRECT_OUTPUT:
            answer = self._direct_chat(
                "你是助理，直接回答用户问题，简洁准确。", requirement,
            )
            return PipelineResult(kind="direct_answer", answer=answer, route=route)

        if route.route is Route.DIRECT_SIMPLE_CODING:
            answer = self._direct_chat(
                "你是工程师，直接给出单文件 Python 代码，仅输出代码。", requirement,
            )
            return PipelineResult(kind="direct_code", answer=answer, route=route)

        # TEAM_FLOW：组队（3.3 / 11.0）
        models = self._resolve_models(route, models)
        main_model, dev_model, test_model = _model_triplet(models)
        team = TeamBuilder(self.file_manager, self.settings).build(
            requirement=requirement,
            main_model=main_model,
            dev_model=dev_model,
            test_model=test_model,
            project_dirname=project_dirname,
            mode=mode,
            auto_mode_confirmed=auto_mode_confirmed,
        )
        # 自动验证模式：绑定项目 code/ 目录（跨模块/_shared 依赖解析）
        self._bind_executor_project(team.project_id)
        # M8-4：项目目录就绪事件（异步任务据此落盘 task_state.json）
        _handle = self.file_manager.get_project(team.project_id)
        self._heartbeat_root = _handle.root if _handle is not None else None
        self._emit(
            "project", project_id=team.project_id,
            project_dir=str(_handle.root) if _handle is not None else "",
        )

        # 11.0 第 0 层总闸：按模式预算创建护栏并挂接到 LLM 客户端。
        # 评估等前置调用的用量计入本任务预算；任务结束（含异常）后卸载。
        # M12-4：任务级预算覆盖（插件设置页；None/缺省 = team 档位预算）
        if budget_override is not None and budget_override <= 0:
            raise ValueError(f"budget_override 必须为正整数，当前: {budget_override}")
        guard = BudgetGuard(
            budget_tokens=budget_override or team.budget_tokens,
            throttle_threshold=self.settings.budget_throttle_threshold,
            repair_reserve_ratio=getattr(
                self.settings, "budget_repair_reserve", 0.0),
        )
        # getattr 防护与 200/692 行同构：测试桩 LLM 无 call_log 时按 0 计
        guard.record(_sum_tokens(getattr(self.llm, "call_log", [])[baseline:]))
        setattr(self.llm, "budget_guard", guard)
        # 活动护栏登记（2026-09-20 平台双跑取证）：验证/修复通道的零散
        # ModelClient 不经工厂接线，曾整体绕过预算（7.0M/6.2M vs 2M 帽）；
        # 登记后零散客户端兜底接入同一把护栏。护栏需存活到管线之后的
        # verify/交付段（main.py 同进程续用），不做任务末卸载——下一任务
        # 创建护栏时按覆盖语义自然接替。
        from app.utils.budget import set_active_budget_guard

        set_active_budget_guard(guard)
        # M12-1：协作式取消检查点注入（ensure_allowed 每次调用前生效）
        if self._cancel_check is not None:
            guard.attach_cancel_check(self._cancel_check)

        stage = "方案讨论"
        stage_box: list[str] = [stage]  # 可变引用（_develop_and_deliver 内更新）
        self._emit("stage", stage=stage)  # M8-4
        module_results: dict = {}
        order: list[str] = []

        # M10 Researcher（4.1 可选前置角色）：触发判定 → 结构化摘要 →
        # 落盘留档与注入。失败方向单一：无资料 / 预算耗尽 / 校验不通过
        # / 意外异常 → 跳过研究（research_context 保持空串），任务继续。
        research_context = ""
        decision = should_research(
            requirement, route.reason, research, self.settings.researcher_enabled
        )
        if decision.triggered:
            try:
                self._emit("stage", stage="研究调研")
                cache = (
                    ResearchCache(
                        self.settings.research_cache_path,
                        ttl_days=self.settings.research_cache_ttl_days,
                    )
                    if self.settings.research_cache_enabled else None
                )
                researcher = Researcher(
                    self.llm, team.dev_model, self.settings,
                    # 4.4：独立预算（独立于任务总闸；研究调用同样被
                    # llm.call_log 记录 → 全局消耗日志天然覆盖）
                    budget_guard=BudgetGuard(
                        budget_tokens=self.settings.research_budget_tokens
                    ),
                    cache=cache,
                )
                # M10-5 联网调研（缺省关）：搜索结果增强资料；
                # 失败返回空串 → 回退用户资料注入模式（降级链路单一）
                if self.settings.researcher_web_enabled:
                    web_material = fetch_web_material(
                        decision.stack or requirement, self.settings
                    )
                    if web_material:
                        research_material = (
                            f"{research_material}\n\n{web_material}".strip()
                        )
                        self._emit("research_web",
                                   provider=self.settings.research_web_provider)
                    else:
                        self._emit("research_web_fallback")
                brief = researcher.generate_brief(
                    research_material, stack=decision.stack
                )
                if cache is not None:
                    cache.close()
                if brief is not None:
                    # 可审计：摘要落盘（resume 时重读注入，无需重新生成）
                    handle = self.file_manager.get_project(team.project_id)
                    if handle is not None:
                        (handle.root / "sessions" / "research_brief.md").write_text(
                            f"# Researcher 结构化摘要（{decision.source} 触发）\n\n"
                            + brief.render() + "\n",
                            encoding="utf-8",
                        )
                    # 4.3 注入 + M7-6 治理：摘要源于用户资料（不可信），
                    # 注入提示词前统一包裹数据边界
                    research_context = sanitize_untrusted(brief.render())
                    self._emit(
                        "research", source=decision.source,
                        stack=decision.stack,
                    )
                else:
                    self._emit(
                        "research_skipped", reason=researcher.last_error
                    )
            except TaskCancelledError:
                # 取消必上抛。BudgetExceededError 不在此列：这里的守卫吃得到
                # 两种来源——研究独立预算（4.4，设计上就该「跳过研究继续做」）
                # 与任务总闸（llm.chat 内部检查点），按类型区分不开，
                # 一律上抛会把「研究子预算花完」升级成整跑中止。
                raise
            except Exception as exc:  # 研究失败不阻塞任务（方向单一）
                self._emit(
                    "research_skipped",
                    reason=f"{type(exc).__name__}: {exc}",
                )

        try:
            # 6.3：评估结论落盘（可审计：分数/等级/类型/理由/预估文件数/路由）
            self._persist_assessment(team.project_id, route, models, mode)
            # 方案讨论（3.4 / 11.0 省token模式 / 11.1 / 11.3 / 11.5）
            discussion = DiscussionEngine(
                llm=self.llm,
                main_model=team.main_model,
                dev_model=team.dev_model,
                test_model=team.test_model,
                settings=self.settings,
                file_manager=self.file_manager,
                project_id=team.project_id,
                budget_guard=guard,
            )
            outcome = discussion.run_discussion(
                requirement_brief or requirement, team.project_id
            )
            confirm = discussion.confirm_spec(outcome, spec_confirm)
            final_spec = confirm.spec_md

            # 三刀②：收敛后零 LLM 对账 spec 点名 REQ vs 题面 ATOMIC 总数
            try:
                from app.utils.spec_req_audit import (
                    annotate_spec_with_missing, audit_spec_req_coverage,
                    persist_spec_req_report,
                )
                spec_req = audit_spec_req_coverage(requirement, final_spec)
                sessions = (
                    self.file_manager.get_project(team.project_id).root
                    / "sessions")
                persist_spec_req_report(spec_req, sessions)
                final_spec = annotate_spec_with_missing(final_spec, spec_req)
                print(
                    f"[spec↔REQ] {spec_req.ratio} 条已在 spec 点名"
                    + (f"（缺 {len(spec_req.missing)}）"
                       if spec_req.missing else ""),
                    flush=True,
                )
                self._emit(
                    "spec_req_coverage",
                    mentioned=len(spec_req.mentioned),
                    required=len(spec_req.required),
                    missing=list(spec_req.missing)[:20],
                )
            except Exception as exc:
                print(f"[spec↔REQ] 对账降级: {exc!r}"[:160], flush=True)

            # 14 章：git init + spec 确认后阶段提交
            git = self._git()
            project_root = self.file_manager.get_project(team.project_id).root
            if git is not None:
                git.init(project_root)
                git.commit_stage(project_root, "spec", "spec 确认，方案定稿")

            # 模块拆分 + 接口契约（3.5 / 12.1 / 12.2）
            stage_box[0] = "模块拆分与接口契约"
            self._emit("stage", stage=stage_box[0])  # M8-4
            builder = ModuleBuilder(
                llm=self.llm, main_model=team.main_model,
                settings=self.settings, file_manager=self.file_manager,
            )
            if should_modularize(
                route.difficulty_score, route.estimated_files, self.settings
            ) or route.fallback:
                # 12.2：难度 ≥5 或预估文件数 ≥6 → 模块化拆分
                # 规模工程：讨论吃 FOLDER 摘要，拆分补全量需求原文
                # （原子验收细节/场景/夹具契约在此回到拆分视野）
                # route.fallback（批次#24）：15.3 降级评估的分数与文件数都是
                # 占位 0，should_modularize 必然判假——需求形状未知时按大做
                # （多模块）比按小做（单模块吞整份 spec）更接近保守本意，
                # 与「保守视作编程任务」是同一条取舍。
                try:
                    plans = builder.split_spec(
                        final_spec, project_id=team.project_id,
                        requirement=requirement,
                    )
                    interfaces = builder.generate_interfaces(
                        plans, project_id=team.project_id
                    )
                except SplitError as exc:
                    # 重试到腿数/轮数上限＝LLM 输出仍不可用（网关半瘫或反复
                    # 解析失败）。原先 SplitError 直穿 run 的 except Exception
                    # → 落盘现场后 re-raise = 整跑 rc=1 零交付；退回 12.2 既有
                    # 的单模块直出（零额外调用）至少交出一份可跑的代码——
                    # 少几层模块清晰度，好过零分。
                    self._emit("split_fallback", error=f"{type(exc).__name__}: {exc}"[:200])
                    plans = [builder.single_module_plan(
                        final_spec, project_id=team.project_id
                    )]
                    interfaces = {}
            else:
                # 12.2：单份 spec 直出（跳过拆分与接口契约，省 LLM 调用）
                plans = [builder.single_module_plan(
                    final_spec, project_id=team.project_id
                )]
                interfaces = {}
            order = builder.build_order(plans)
            # P1-A：ATOMIC 覆盖闸——每条原子需求必须有主人；未覆盖则机械补挂
            # 进最像模块的职责（零 LLM）。不 raise、不改交付口径。
            coverage_report = None
            try:
                from app.utils.atomic_coverage import (
                    enforce_atomic_coverage, persist_coverage_report,
                )
                coverage_report = enforce_atomic_coverage(requirement, plans)
                # P0-1（评审发现）：normalize 可能追加 `*_p2` 溢出分册模块，
                # 而 order 在覆盖闸之前算好——分册若不重算进 order，永远不进
                # 开发循环：报告全绿、盘上无代码。覆盖闸后必须重算。
                order = builder.build_order(plans)
                # v53 刀C：所有权已唯一 → 按主人注入逐 REQ 验收清单
                # （废除 inject_ui_manifest 整表灌进单一 UI 模块）
                try:
                    from app.acceptance_compile import (
                        compile_checklists_from_text,
                    )
                    from app.utils.atomic_coverage import (
                        inject_contracts_by_ownership,
                    )
                    owner = dict(coverage_report.owned or {})
                    # owned 为空时退回补挂映射（骨架拆分）
                    for rid, mod in (coverage_report.assigned or {}).items():
                        owner.setdefault(rid, mod)
                    cks = compile_checklists_from_text(requirement)
                    injected = inject_contracts_by_ownership(
                        plans, cks, owner)
                    if injected:
                        print(
                            "[coverage] 契约按所有权注入: "
                            + ", ".join(
                                f"{m}×{n}" for m, n in
                                list(injected.items())[:12]),
                            flush=True,
                        )
                    # 刀J'：home/login 锚点 sidecar → 冒烟起服后 GET 对应路由
                    # v56：冒烟读 project/code/.surface_route_anchors.json；
                    # 旧写 backend/ 或项目根 → 闸永不触发（v55 双题尸检）。
                    try:
                        from app.utils.manifest_landing import (
                            write_surface_anchors_sidecar,
                        )
                        handle = self.file_manager.get_project(
                            team.project_id)
                        if handle is not None:
                            texts = [
                                getattr(p, "responsibility", "") or ""
                                for p in plans
                            ]
                            code_dest = handle.root / "code"
                            code_dest.mkdir(parents=True, exist_ok=True)
                            by_s = write_surface_anchors_sidecar(
                                code_dest, texts)
                            n = sum(len(v) for v in by_s.values())
                            keys = ",".join(by_s.keys()) or "-"
                            print(
                                f"[coverage] surface 锚点 sidecar "
                                f"{n} 条[{keys}] → code/",
                                flush=True,
                            )
                    except Exception as exc:
                        print(f"[coverage] surface sidecar 降级: {exc!r}",
                              flush=True)
                except Exception as exc:
                    print(f"[coverage] 契约所有权注入降级: {exc!r}",
                          flush=True)
                handle = self.file_manager.get_project(team.project_id)
                if handle is not None:
                    persist_coverage_report(handle.root, coverage_report)
                print(
                    f"[coverage] ATOMIC={len(coverage_report.required)} "
                    f"已认领={len(coverage_report.owned)} "
                    f"补挂={len(coverage_report.assigned)} "
                    f"仍缺={len(coverage_report.uncovered)} "
                    f"重复={len(coverage_report.duplicates)}",
                    flush=True,
                )
                self._emit(
                    "atomic_coverage",
                    required=len(coverage_report.required),
                    owned=dict(coverage_report.owned),
                    assigned=dict(coverage_report.assigned),
                    uncovered=list(coverage_report.uncovered)[:20],
                )
            except Exception as exc:
                print(f"[coverage] 覆盖闸降级: {exc!r}", flush=True)
            # P1-D：领域内核落盘 + 职责注解（只增不改）
            try:
                from app.utils.domain_kernels import (
                    annotate_plans_with_kernels, ensure_domain_kernels,
                )
                annotate_plans_with_kernels(plans, requirement)
                handle = self.file_manager.get_project(team.project_id)
                if handle is not None:
                    code_root = handle.root / "code"
                    code_root.mkdir(parents=True, exist_ok=True)
                    written = ensure_domain_kernels(code_root, requirement)
                    if written:
                        print(f"[domain-kernel] 已落盘: {', '.join(written)}",
                              flush=True)
            except Exception as exc:
                print(f"[domain-kernel] 降级: {exc!r}", flush=True)
            # 刀L（行走骨架）：契约冻结后、业务模块开发前，机械装配一个
            # 活着的应用骨架并起服冒烟——链路连通从交付段祈祷变成开发段
            # 不变量。骨架带 __arcbench_assembled__ 标记，交付段作者入口
            # 在场时自动让位（mechanical_assembly 既定口径），这里零择优
            # 改动。失败不阻塞主流程：降级回旧路径，交付段冒烟兜底。
            try:
                from app.utils.walking_skeleton import (
                    build_skeleton, should_build_skeleton, smoke_skeleton,
                )
                if should_build_skeleton(plans):
                    _skel_code = (self.file_manager.get_project(
                        team.project_id).root / "code")
                    _skel = build_skeleton(_skel_code, plans)
                    _rep = smoke_skeleton(_skel_code)
                    if not _rep.get("ok"):
                        _rep = smoke_skeleton(
                            _skel_code)  # 起服抖动重试一次
                    self._emit(
                        "skeleton_ready", ok=bool(_rep.get("ok")),
                        health=_rep.get("health"), home=_rep.get("home"),
                        routes=_rep.get("routes"),
                        framework=_skel.get("framework"),
                        blueprints=_skel.get("blueprints"),
                    )
                    print(
                        f"[skeleton] 行走骨架就绪: ok={_rep.get('ok')} "
                        f"framework={_skel.get('framework')} "
                        f"blueprints={_skel.get('blueprints')} "
                        f"routes={_rep.get('routes')}",
                        flush=True,
                    )
                    if not _rep.get("ok"):
                        print(
                            "[skeleton] 冒烟未过（重试后仍失败）——降级继续开发"
                            f"，排障线索: {(_rep.get('error') or '')[:140]}",
                            flush=True,
                        )
            except Exception as exc:
                print(f"[skeleton] 降级（不影响主流程）: {exc!r}",
                      flush=True)
            if interfaces:
                # factory26：契约快照事件（平台桥接层登记 traceability，
                # 工作台无消费者时零成本）
                self._emit(
                    "interfaces_ready",
                    interfaces={
                        name: {
                            "exports": list(c.get("exports") or []),
                            "public_api": list(c.get("public_api") or []),
                            "dependencies": list(c.get("dependencies") or []),
                        }
                        for name, c in interfaces.items()
                        if isinstance(c, dict)
                    },
                )
            stage_box[0] = "模块开发"
            self._emit("stage", stage=stage_box[0])  # M8-4

            # 生成时约束注入（generation-5 取证：命名漂移是最高频缺陷族）
            # 构建全模块导出符号摘要，注入 dev_loop——后续模块生成时
            # 能看到其他模块的导出名，消除 auth_bp/bp 式命名漂移
            # 任何异常静默吞掉——约束注入是增强，不能阻塞主流程
            try:
                if interfaces:
                    # 优先按 plans 开发顺序，再补 interfaces 里多出的名
                    ordered = [p.name for p in plans] if plans else list(
                        interfaces.keys())
                    seen: set[str] = set()
                    names: list[str] = []
                    for n in ordered:
                        if n not in seen:
                            seen.add(n)
                            names.append(n)
                    for n in interfaces:
                        if n not in seen:
                            names.append(n)
                    inventory = (
                        "## 本项目模块清单（硬约束）\n"
                        "只允许 `import` / `from … import` 下列模块名"
                        "（另加 `_shared` 与标准库/已知第三方）。"
                        "**禁止**发明清单外的兄弟模块名"
                        "（实测：`from auth import bp` / `from sheets import bp`"
                        "在清单无此名时会毒死组装工厂）。\n"
                        + "- " + ", ".join(names) + "\n"
                    )
                    peer_lines = []
                    for mod_name in names:
                        mod_contract = interfaces.get(mod_name) or {}
                        if not isinstance(mod_contract, dict):
                            peer_lines.append(f"- {mod_name}: （无契约）")
                            continue
                        exports = mod_contract.get("exports") or []
                        if exports:
                            peer_lines.append(
                                f"- {mod_name}: {', '.join(str(x) for x in exports[:8])}")
                        else:
                            peer_lines.append(f"- {mod_name}: （exports 未声明）")
                    # peer_exports 在 _develop_and_deliver 里挂到 DevLoop
                    self._peer_exports_summary = (
                        inventory
                        + "\n## 全模块导出符号清单（组装/跨模块 import 必须用这些名字）\n"
                        + "\n".join(peer_lines)
                    )
            except Exception:
                pass
            # 刀M：生成规范 skill 摘要（HOW；题面关键词路由，空=零变化）
            try:
                from app.skills_gen import detect_skills, render_skills_summary
                self._skills_summary = render_skills_summary(
                    detect_skills(requirement))
            except Exception:
                self._skills_summary = ""

            # 中断恢复（产品审计问题 4）：进入模块开发前落盘恢复快照——
            # 恢复所需的最小充分状态（order / plans / interfaces / 模式 / 模型）
            self._persist_pipeline_state(
                team.project_id, plans, interfaces, order, mode, models,
                budget_tokens=guard.budget_tokens,
            )

            result = self._develop_and_deliver(
                team, route, plans, interfaces, order, guard, mode,
                feedback_fn, user_feedback, module_results, stage_box,
                research_context=research_context,
                requirement=requirement,
            )
            # 任务完成 → 清理中断现场标记
            handle = self.file_manager.get_project(team.project_id)
            if handle is not None:
                marker = handle.root / "sessions" / "interruption.md"
                if marker.exists():
                    marker.unlink()
            return result
        except BudgetExceededError:
            # 11.0：超预算立即中止 → 落盘「已完成部分 + 未完成清单 + 已耗 token」
            return self._budget_stop_result(
                team, guard, stage_box[0], order, module_results, mode, route
            )
        except TaskDeadlineError as exc:
            # 运行墙钟见底（批次#58B）：不等平台强杀，自己走中断出口。
            # 与 KeyboardInterrupt 同路而非同 BudgetExceededError 一路：
            # 死因是时间不是钱，报告里写成「预算中止」会把下一次排障带到
            # 错误的方向（而信封调大这件事本来就不该由时间闸来背）。
            return self._interruption_result(
                team, guard, stage_box[0], order, module_results, mode, route,
                str(exc),
            )
        except KeyboardInterrupt:
            # Ctrl+C：落盘中断现场，返回可观测结果（11.0 同款「续跑或止损」语义）
            return self._interruption_result(
                team, guard, stage_box[0], order, module_results, mode, route,
                "KeyboardInterrupt（用户手动中断）",
            )
        except Exception as exc:
            # 意外异常：先落盘现场再上抛（bug 暴露不吞，恢复信息不丢失）
            self._persist_interruption(
                team, guard, stage_box[0], order, module_results,
                f"{type(exc).__name__}: {exc}",
            )
            raise
        finally:
            setattr(self.llm, "budget_guard", None)
            # 问题 7：任务终态清场——看板已构建并 persist 落盘，
            # 内存 call_log 无后续消费者（含直答路径的残留条目一并释放）
            if hasattr(self.llm, "call_log"):
                self.llm.call_log.clear()

    # ------------------------------------------------------------------

    def _develop_and_deliver(
        self,
        team,
        route,
        plans,
        interfaces: dict,
        order: list[str],
        guard: BudgetGuard,
        mode: str,
        feedback_fn: Callable[[str], str] | None,
        user_feedback: str,
        module_results: dict,
        stage_box: list[str] | None = None,
        research_context: str = "",
        requirement: str = "",
    ) -> PipelineResult:
        """模块开发循环 → _shared 回归 → 反馈环 → 交付（run / resume 共用）。

        stage_box：单元素可变列表——中断/预算中止时报告当前阶段
        （「反馈修复」比「模块开发」更精确），resume 传 None。

        research_context：M10-3 Researcher 摘要（已含数据边界治理），
        空串 = 未触发研究（零行为变化）。
        requirement：题面全文——覆盖闸/领域内核续跑补落盘可能用到。
        """
        git = self._git()
        project_root = self.file_manager.get_project(team.project_id).root
        # P1-D 续跑兜底：内核文件缺失则补（已存在跳过）
        if requirement:
            try:
                from app.utils.domain_kernels import ensure_domain_kernels
                ensure_domain_kernels(project_root / "code", requirement)
            except Exception:
                pass
        dev_loop = DevLoopEngine(
            llm=self.llm,
            dev_model=team.dev_model,
            test_model=team.test_model,
            executor=self.executor,
            settings=self.settings,
            file_manager=self.file_manager,
            budget_guard=guard,
            research_context=research_context,
            main_model=team.main_model,  # factory26 r7e：模型级降级备胎
        )
        peer = getattr(self, "_peer_exports_summary", "") or ""
        if peer:
            dev_loop.peer_exports_summary = peer
            self._peer_exports_summary = ""
        # 刀M：skill 摘要挂槽（默认空串=零行为变化）
        dev_loop.skills_summary = getattr(self, "_skills_summary", "") or ""
        # v52：schema 权威摘要进写码提示（盘上已有 CREATE TABLE）
        try:
            from app.utils.schema_audit import format_schema_authority
            schema = format_schema_authority(project_root / "code")
            if schema:
                dev_loop.schema_authority_summary = schema
        except Exception:
            pass
        self._bind_executor_project(team.project_id)
        # 14.4：_shared/ 内容签名基线（变更检测）
        shared_baseline = self.file_manager.shared_signature(team.project_id)

        def _finish_one(name: str) -> None:
            """单模块收尾:事件 + 阶段提交 + _shared 回归(串行段,并发后统一执行)。"""
            self._emit(
                "module_done", module=name,
                status=module_results[name].status.value,
                fix_attempts=module_results[name].fix_attempts,
                # C3 冻结原因前置展示:截尾原因直通工作台
                message=(module_results[name].message or "")[:200],
            )
            if git is not None:
                status = "完成" if module_results[name].status is ModuleStatus.SUCCESS else "冻结"
                git.commit_stage(
                    project_root, f"module:{name}",
                    f"模块 {name} {status}（修复 {module_results[name].fix_attempts} 次）",
                )
            return None

        def _develop_one(name: str) -> None:
            plan = next(p for p in plans if p.name == name)
            # 模块落地后 DDL 可能更新——刷新写码侧 schema 权威
            try:
                from app.utils.schema_audit import format_schema_authority
                schema = format_schema_authority(project_root / "code")
                if schema:
                    dev_loop.schema_authority_summary = schema
            except Exception:
                pass
            try:
                module_results[name] = dev_loop.run_module(
                    name,
                    project_id=team.project_id,
                    responsibility=plan.responsibility,
                    contract=interfaces.get(name),
                    project_modules=set(order),
                    user_feedback=user_feedback,
                )
            except ModelChainExhausted as exc:
                # generation-2 取证：单模块 LLM 全灭曾崩穿管线——143 需求
                # 2 小时工作量归零。该模块冻结（FROZEN），继续其余模块：
                # 部分交付仍进 Stage 3 评测拿部分分 > 零分。
                # 只捕模型链耗尽专类型：预算闸门与意外 bug 仍按原语义上抛。
                from app.agents.dev_loop import ModuleResult

                module_results[name] = ModuleResult(
                    module=name,
                    status=ModuleStatus.FROZEN,
                    fix_attempts=0,
                    message=f"模型级全链失败（模块冻结，优雅降级）: {exc}"[:200],
                )

        # v1.2 S0:按契约依赖分层;同层无依赖可并发(默认 1 = 完全串行,
        # 行为与 v1.0 逐字节一致)。层间仍按拓扑序,层结束后统一做
        # 事件/提交/_shared 回归(收尾段串行化,语义与串行等价)。
        layers = self._dependency_layers(order, interfaces)
        workers = max(1, int(self.settings.module_parallelism))
        _skel_routes: int | None = None  # 刀L：上一层层冒烟的路由数（趋势读数）
        for _layer_no, layer in enumerate(layers, 1):
            todo = [n for n in layer if n not in module_results]
            if not todo:
                continue  # resume:该层全部已完成/已冻结
            if workers > 1 and len(todo) > 1:
                from concurrent.futures import ThreadPoolExecutor

                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(_develop_one, n) for n in todo]
                    for f in futures:
                        f.result()  # 任一异常 → 传播(与串行语义一致)
            else:
                for n in todo:
                    _develop_one(n)
            # 收尾(串行):层内模块按原拓扑序 事件 → 提交 → _shared 回归
            for n in todo:
                _finish_one(n)
            shared_baseline = self._shared_regression(
                team, dev_loop, interfaces, order, module_results,
                shared_baseline, git, project_root,
            )
            # 刀L：层冒烟——骨架重新装配（吃进本层新完成模块）+ 起服探活。
            # 路由数较上层回退 = 新层破坏了既有挂载，当场显形（留痕
            # sessions/skeleton_smoke.md 供交付段修复环定向）；
            # 冒烟失败不阻塞开发（该层的模块自检/修复已各自负责），只报红。
            try:
                from app.utils.walking_skeleton import (
                    layer_smoke, should_build_skeleton,
                )
                if should_build_skeleton(plans):
                    _lrep = layer_smoke(
                        project_root / "code", plans, _layer_no,
                        sessions_dir=project_root / "sessions",
                        last_routes=_skel_routes,
                    )
                    _skel_routes = _lrep.get("routes") or _skel_routes
                    self._emit(
                        "layer_smoke", layer=_layer_no, ok=bool(_lrep.get("ok")),
                        health=_lrep.get("health"), home=_lrep.get("home"),
                        routes=_lrep.get("routes"),
                        routes_delta=_lrep.get("routes_delta"),
                        bp_coverage=_lrep.get("bp_coverage"),
                    )
                    print(
                        f"[skeleton] 层{_layer_no}冒烟: ok={_lrep.get('ok')} "
                        f"health={_lrep.get('health')} home={_lrep.get('home')} "
                        f"routes={_lrep.get('routes')}"
                        f"（Δ{_lrep.get('routes_delta')}） "
                        f"bp_coverage={_lrep.get('bp_coverage')}",
                        flush=True,
                    )
            except Exception as exc:
                print(f"[skeleton] 层冒烟降级: {exc!r}", flush=True)

        # 3.8 反馈交互闭环（安全模式）：循环直至用户确认成功 /
        # 达修复上限（冻结） / 手动停止（exit）
        if feedback_fn is not None and mode == "safe":
            if stage_box is not None:
                stage_box[0] = "反馈修复"
                self._emit("stage", stage=stage_box[0])  # M8-4
            self._feedback_loop(
                team, dev_loop, plans, interfaces, order,
                module_results, feedback_fn, git, project_root,
            )

        # 刀 I（v55）：交付前 node_states 覆盖缺口闸——官方树全节点 vs
        # SDK 已上报键集对账；缺口红 + 清单机械补挂最像模块 + requirements 补登记。
        if requirement:
            try:
                from app.utils.coverage_gap import enforce_node_states_gap
                owner_hint: dict[str, str] = {}
                try:
                    import json as _json
                    cov_path = (project_root / "sessions"
                                / "atomic_coverage.json")
                    if cov_path.is_file():
                        raw = _json.loads(
                            cov_path.read_text(encoding="utf-8"))
                        owner_hint.update(raw.get("owned") or {})
                        owner_hint.update(raw.get("assigned") or {})
                except Exception:
                    owner_hint = {}
                gap = enforce_node_states_gap(
                    requirement, plans, reported_ids=None,
                    project_root=project_root,
                    owner_hint=owner_hint,
                )
                if gap.missing:
                    self._emit(
                        "coverage_gap",
                        missing=list(gap.missing)[:40],
                        injected=dict(gap.injected),
                        registered=list(gap.registered)[:40],
                    )
            except Exception as exc:
                print(f"[coverage-gap] 交付前对账降级: {exc!r}", flush=True)

        # 交付物汇总（10.1 尾段）
        summary = self._deliverable_summary(team, module_results, mode)
        # 14 章：集成（交付汇总 + 成本报告）后最终提交
        if git is not None:
            git.commit_stage(project_root, "integration", "集成完成，交付物汇总")
        # M10-2 条件③：同一模块连续修复失败 ≥2 轮 → 建议 Researcher 调研
        #（仅建议不激活——4.5「由用户确认后激活」，总则 D.1）
        suggestions = [
            name for name, r in module_results.items()
            if r.fix_attempts >= 2
        ]
        if suggestions:
            self._emit("research_suggest", modules=suggestions)
        # factory26：完成标记（--resume 恢复查找的判据——硬杀进程写不出
        # interruption.md，只有 pipeline_state.json + 无完成标记 = 可恢复）
        try:
            (project_root / "sessions" / "completed.json").write_text(
                '{"completed": true}', encoding="utf-8"
            )
        except Exception:
            pass
        return PipelineResult(
            kind="team_flow",
            project_id=team.project_id,
            project_dir=self.file_manager.get_project(team.project_id).root,
            deliverable_summary=summary,
            frozen_modules=[
                n for n, r in module_results.items() if r.status is ModuleStatus.FROZEN
            ],
            route=route,
            cost_dashboard=self._build_dashboard(mode, team.project_id),
            research_suggestions=suggestions,
        )

    # ------------------------------------------------------------------

    # 中断恢复（产品审计问题 4）
    # ------------------------------------------------------------------

    _STATE_FILE = "pipeline_state.json"
    _INTERRUPT_FILE = "interruption.md"

    def _persist_pipeline_state(
        self, project_id: str, plans, interfaces: dict,
        order: list[str], mode: str, models: tuple[str, str, str],
        budget_tokens: int = 0,
    ) -> None:
        """进入模块开发前落盘恢复快照（resume 所需的最小充分状态）。"""
        import json as _json

        handle = self.file_manager.get_project(project_id)
        if handle is None:
            return
        state = {
            "order": order,
            "plans": [
                {"name": p.name, "responsibility": p.responsibility,
                 "dependencies": p.dependencies, "priority": p.priority}
                for p in plans
            ],
            "interfaces": interfaces,
            "mode": mode,
            "models": list(models),
            # 11.0 信封快照：题面折算出的 budget_override 只活在 run() 的
            # 局部变量里，不落盘则续跑必然退回配置缺省（见 resume 侧注释）
            "budget_tokens": int(budget_tokens) if budget_tokens else 0,
        }
        (handle.root / "sessions" / self._STATE_FILE).write_text(
            _json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _persist_interruption(
        self, team, guard, stage: str, order: list[str],
        module_results: dict, reason: str,
    ) -> None:
        """中断现场落盘 sessions/interruption.md（阶段/进度/token/恢复指引）。"""
        handle = self.file_manager.get_project(team.project_id)
        if handle is None:
            return
        completed = [
            n for n, r in module_results.items() if r.status is ModuleStatus.SUCCESS
        ]
        in_progress = [
            n for n, r in module_results.items()
            if r.status is not ModuleStatus.SUCCESS
        ]
        pending = [n for n in order if n not in module_results]
        used = guard.summary() if guard is not None else "（未知）"
        lines = [
            "========== 任务中断（崩溃 / Ctrl+C） ==========",
            f"项目目录: {handle.root}",
            f"中断阶段: {stage}",
            f"中断原因: {reason}",
            f"已耗 token: {used}",
            "",
            f"已完成部分: {', '.join(completed) if completed else '（无）'}",
            f"进行中（未完成）: {', '.join(in_progress) if in_progress else '（无）'}",
            f"未开始清单: {', '.join(pending) if pending else '（无）'}",
            "",
            "恢复方式: 重新运行程序并选择恢复该项目"
            "（已完成模块自动跳过，仅续跑未完成部分）；",
            "或止损：交付物与修复记录已落盘，可直接取用。",
        ]
        (handle.root / "sessions" / self._INTERRUPT_FILE).write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    def _interruption_result(
        self, team, guard, stage, order, module_results, mode, route, reason: str,
    ) -> PipelineResult:
        """Ctrl+C 的可观测返回（interruption.md 已落盘）。"""
        self._persist_interruption(
            team, guard, stage, order, module_results, reason
        )
        handle = self.file_manager.get_project(team.project_id)
        root = handle.root if handle is not None else None
        report = ""
        if root is not None:
            report = (root / "sessions" / self._INTERRUPT_FILE).read_text(encoding="utf-8")
        return PipelineResult(
            kind="interrupted",
            project_id=team.project_id,
            project_dir=root,
            deliverable_summary=report,
            pending_modules=[n for n in order if n not in module_results],
            route=route,
            cost_dashboard=self._build_dashboard(mode, team.project_id),
        )

    def resume(
        self,
        project_id: str,
        feedback_fn: Callable[[str], str] | None = None,
    ) -> PipelineResult:
        """从磁盘快照续跑中断任务（问题 4）。

        状态重建（零 LLM 调用）：
        - sessions/pipeline_state.json → plans / interfaces / order / 模式 / 模型；
        - changelog/<模块>/validation.md → 模块终态（SUCCESS / FROZEN /
          AWAITING_FEEDBACK）与修复次数；
        - code/<模块>/、tests/<模块>/ → 已生成代码与测试。

        续跑语义：SUCCESS 与 FROZEN 不重跑（不重复消耗 token）；
        AWAITING_FEEDBACK 直接进反馈环；无验证报告的模块重新开发。
        中断前已耗 token 计入新任务预算（11.0 总闸语义延续）。
        """
        import json as _json
        from types import SimpleNamespace

        from app.agents.module_builder import ModulePlan

        handle = self.file_manager.get_project(project_id)
        if handle is None:
            raise ValueError(f"项目不存在: {project_id!r}")
        state_path = handle.root / "sessions" / self._STATE_FILE
        if not state_path.is_file():
            raise ValueError(
                f"缺少 {self._STATE_FILE}（任务在模块拆分前中断，无法续跑；"
                "请重新发起任务）"
            )
        state = _json.loads(state_path.read_text(encoding="utf-8"))
        plans = [ModulePlan(**p) for p in state["plans"]]
        interfaces = state.get("interfaces") or {}
        order = state["order"]
        mode = state.get("mode", "safe")
        models = tuple(state.get("models") or ("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"))

        # team 轻量重建（TeamConfig 字段子集）
        main_model, dev_model, test_model = _model_triplet(models)
        # 信封继承快照：官方题面入口的预算是按 ATOMIC 条数折算的
        # （main.py → budget_override），这份折算只存在于护栏里。快照没有
        # budget_tokens 的旧项目/脏值退回配置口径——但绝不能让续跑拿到比
        # 「跑完这道题的实测成本」更小的信封，那等于第二次付费跑开局即注定撞墙。
        try:
            snap_budget = int(state.get("budget_tokens") or 0)
        except (TypeError, ValueError):
            snap_budget = 0
        team = SimpleNamespace(
            project_id=project_id,
            main_model=main_model, dev_model=dev_model, test_model=test_model,
            budget_tokens=(snap_budget if snap_budget > 0
                           else self.settings.task_token_budget(mode)),
        )
        self._bind_executor_project(project_id)
        _resume_handle = self.file_manager.get_project(project_id)
        self._heartbeat_root = (
            _resume_handle.root if _resume_handle is not None else None
        )

        # 模块终态重建：validation.md（无报告 → 待重跑，不进 module_results）
        module_results: dict = {}
        for name in order:
            rebuilt = self._rebuild_module_result(project_id, name)
            if rebuilt is not None:
                module_results[name] = rebuilt

        # 11.0 总闸：中断前已耗 token 从 interruption.md 之后的 call_log
        # 无法恢复，按快照时刻的 guard 用量近似——resume 会话从零起算，
        # 预算覆盖续跑部分（原始预算已在快照任务中部分消耗）。
        self._resolve_llm()  # M8-1：factory 模式下续跑同样每任务新建
        self._emit("stage", stage="恢复续跑")  # M8-4
        self._task_baseline = len(getattr(self.llm, "call_log", []))  # 看板切片
        # M10-3：中断前已生成的研究摘要 → 重读注入（无需重新生成消耗）
        research_brief_path = handle.root / "sessions" / "research_brief.md"
        research_context = (
            sanitize_untrusted(research_brief_path.read_text(encoding="utf-8"))
            if research_brief_path.is_file() else ""
        )
        guard = BudgetGuard(
            budget_tokens=team.budget_tokens,
            throttle_threshold=self.settings.budget_throttle_threshold,
            repair_reserve_ratio=getattr(
                self.settings, "budget_repair_reserve", 0.0),
        )
        # M14-6：恢复历史用量（11.0 单任务总预算语义——多次 resume 不再
        # N×budget 超支；「交用户决定续跑」语义保留：预算仍可被重新配置）
        history_report = self._read_cost_report(handle.root)
        history_tokens = int(history_report.get("total_tokens", 0) or 0)
        if history_tokens > 0:
            guard.record(history_tokens)
        setattr(self.llm, "budget_guard", guard)
        # resume 同 run 登记『活动护栏』：verify/修复通道的零散 ModelClient
        # 靠这把兜底接入预算闸——漏登记则恢复后的验证/修复整体绕闸烧钱
        # （与 run():392 同款；¥210 学费同源。Qoder 交叉审查 9/21 取证）
        from app.utils.budget import set_active_budget_guard

        set_active_budget_guard(guard)
        # M12-1：协作式取消检查点注入（resume 路径同 run）
        if self._cancel_check is not None:
            guard.attach_cancel_check(self._cancel_check)
        try:
            result = self._develop_and_deliver(
                team, None, plans, interfaces, order, guard, mode,
                feedback_fn, "", module_results,
                research_context=research_context,
            )
            marker = handle.root / "sessions" / self._INTERRUPT_FILE
            if marker.exists():
                marker.unlink()
            return result
        except BudgetExceededError:
            return self._budget_stop_result(
                team, guard, "恢复续跑", order, module_results, mode, None
            )
        except TaskDeadlineError as exc:
            # 续跑段同样在墙钟管辖内（批次#58B）：恢复出来的项目更容易一路
            # 跑到上限，中断现场照常落盘，出口走「按现状交付」。
            return self._interruption_result(
                team, guard, "恢复续跑", order, module_results, mode, None,
                str(exc),
            )
        except KeyboardInterrupt:
            return self._interruption_result(
                team, guard, "恢复续跑", order, module_results, mode, None,
                "KeyboardInterrupt（用户手动中断）",
            )
        except Exception as exc:
            self._persist_interruption(
                team, guard, "恢复续跑", order, module_results,
                f"{type(exc).__name__}: {exc}",
            )
            raise
        finally:
            setattr(self.llm, "budget_guard", None)
            # 问题 7：续跑会话同样终态清场（看板已 persist）
            if hasattr(self.llm, "call_log"):
                self.llm.call_log.clear()

    def _rebuild_module_result(self, project_id: str, name: str):
        """从 validation.md + 磁盘代码重建 ModuleResult；无报告返回 None。"""
        import re as _re

        from app.agents.dev_loop import ModuleResult, ModuleStatus

        handle = self.file_manager.get_project(project_id)
        report = handle.root / "changelog" / name / "validation.md"
        if not report.is_file():
            return None
        text = report.read_text(encoding="utf-8")
        status_match = _re.search(r"最终状态[:：]\s*(\w+)", text)
        fix_match = _re.search(r"修复次数[:：]\s*(\d+)", text)
        if not status_match:
            return None
        try:
            status = ModuleStatus(status_match.group(1))
        except ValueError:
            return None
        code = self.file_manager.read_file(project_id, f"code/{name}/{name}.py") or ""
        tests = self.file_manager.read_file(project_id, f"tests/{name}/test_{name}.py") or ""
        return ModuleResult(
            module=name, status=status,
            fix_attempts=int(fix_match.group(1)) if fix_match else 0,
            message="（中断恢复重建）", code=code, tests=tests,
        )

    # ------------------------------------------------------------------

    def _bind_executor_project(self, project_id: str) -> None:
        """自动验证模式：把项目 code/ 目录绑定给执行器（依赖解析）。

        M2：LocalExecutor / DockerExecutor 经基类 bind_project_code_dir
        接收绑定；测试注入的鸭子类型桩无此方法，跳过即可。
        """
        bind = getattr(self.executor, "bind_project_code_dir", None)
        if bind is None:
            return
        handle = self.file_manager.get_project(project_id)
        if handle is not None:
            bind(handle.root / "code")

    def _persist_assessment(self, project_id: str, route, models, mode: str) -> None:
        """6.3：评估结论落盘 sessions/difficulty_assessment.md。"""
        import time as _time

        handle = self.file_manager.get_project(project_id)
        if handle is None:
            return
        main_model, dev_model, test_model = _model_triplet(models)
        lines = [
            "# 难度评估与路由决策（3.2）",
            "",
            f"- 评估时间: {_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 难度分: {route.difficulty_score}（{route.difficulty_level}）",
            f"- 任务类型: {route.task_type}",
            f"- 预估源码文件数: {route.estimated_files}",
            f"- 路由决策: {route.route.value}",
            f"- 评估理由: {route.reason or '（未提供）'}",
            f"- 团队模型: 主 {main_model} / 开发 {dev_model} / 测试 {test_model}",
            f"- 执行模式: {mode}",
        ]
        if route.rechecked:
            lines.append("- 边界护栏复核: 已触发")
        if route.fallback:
            lines.append("- 解析降级: 是（保守视作编程任务，15.3）")
        if route.suggest_review:
            lines.append("- 评审建议: 研究·分析难度 ≥8，可选用一次评审确认")
        path = handle.root / "sessions" / "difficulty_assessment.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _shared_regression(
        self,
        team,
        dev_loop: DevLoopEngine,
        interfaces: dict,
        order: list[str],
        module_results: dict,
        shared_baseline: str,
        git,
        project_root,
    ) -> str:
        """14.4/12.7：检测 _shared/ 变更并对依赖模块整包回归。

        _shared 签名与基线一致（14.5：普通模块修复不触发）→ 直接返回；
        变更 → AST 判定依赖模块（已完成 SUCCESS 者）逐个重走
        门禁+执行，回归失败进修复循环；事件落盘可审计。
        """
        current = self.file_manager.shared_signature(team.project_id)
        if current == shared_baseline:
            return shared_baseline

        # 变更：找已完成且依赖 _shared 的模块
        dependents = find_shared_dependents(project_root, order)
        regressed = [
            n for n in dependents
            if n in module_results
            and module_results[n].status is ModuleStatus.SUCCESS
        ]
        outcomes: list[str] = []
        for name in regressed:
            module_results[name] = dev_loop.regress_module(
                name,
                module_results[name],
                project_id=team.project_id,
                contract=interfaces.get(name),
                project_modules=set(order),
            )
            result = module_results[name]
            outcomes.append(
                f"- {name}: {'回归通过' if result.status is ModuleStatus.SUCCESS else f'回归后状态 {result.status.value}（修复 {result.fix_attempts} 次）'}"
            )
            if git is not None:
                git.commit_stage(
                    project_root, f"regression:{name}",
                    f"_shared 变更触发 {name} 整包回归",
                )
        self._persist_regression_report(project_root, regressed, outcomes)
        return current

    def _persist_regression_report(
        self, project_root, regressed: list[str], outcomes: list[str]
    ) -> None:
        """14.4：回归事件落盘（changelog/shared_regression.md，追加式审计）。"""
        import time as _time

        if not regressed:
            return
        path = project_root / "changelog" / "shared_regression.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = (
            f"\n## _shared 变更整包回归（{_time.strftime('%Y-%m-%d %H:%M:%S')}）\n"
            f"回归范围: {', '.join(regressed)}\n"
            + "\n".join(outcomes)
            + "\n"
        )
        with path.open("a", encoding="utf-8") as f:
            f.write(entry)

    _EXIT_WORDS = ("exit", "quit", "停止", "结束")

    def _feedback_loop(
        self,
        team,
        dev_loop: DevLoopEngine,
        plans,
        interfaces: dict,
        order: list[str],
        module_results: dict,
        feedback_fn: Callable[[str], str],
        git,
        project_root,
    ) -> None:
        """3.8 反馈交互闭环：用户手动运行反馈驱动的修复循环。

        循环直至三态之一：
        - 用户确认成功（active 清空）；
        - 全部模块达修复上限（冻结，退出 active）；
        - 用户手动停止（exit / 空输入，模块保持待反馈状态）。

        3.8/4.5：同一模块连续修复 ≥2 轮未成功 → 征询 prompt 中
        附带 Researcher 调研建议（Beta v0.5，MVP 以提示落地）。
        """
        project_modules = set(order)
        while True:
            active = [
                n for n in order
                if module_results[n].status is ModuleStatus.AWAITING_FEEDBACK
            ]
            if not active:
                return
            hints = [
                f"模块 {n} 已连续修复 {module_results[n].fix_attempts} 轮未确认成功，"
                "建议启动 Researcher 调研（Beta v0.5）或粘贴相关文档片段辅助修复"
                for n in active if module_results[n].fix_attempts >= 2
            ]
            prompt = (
                f"请本地运行模块 {', '.join(active)} 并反馈结果"
                "（确认成功词 / 粘贴报错日志触发修复 / exit 结束）"
            )
            if hints:
                prompt += "\n" + "\n".join(hints)
            reply = (feedback_fn(prompt) or "").strip()
            # 3.8：手动停止（保留待反馈状态与现场）
            if not reply or reply.lower() in self._EXIT_WORDS:
                return
            for name in active:
                module_results[name] = dev_loop.resume_with_feedback(
                    name,
                    module_results[name],
                    reply,
                    project_id=team.project_id,
                    contract=interfaces.get(name),
                    project_modules=project_modules,
                )
                # 14 章：反馈轮修复后追加阶段提交（保留现场演进轨迹）
                if git is not None:
                    git.commit_stage(
                        project_root, f"module:{name}",
                        f"模块 {name} 反馈修复"
                        f"（累计修复 {module_results[name].fix_attempts} 次）",
                    )

    def _budget_stop_result(
        self,
        team,
        guard: BudgetGuard,
        stage: str,
        order: list[str],
        module_results: dict,
        mode: str,
        route: RoutingResult,
    ) -> PipelineResult:
        """预算中止结果：报告落盘 sessions/budget_stop.md（11.0，交用户决定）。"""
        completed = [
            n for n, r in module_results.items() if r.status is ModuleStatus.SUCCESS
        ]
        pending = [n for n in order if n not in module_results]
        handle = self.file_manager.get_project(team.project_id)
        root = handle.root if handle is not None else None
        lines = [
            "========== 预算中止（11.0 单任务成本总预算闸门） ==========",
            f"项目目录: {root}",
            f"中止阶段: {stage}",
            f"已耗 token: {guard.summary()}",
            "",
            f"已完成部分: {', '.join(completed) if completed else '（无）'}",
            f"未完成清单: {', '.join(pending) if pending else '（无）'}",
            "",
            "请决定：续跑（调高 max_task_tokens 后重新发起）或止损（保留现场）。",
        ]
        if root is not None:
            (root / "sessions" / "budget_stop.md").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
        return PipelineResult(
            kind="budget_exceeded",
            project_id=team.project_id,
            project_dir=root,
            deliverable_summary="\n".join(lines),
            pending_modules=pending,
            route=route,
            cost_dashboard=self._build_dashboard(mode, team.project_id),
        )

    def _build_dashboard(self, mode: str, project_id: str):
        """8.5 成本统计：从本任务切片构建仪表盘并落盘 logs/（问题 7）。"""
        if not hasattr(self.llm, "call_log"):
            return None
        # M12-4：看板预算 = 实际生效预算（任务级覆盖优先于档位配置）
        guard = getattr(self.llm, "budget_guard", None)
        budget = (
            guard.budget_tokens if guard is not None
            else self.settings.task_token_budget(mode)
        )
        # M12-9：路由档位标注 + 旗舰假设成本（价格维度，确定性计算）
        tmap = tier_map(self.settings)
        ref = next(
            (m for m in self.settings.model_tier_flagship
             if m in self.settings.models),
            None,
        )
        flagship_price = (
            self.settings.model_prices.get(ref) if ref is not None else None
        )
        dashboard = CostDashboard.from_call_log(
            self.llm.call_log[self._task_baseline:],  # 仅本任务条目
            budget_tokens=budget,
            tier_map=tmap,
        )
        handle = self.file_manager.get_project(project_id)
        if handle is not None:
            # M14-6：看板累计口径——并入历史会话聚合（resume 后 cost_report
            # 为项目累计审计报告，与 guard 恢复的预算口径一致）
            history_report = self._read_cost_report(handle.root)
            if history_report:
                dashboard.merge_history(history_report)
            dashboard.attach_routing_costs(
                prices=self.settings.model_prices,
                flagship_price=flagship_price,
            )
            dashboard.persist(
                handle.root / "logs",
                prices=self.settings.model_prices,
                flagship_price=flagship_price,
            )
        return dashboard

    def _read_cost_report(self, project_root) -> dict:
        """M14-6：读项目 logs/cost_report.json（缺失/损坏 → 空字典）。"""
        import json as _json

        path = project_root / "logs" / "cost_report.json"
        if not path.is_file():
            return {}
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

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
            # 3.8 三态：完成 / 待用户反馈（未验证） / 冻结（修复上限）
            if result.status is ModuleStatus.SUCCESS:
                status = "完成"
            elif result.status is ModuleStatus.AWAITING_FEEDBACK:
                status = "待用户反馈（未验证）"
            else:
                status = "冻结（修复上限）"
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
                f"  cd {root / 'code'}",
                "  python -m <模块名>.<模块名>    # 逐模块运行（如 user → python -m user.user）",
                f"  cd {root} && python -m pytest tests/<模块>/ -v",
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
