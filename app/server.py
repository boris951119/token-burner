"""API server（client.html 契约的正式实现）。

薄 FastAPI 包装：交互层不含流程逻辑，全部编排经 Pipeline（与 CLI 同构）。
契约（与 client.html 中约定一致）：

  GET  /api/health                          → 探活（客户端 live 检测）
  POST /api/route      {requirement}        → 评估结果（展示用）
  POST /api/run        {requirement, models?, mode?, spec_confirm?,
                        confirmed_as_coding?, route?} → 完整执行
  POST /api/tasks      {kind: run|resume|feedback, ...} → {task_id}（异步提交，M8-3）
  GET  /api/tasks/{id}                      → 任务状态/当前阶段/已耗 token
  GET  /api/tasks/{id}/events               → SSE 进度事件流（M8-4）
  GET  /api/resumable                       → 可恢复项目列表
  POST /api/resume      {project_id}        → 续跑（已完成模块跳过）
  POST /api/project/{id}/feedback {message} → 单轮反馈（经 resume 通道）
  GET  /api/project/{id}/dashboard          → 成本看板（磁盘 logs/）

设计要点：
- route 与 run 分离且 route 可回传（问题 5：复用评估，零重复调用）；
- 反馈闭环经 Pipeline.resume 磁盘重建（进程重启不丢现场）；
- M8-1 任务级隔离：每任务经 ModelClientFactory 新建 ModelClient
  （budget_guard / call_log 天然隔离，不串数）；测试注入 llm 时
  退回共享实例（旧行为兼容）；/route 每请求临时客户端；
- M8-2 项目级锁：/resume、/feedback 同一项目串行（防文件/git 写
  竞争），不同项目完全并行——替换旧全局 task_lock（并发能力=1）；
  /run 新建项目目录带时间戳唯一、/route 无项目状态，均无需加锁；
- 长任务同步返回（MVP）：真实任务可能数分钟，客户端需容忍长响应。

启动：
  python -m app.server            # 默认 127.0.0.1:8000
  uvicorn app.server:app --port 8000
"""

from __future__ import annotations

import json
import queue
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, load_settings
from app.dashboard.cost_dashboard import CostDashboard
from app.recommender import recommend as recommend_mode
from app.execution.factory import build_executor
from app.orchestrator import Route, RoutingResult, TaskRouter
from app.pipeline import Pipeline, PipelineResult
from app.task_manager import TaskManager, TaskStatus
from app.tools.file_manager import FileManager
from app.utils.locks import ProjectLockManager
from app.utils.model_client import ModelClientFactory


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class RouteRequest(BaseModel):
    requirement: str = Field(min_length=1)


class RunRequest(BaseModel):
    requirement: str = Field(min_length=1)
    models: list[str] | None = None          # 三模型互异（3.3），缺省用配置
    mode: str = "safe"                       # safe | auto
    spec_confirm: str = "确认"               # 11.5 spec 确认（缺省直接确认）
    confirmed_as_coding: bool = False        # 15.3 保守降级确认
    route: dict | None = None                # /api/route 结果回传（复用评估）


class ResumeRequest(BaseModel):
    project_id: str


class FeedbackRequest(BaseModel):
    message: str = Field(min_length=1)


class TaskSubmitRequest(BaseModel):
    """M8-3 异步任务提交体（kind 区分三种入口）。"""

    kind: str = "run"                        # run | resume | feedback
    requirement: str = ""                    # run 必填
    project_id: str | None = None            # resume / feedback 必填
    message: str = ""                        # feedback 必填（单轮反馈内容）
    models: list[str] | None = None          # run：三模型互异（3.3）
    mode: str = "safe"                       # run：safe | auto
    spec_confirm: str = "确认"
    confirmed_as_coding: bool = False
    route: dict | None = None                # /api/route 结果回传（复用评估）
    # M10 Researcher（v0.5 Beta，researcher_enabled 开启时生效）：
    # research = on（显式调研）| auto（评估命中陌生栈自动触发）| off
    research: str = "off"
    research_material: str = ""              # 用户提供的资料文本（降级模式输入）


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------

def _route_dict(route: RoutingResult | None) -> dict | None:
    if route is None:
        return None
    data = asdict(route)
    data["route"] = route.route.value
    return data


def _route_from_dict(data: dict) -> RoutingResult:
    """JSON → RoutingResult（route 枚举还原；非法 route 值显式报错）。"""
    payload = dict(data)
    try:
        payload["route"] = Route(payload.pop("route"))
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, f"route 字段非法: {exc}") from exc
    fields = {f.name for f in RoutingResult.__dataclass_fields__.values()}
    unknown = set(payload) - fields
    if unknown:
        raise HTTPException(400, f"route 含未知字段: {sorted(unknown)}")
    return RoutingResult(**payload)


def _dashboard_dict(dashboard: CostDashboard) -> dict:
    return {
        "budget_tokens": dashboard.budget_tokens,
        "total_tokens": dashboard.total_tokens,
        "input_output": dashboard.input_output_totals(),
        "by_model": dashboard.by_model(),
        "by_stage": dashboard.by_stage(),
        "savings": dashboard.savings_summary(),  # M6-1：节省量三指标
    }


def _result_dict(result: PipelineResult) -> dict:
    return {
        "kind": result.kind,
        "answer": result.answer,
        "declined_reply": result.declined_reply,  # M9-3：快判拒答友好文案
        "project_id": result.project_id,
        "project_dir": str(result.project_dir) if result.project_dir else None,
        "needs_user_confirm": result.needs_user_confirm,
        "deliverable_summary": result.deliverable_summary,
        "frozen_modules": result.frozen_modules,
        "pending_modules": result.pending_modules,
        "route": _route_dict(result.route),
        "dashboard": (
            _dashboard_dict(result.cost_dashboard)
            if result.cost_dashboard is not None else None
        ),
    }


# ---------------------------------------------------------------------------
# 应用工厂
# ---------------------------------------------------------------------------

def create_app(
    llm: Any = None,
    settings: Settings | None = None,
    projects_root: Path | None = None,
    executor: Any = None,
    llm_factory: Any = None,
) -> FastAPI:
    """构建 API 应用。参数注入供测试；缺省为生产配置。

    llm 与 llm_factory 的取舍（M8-1）：注入 llm → 全端点共享实例
    （测试桩兼容）；否则经 llm_factory 每请求/每任务新建客户端。
    """
    app = FastAPI(title="token-burner API", version="0.1.0")
    app.state.settings = settings or load_settings()
    app.state.llm = llm  # 测试注入（共享模式）；生产为 None
    app.state.llm_factory = llm_factory or ModelClientFactory(app.state.settings)
    # 产出目录三层优先：显式注入（测试）> config.projects_root > cwd/projects
    app.state.file_manager = FileManager(
        projects_root=(
            projects_root
            or (
                Path(app.state.settings.projects_root)
                if app.state.settings.projects_root else None
            )
            or (Path.cwd() / "projects")
        )
    )
    app.state.executor = executor            # 测试注入；缺省按 mode 构造
    app.state.lock_manager = ProjectLockManager()  # M8-2 项目级锁
    app.state.task_manager = TaskManager(
        projects_root=app.state.file_manager.projects_root,
    )  # M8-3 异步任务（线程池 + 状态落盘 + 事件广播）
    app.state.task_manager.recover_zombies()  # M12-1：重启后僵尸清扫

    def _client():
        """M8-1：本请求的 ModelClient（注入 llm 时退回共享实例）。"""
        return app.state.llm or app.state.llm_factory.create()

    def _pipeline(mode: str, task_id: str | None = None) -> Pipeline:
        executor_obj = app.state.executor or build_executor(mode, app.state.settings)
        return Pipeline(
            llm=app.state.llm,
            llm_factory=None if app.state.llm else app.state.llm_factory,
            settings=app.state.settings,
            file_manager=app.state.file_manager,
            executor=executor_obj,
            # M8-4：异步任务挂接进度事件（同步端点不挂接）
            on_event=(
                (lambda kind, data:
                 app.state.task_manager.on_pipeline_event(task_id, kind, data))
                if task_id else None
            ),
            # M12-1：协作式取消旗标（异步任务注入 BudgetGuard 检查点）
            cancel_check=(
                (lambda: app.state.task_manager.cancel_flag(task_id).is_set())
                if task_id else None
            ),
        )

    def _validated_models(models: list[str] | None) -> tuple[str, str, str]:
        models_t = tuple(models) if models else tuple(app.state.settings.models[:3])
        if len(models_t) != 3 or len(set(models_t)) != 3:
            raise HTTPException(400, "三个模型必须互异（规格 3.3）")
        return models_t  # type: ignore[return-value]

    def _project_mode(project_id: str) -> str:
        """按快照确定执行模式（/resume、/feedback 共用）。"""
        state_path = (
            app.state.file_manager.projects_root / project_id
            / "sessions" / "pipeline_state.json"
        )
        if state_path.is_file():
            try:
                return json.loads(
                    state_path.read_text(encoding="utf-8")
                ).get("mode", "safe")
            except (OSError, ValueError):
                pass
        return "safe"

    # ------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/config")
    def config() -> dict:
        """插件/客户端启动配置：预设模型、执行模式与预算（展示用，M1-2）。"""
        s = app.state.settings
        return {
            "models": list(s.models),
            "default_mode": s.default_execution_mode,
            "budget_tokens": s.task_token_budget("safe"),
            "auto_budget_tokens": s.task_token_budget("auto"),
            "auto_budget_multiplier": s.auto_mode_budget_multiplier,
            "projects_root": str(app.state.file_manager.projects_root),
        }

    @app.get("/", include_in_schema=False)
    def index():
        """同源托管 client.html（浏览器直开避免 CORS；API_BASE 同源即可）。"""
        import sys

        from fastapi.responses import FileResponse

        # PyInstaller onefile：资源解压在 sys._MEIPASS 临时目录
        if getattr(sys, "frozen", False):
            client = Path(sys._MEIPASS) / "client.html"  # type: ignore[attr-defined]
        else:
            client = Path(__file__).resolve().parent.parent / "client.html"
        if client.is_file():
            return FileResponse(client)
        raise HTTPException(404, "client.html 不存在")

    @app.post("/api/route")
    def route(req: RouteRequest) -> dict:
        """需求评估（3.2 三分类路由 / M9 快判）；结果可回传 /api/run 复用。

        M8-1：每请求临时客户端（无任务级状态可竞争），无需加锁。
        """
        router = TaskRouter(_client(), app.state.settings.models[0],
                            app.state.settings)
        result = _llm_call(router.route, req.requirement)
        return _route_dict(result)

    @app.post("/api/run")
    def run(req: RunRequest) -> dict:
        """完整管线执行（同步长任务）。

        M8-2：新建项目目录带时间戳唯一，且本端点不触碰既有项目——
        无需项目锁，多任务天然并行（每任务客户端/执行器独立，M8-1）。
        """
        if req.mode not in ("safe", "auto"):
            raise HTTPException(400, f"mode 非法: {req.mode}")
        models = _validated_models(req.models)
        route_obj = _route_from_dict(req.route) if req.route else None
        pipeline = _pipeline(req.mode)
        result = _llm_call(
            pipeline.run, req.requirement,
            confirmed_as_coding=req.confirmed_as_coding,
            models=models,
            mode=req.mode,
            # 3.6.3：API 请求显式选择 auto 即视为用户确认（客户端 UI 展示
            # 预算放大警示后提交）；否则 TeamBuilder 预算闸门会拒绝
            auto_mode_confirmed=(req.mode == "auto"),
            spec_confirm=req.spec_confirm,
            route=route_obj,
        )
        return _result_dict(result)

    @app.get("/api/recommend")
    def recommend(requirement: str = "") -> dict:
        """M11-3：模式智能推荐（历史项目确定性统计，无 LLM，可覆盖）。"""
        if not requirement.strip():
            raise HTTPException(400, "requirement 不能为空")
        return recommend_mode(
            requirement,
            app.state.file_manager.projects_root,
            app.state.settings,
        )

    @app.post("/api/tasks")
    def submit_task(req: TaskSubmitRequest) -> dict:
        """M8-3 异步任务提交：立即返回 task_id（线程池执行，并发 ≥4）。

        kind=run      → 完整管线（语义同 /api/run）
        kind=resume   → 续跑中断项目（语义同 /api/resume）
        kind=feedback → 单轮反馈（语义同 /api/project/{id}/feedback）
        进度查询：GET /api/tasks/{id}；实时事件：GET /api/tasks/{id}/events。
        项目级锁在任务体内获取（提交立即返回，锁不阻塞响应）。
        """
        started = time.monotonic()
        project_dir = ""  # run：项目未创建，落盘位置由 project 事件回填

        if req.kind == "run":
            if not req.requirement.strip():
                raise HTTPException(400, "run 任务需要 requirement")
            if req.mode not in ("safe", "auto"):
                raise HTTPException(400, f"mode 非法: {req.mode}")
            models = _validated_models(req.models)
            route_obj = _route_from_dict(req.route) if req.route else None

            def job_factory(task_id: str) -> Any:
                def job() -> dict:
                    pipeline = _pipeline(req.mode, task_id)
                    return _result_dict(pipeline.run(
                        req.requirement,
                        confirmed_as_coding=req.confirmed_as_coding,
                        models=models, mode=req.mode,
                        # 3.6.3：API 显式选择 auto 即视为确认（同 /api/run）
                        auto_mode_confirmed=(req.mode == "auto"),
                        spec_confirm=req.spec_confirm, route=route_obj,
                        # M10：Researcher 触发模式与资料透传
                        research=req.research,
                        research_material=req.research_material,
                    ))
                return job

        elif req.kind == "resume":
            if not req.project_id:
                raise HTTPException(400, "resume 任务需要 project_id")
            handle = app.state.file_manager.get_project(req.project_id)
            if handle is None:
                raise HTTPException(404, f"项目不存在: {req.project_id}")
            project_dir = str(handle.root)
            mode = _project_mode(req.project_id)

            def job_factory(task_id: str) -> Any:
                def job() -> dict:
                    pipeline = _pipeline(mode, task_id)
                    with app.state.lock_manager.acquire(req.project_id):
                        return _result_dict(pipeline.resume(req.project_id))
                return job

        elif req.kind == "feedback":
            if not req.project_id:
                raise HTTPException(400, "feedback 任务需要 project_id")
            handle = app.state.file_manager.get_project(req.project_id)
            if handle is None:
                raise HTTPException(404, f"项目不存在: {req.project_id}")
            if not req.message.strip():
                raise HTTPException(400, "feedback 任务需要 message")
            project_dir = str(handle.root)
            mode = _project_mode(req.project_id)

            def job_factory(task_id: str) -> Any:
                # 单条反馈语义与同步端点一致：本轮消费一条 → exit 停止
                state = {"given": False}

                def one_shot(prompt: str) -> str:
                    if state["given"]:
                        return "exit"
                    state["given"] = True
                    return req.message

                def job() -> dict:
                    pipeline = _pipeline(mode, task_id)
                    with app.state.lock_manager.acquire(req.project_id):
                        return _result_dict(pipeline.resume(
                            req.project_id, feedback_fn=one_shot,
                        ))
                return job

        else:
            raise HTTPException(
                400, f"kind 非法: {req.kind}（run | resume | feedback）"
            )

        task_id = app.state.task_manager.submit(
            kind=req.kind, job_factory=job_factory,
            requirement=req.requirement,
            project_id=req.project_id, project_dir=project_dir,
        )
        return {
            "task_id": task_id,
            "kind": req.kind,
            "status": "pending",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }

    @app.get("/api/tasks/{task_id}")
    def task_status(task_id: str) -> dict:
        """M8-3：任务状态/当前阶段/已耗 token；服务重启后仍可查询。"""
        data = app.state.task_manager.get(task_id)
        if data is None:
            raise HTTPException(404, f"任务不存在: {task_id}")
        return data

    @app.delete("/api/tasks/{task_id}")
    def cancel_task(task_id: str) -> dict:
        """M12-1：取消任务（pending 立即 / running 协作式）。

        - pending → 立即置 CANCELLED（响应 status=cancelled）；
        - running → 置协作取消旗标（响应 status=cancelling，
          任务体在下一 BudgetGuard 检查点中止，终态经 GET/SSE 收敛）；
        - 已终态 → 409；未知 task_id → 404。
        """
        result = app.state.task_manager.cancel(task_id)
        if result is None:
            raise HTTPException(404, f"任务不存在: {task_id}")
        action, state = result
        if action == "already_terminal":
            raise HTTPException(
                409, f"任务已终态（{state['status']}），无法取消"
            )
        return {
            "task_id": task_id,
            "status": "cancelled" if action == "immediate" else "cancelling",
            "mode": action,
            "detail": state.get("error", ""),
        }

    @app.get("/api/tasks/{task_id}/events")
    def task_events(task_id: str):
        """M8-4 SSE 进度事件流（text/event-stream）。

        首帧为全量快照（断线重连不丢状态）；终态 done 帧后关闭；
        每 30s 心跳注释帧保活；客户端 EventSource 断线自动重连。
        """
        snapshot = app.state.task_manager.get(task_id)
        if snapshot is None:
            raise HTTPException(404, f"任务不存在: {task_id}")
        q = app.state.task_manager.subscribe(task_id)

        def gen():
            try:
                yield _sse({"type": "snapshot", "task": snapshot})
                if snapshot.get("status") in [
                    s.value for s in TaskStatus.terminal()
                ]:
                    # 订阅时任务已终态（竞态）：快照 + done 后即关流
                    yield _sse({
                        "type": "done", "status": snapshot.get("status"),
                        "task_id": task_id, "result": snapshot.get("result"),
                    })
                    return
                while True:
                    try:
                        event = q.get(timeout=30)
                    except queue.Empty:
                        yield ": keep-alive\n\n"
                        continue
                    yield _sse(event)
                    if event.get("type") == "done":
                        return
            finally:
                app.state.task_manager.unsubscribe(task_id, q)

        from fastapi.responses import StreamingResponse

        return StreamingResponse(
            gen(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/resumable")
    def resumable() -> list[dict]:
        """含恢复快照的项目（最新优先；含已中断标记）。"""
        fm = app.state.file_manager
        root = fm.projects_root
        if not root.is_dir():
            return []
        out = []
        for p in root.iterdir():
            state = p / "sessions" / "pipeline_state.json"
            if not state.is_file():
                continue
            try:
                meta = json.loads(state.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out.append({
                "project_id": p.name,
                "order": meta.get("order", []),
                "mode": meta.get("mode", "safe"),
                "interrupted": (p / "sessions" / "interruption.md").is_file(),
            })
        out.sort(key=lambda x: x["project_id"], reverse=True)
        return out

    @app.get("/api/projects")
    def projects() -> list[dict]:
        """M5-2 历史项目列表（全部 projects/，最新优先，只读聚合）。

        每项：需求摘要（task_state/pipeline_state 回填，缺失时回落目录名）、
        执行模式、是否可恢复/已中断、已耗 token（logs/cost_report.json）、
        更新时间（目录 mtime）。损坏的元数据文件跳过对应字段不跳过项目。
        """
        fm = app.state.file_manager
        root = fm.projects_root
        if not root.is_dir():
            return []
        out = []
        for p in root.iterdir():
            if not p.is_dir():
                continue
            sessions = p / "sessions"
            requirement, mode, has_state = "", "safe", False
            task_state = sessions / "task_state.json"
            if task_state.is_file():
                try:
                    meta = json.loads(task_state.read_text(encoding="utf-8"))
                    requirement = str(meta.get("requirement", ""))
                    has_state = True
                except (OSError, ValueError):
                    pass
            pipeline_state = sessions / "pipeline_state.json"
            if pipeline_state.is_file():
                has_state = True
                if not requirement:
                    try:
                        requirement = str(json.loads(
                            pipeline_state.read_text(encoding="utf-8"),
                        ).get("requirement", ""))
                    except (OSError, ValueError):
                        pass
                try:
                    mode = json.loads(
                        pipeline_state.read_text(encoding="utf-8")
                    ).get("mode", "safe")
                except (OSError, ValueError):
                    pass
            tokens = 0
            report = p / "logs" / "cost_report.json"
            if report.is_file():
                try:
                    tokens = int(json.loads(
                        report.read_text(encoding="utf-8"),
                    ).get("total_tokens", 0))
                except (OSError, ValueError):
                    pass
            try:
                updated = time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime),
                )
            except OSError:
                updated = ""
            out.append({
                "project_id": p.name,
                "requirement": requirement,
                "mode": mode,
                "has_state": has_state,
                "interrupted": (sessions / "interruption.md").is_file(),
                "tokens": tokens,
                "updated": updated,
            })
        out.sort(key=lambda x: x["updated"], reverse=True)
        return out

    @app.post("/api/resume")
    def resume(req: ResumeRequest) -> dict:
        """续跑中断任务（问题 4：磁盘重建，已完成模块跳过）。"""
        if app.state.file_manager.get_project(req.project_id) is None:
            raise HTTPException(404, f"项目不存在: {req.project_id}")
        # 按快照 mode 构造执行器
        mode = _project_mode(req.project_id)
        pipeline = _pipeline(mode)
        try:
            # M8-2：同一项目串行（防与并发 feedback 重建现场竞争）
            with app.state.lock_manager.acquire(req.project_id):
                result = _llm_call(pipeline.resume, req.project_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return _result_dict(result)

    @app.post("/api/project/{project_id}/feedback")
    def feedback(project_id: str, req: FeedbackRequest) -> dict:
        """单轮反馈（3.8）：成功词确认 / 报错修复 / exit 停止。

        经 Pipeline.resume 通道驱动（磁盘重建反馈环——服务重启不丢）。
        每次请求消费一条反馈；客户端循环调用直至确认或冻结。
        """
        if app.state.file_manager.get_project(project_id) is None:
            raise HTTPException(404, f"项目不存在: {project_id}")
        state = {"given": False}

        def one_shot(prompt: str) -> str:
            if state["given"]:
                return "exit"    # 本轮已消费一条 → 手动停止语义（下轮再调）
            state["given"] = True
            return req.message

        mode = _project_mode(project_id)
        pipeline = _pipeline(mode)
        try:
            # M8-2：同一项目串行（两次并发反馈不并发重建/写盘）
            with app.state.lock_manager.acquire(project_id):
                result = _llm_call(pipeline.resume, project_id, feedback_fn=one_shot)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return _result_dict(result)

    @app.get("/api/project/{project_id}/dashboard")
    def dashboard(project_id: str) -> dict:
        """成本看板（磁盘 logs/cost_report.json，8.5 审计口径）。"""
        handle = app.state.file_manager.get_project(project_id)
        if handle is None:
            raise HTTPException(404, f"项目不存在: {project_id}")
        report = handle.root / "logs" / "cost_report.json"
        if not report.is_file():
            raise HTTPException(404, "尚无成本报告（任务未产生调用）")
        return json.loads(report.read_text(encoding="utf-8"))

    @app.get("/api/project/{project_id}/messages")
    def project_messages(project_id: str) -> dict:
        """M11-2：方案讨论消息记录（对话流图数据源，只读）。

        数据为讨论产物落盘（sessions/discussion_messages.json，审计口径）；
        任务未到讨论完成 / 记录不存在 → 空列表（前端渲染占位）。
        """
        handle = app.state.file_manager.get_project(project_id)
        if handle is None:
            raise HTTPException(404, f"项目不存在: {project_id}")
        messages_file = handle.root / "sessions" / "discussion_messages.json"
        if not messages_file.is_file():
            return {"project_id": project_id, "messages": []}
        try:
            messages = json.loads(messages_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            messages = []  # 记录损坏不阻塞前端（返回空 + 占位渲染）
        if not isinstance(messages, list):
            messages = []
        return {"project_id": project_id, "messages": messages}

    # ------------------------------------------------------------------
    # 生成代码只读访问（M1-4：插件 diff 预览与应用）
    # ------------------------------------------------------------------

    @app.get("/api/project/{project_id}/files")
    def project_files(project_id: str) -> dict:
        """生成代码清单（只读）：code/ 与 tests/ 下的相对路径。"""
        if app.state.file_manager.get_project(project_id) is None:
            raise HTTPException(404, f"项目不存在: {project_id}")
        files = (
            app.state.file_manager.list_files(project_id, "code")
            + app.state.file_manager.list_files(project_id, "tests")
        )
        return {"project_id": project_id, "files": files}

    @app.get("/api/project/{project_id}/file")
    def project_file(project_id: str, path: str) -> dict:
        """单文件内容（只读）。仅开放 code/ 与 tests/ 前缀——
        sessions/logs 等内部目录不暴露；路径逃逸由 FileManager 校验。"""
        if app.state.file_manager.get_project(project_id) is None:
            raise HTTPException(404, f"项目不存在: {project_id}")
        if not (path.startswith("code/") or path.startswith("tests/")):
            raise HTTPException(400, f"仅允许访问 code/ 与 tests/ 下的文件: {path!r}")
        content = app.state.file_manager.read_file(project_id, path)
        if content is None:
            raise HTTPException(404, f"文件不存在: {path}")
        return {"path": path, "content": content}

    return app


def _sse(event: dict) -> str:
    """M8-4：单帧 SSE 文本（data 行 + 空行）。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _llm_call(fn, *args, **kwargs):
    """LLM 调用统一兜底：异常转 503 JSON（进程存活，客户端可提示）。

    典型场景：MissingApiKeyError（密钥未配置）——不应崩溃整个服务。
    """
    try:
        return fn(*args, **kwargs)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 —— 统一转可读错误响应
        raise HTTPException(503, f"LLM 调用失败: {exc}") from exc


app = create_app()   # uvicorn app.server:app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
