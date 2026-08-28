"""API server（client.html 契约的正式实现）。

薄 FastAPI 包装：交互层不含流程逻辑，全部编排经 Pipeline（与 CLI 同构）。
契约（与 client.html 中约定一致）：

  GET  /api/health                          → 探活（客户端 live 检测）
  POST /api/route      {requirement}        → 评估结果（展示用）
  POST /api/run        {requirement, models?, mode?, spec_confirm?,
                        confirmed_as_coding?, route?} → 完整执行
  GET  /api/resumable                       → 可恢复项目列表
  POST /api/resume      {project_id}        → 续跑（已完成模块跳过）
  POST /api/project/{id}/feedback {message} → 单轮反馈（经 resume 通道）
  GET  /api/project/{id}/dashboard          → 成本看板（磁盘 logs/）

设计要点：
- route 与 run 分离且 route 可回传（问题 5：复用评估，零重复调用）；
- 反馈闭环经 Pipeline.resume 磁盘重建（进程重启不丢现场）；
- 任务级互斥锁：共享 LLM 客户端的 budget_guard 不并发竞争；
- 长任务同步返回（MVP）：真实任务可能数分钟，客户端需容忍长响应。

启动：
  python -m app.server            # 默认 127.0.0.1:8000
  uvicorn app.server:app --port 8000
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings
from app.dashboard.cost_dashboard import CostDashboard
from app.execution.local_executor import LocalExecutor
from app.execution.safe_executor import SafeExecutor
from app.orchestrator import Route, RoutingResult, TaskRouter
from app.pipeline import Pipeline, PipelineResult
from app.tools.file_manager import FileManager
from app.utils.model_client import ModelClient


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
    }


def _result_dict(result: PipelineResult) -> dict:
    return {
        "kind": result.kind,
        "answer": result.answer,
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
) -> FastAPI:
    """构建 API 应用。参数注入供测试；缺省为生产配置。"""
    app = FastAPI(title="token-burner API", version="0.1.0")
    app.state.llm = llm or ModelClient(settings or Settings())
    app.state.settings = settings or Settings()
    app.state.file_manager = FileManager(
        projects_root=projects_root or (Path.cwd() / "projects")
    )
    app.state.executor = executor            # 测试注入；缺省按 mode 构造
    app.state.task_lock = threading.Lock()   # 任务级互斥（budget_guard 独占）

    def _pipeline(mode: str) -> Pipeline:
        executor_obj = app.state.executor or _build_executor(mode)
        return Pipeline(
            llm=app.state.llm, executor=executor_obj,
            settings=app.state.settings,
            file_manager=app.state.file_manager,
        )

    # ------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

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
        """需求评估（3.2 三分类路由）；结果可回传 /api/run 复用。"""
        router = TaskRouter(app.state.llm, app.state.settings.models[0],
                            app.state.settings)
        with app.state.task_lock:
            result = _llm_call(router.route, req.requirement)
        return _route_dict(result)

    @app.post("/api/run")
    def run(req: RunRequest) -> dict:
        """完整管线执行（同步长任务）。"""
        if req.mode not in ("safe", "auto"):
            raise HTTPException(400, f"mode 非法: {req.mode}")
        models = tuple(req.models) if req.models else tuple(
            app.state.settings.models[:3]
        )
        if len(models) != 3 or len(set(models)) != 3:
            raise HTTPException(400, "三个模型必须互异（规格 3.3）")
        route_obj = _route_from_dict(req.route) if req.route else None
        pipeline = _pipeline(req.mode)
        with app.state.task_lock:
            result = _llm_call(
                pipeline.run, req.requirement,
                confirmed_as_coding=req.confirmed_as_coding,
                models=models,
                mode=req.mode,
                spec_confirm=req.spec_confirm,
                route=route_obj,
            )
        return _result_dict(result)

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

    @app.post("/api/resume")
    def resume(req: ResumeRequest) -> dict:
        """续跑中断任务（问题 4：磁盘重建，已完成模块跳过）。"""
        if app.state.file_manager.get_project(req.project_id) is None:
            raise HTTPException(404, f"项目不存在: {req.project_id}")
        # 按快照 mode 构造执行器
        state_path = (
            app.state.file_manager.projects_root / req.project_id
            / "sessions" / "pipeline_state.json"
        )
        mode = "safe"
        if state_path.is_file():
            try:
                mode = json.loads(
                    state_path.read_text(encoding="utf-8")
                ).get("mode", "safe")
            except (OSError, ValueError):
                pass
        pipeline = _pipeline(mode)
        with app.state.task_lock:
            try:
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

        state_path = (
            app.state.file_manager.projects_root / project_id
            / "sessions" / "pipeline_state.json"
        )
        mode = "safe"
        if state_path.is_file():
            try:
                mode = json.loads(
                    state_path.read_text(encoding="utf-8")
                ).get("mode", "safe")
            except (OSError, ValueError):
                pass
        pipeline = _pipeline(mode)
        with app.state.task_lock:
            try:
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

    return app


def _build_executor(mode: str):
    """3.6：按执行模式构造执行器（与 CLI 一致）。"""
    if mode == "auto":
        return LocalExecutor()
    return SafeExecutor()


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
