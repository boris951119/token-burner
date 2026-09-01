"""异步任务管理器（规格 M8-3 提交+轮询 / M8-4 进度事件流 / M12-1 取消与僵尸清理）。

- submit() 立即返回 task_id，线程池执行（默认并发 4）；
- get() 查询状态：内存优先；服务重启后从项目 sessions/task_state.json
  恢复（与断点续跑同构，M8 设计决策「任务状态落盘」）；
- 进度事件源：Pipeline on_event（stage / module_done / project）与
  ModelClient on_call（tokens，经 Pipeline 转发）→ 双通道分发：
  订阅队列（SSE 实时推送）+ 状态落盘（轮询与重启恢复）；
- M12-1 任务取消：pending 立即取消（job 不执行）；running 协作式取消
  （cancel_flag 经 Pipeline 注入 BudgetGuard 检查点，抛 TaskCancelledError
  终止任务体，线程释放）；recover_zombies() 重启后清扫磁盘遗留的
  pending/running 状态（服务重启 → 僵尸标记 cancelled）。

线程模型：工作线程执行任务；状态变更经内部互斥锁；事件广播
put_nowait（订阅者消费过慢时丢弃进度帧——状态可经 GET 兜底）。
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from app.utils.budget import TaskCancelledError

_STATE_FILE = "task_state.json"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class TaskStatus(str, Enum):
    """任务终态机（M12-1：CANCELLED 正式启用）。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"   # 用户取消 / 僵尸清理（M12-1）

    @classmethod
    def terminal(cls) -> tuple["TaskStatus", ...]:
        return (cls.SUCCEEDED, cls.FAILED, cls.CANCELLED)


@dataclass
class TaskState:
    """单个异步任务的可观测状态（轮询 / SSE / 落盘共用）。"""

    task_id: str
    kind: str                       # run | resume | feedback
    status: TaskStatus
    requirement: str = ""
    project_id: str | None = None
    project_dir: str = ""           # 落盘位置（项目就绪后回填）
    stage: str = ""                 # 当前阶段（方案讨论/模块开发/…）
    tokens_used: int = 0
    error: str = ""
    result: dict | None = None      # 终态：_result_dict 序列化后的结果
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


class TaskManager:
    """任务注册表 + 线程池执行器 + 事件广播中枢。"""

    def __init__(self, projects_root: Path | str = "projects", max_workers: int = 4):
        self._projects_root = Path(projects_root)
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="token-burner-task"
        )
        self._tasks: dict[str, TaskState] = {}
        self._subscribers: dict[str, list[queue.Queue]] = {}
        self._cancel_flags: dict[str, threading.Event] = {}  # M12-1
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 提交与执行
    # ------------------------------------------------------------------

    def submit(
        self,
        kind: str,
        job_factory: Callable[[str], Callable[[], dict]],
        requirement: str = "",
        project_id: str | None = None,
        project_dir: str = "",
    ) -> str:
        """登记任务并投递线程池，立即返回 task_id（<200ms 语义）。

        job_factory(task_id) → job：task_id 先于任务体生成，供任务内
        构造 Pipeline 时挂接 on_event 进度回调。
        """
        task_id = uuid.uuid4().hex[:12]
        state = TaskState(
            task_id=task_id, kind=kind, status=TaskStatus.PENDING,
            requirement=requirement, project_id=project_id,
            project_dir=project_dir,
        )
        with self._lock:
            self._tasks[task_id] = state
            self._cancel_flags[task_id] = threading.Event()  # M12-1
        self._pool.submit(self._run, task_id, job_factory(task_id))
        return task_id

    # ------------------------------------------------------------------
    # 取消（M12-1）
    # ------------------------------------------------------------------

    def cancel_flag(self, task_id: str) -> threading.Event | None:
        """任务取消旗标（Pipeline 注入 BudgetGuard 检查点用）。"""
        with self._lock:
            return self._cancel_flags.get(task_id)

    def cancel(self, task_id: str) -> tuple[str, dict] | None:
        """取消任务（M12-1）。

        返回 (action, state_dict)：
        - immediate：pending → 立即置 CANCELLED（job 不执行）；
        - cooperative：running → 置取消旗标，任务体在下一检查点中止；
        - already_terminal：任务已终态，无法取消（调用方映射 409）。
        未知任务返回 None（调用方映射 404）。
        """
        with self._lock:
            state = self._tasks.get(task_id)
            if state is None:
                return None
            if state.status in TaskStatus.terminal():
                return "already_terminal", self._state_dict(state)
            if state.status is TaskStatus.PENDING:
                state.status = TaskStatus.CANCELLED
                state.error = "用户取消（任务未开始执行）"
                state.updated_at = _now()
                state_dict = self._state_dict(state)
                action = "immediate"
            else:
                flag = self._cancel_flags.get(task_id)
                if flag is not None:
                    flag.set()
                state.error = "用户取消（协作式中止，下一检查点生效）"
                state.updated_at = _now()
                state_dict = self._state_dict(state)
                action = "cooperative"
        if action == "immediate":
            self._persist(state)
            self._broadcast(task_id, {
                "type": "done", "status": TaskStatus.CANCELLED.value,
                "task_id": task_id, "error": state.error,
            })
        return action, state_dict

    def recover_zombies(self) -> int:
        """M12-1：服务重启后清扫僵尸任务（磁盘遗留 pending/running）。

        服务重启意味着旧任务线程已消失——磁盘上仍为 pending/running
        的状态即僵尸，统一标记 cancelled 并落盘。返回清理数量。
        """
        if not self._projects_root.is_dir():
            return 0
        cleaned = 0
        for state_file in self._projects_root.glob(f"*/sessions/{_STATE_FILE}"):
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("status") not in (
                TaskStatus.PENDING.value, TaskStatus.RUNNING.value,
            ):
                continue
            data["status"] = TaskStatus.CANCELLED.value
            data["error"] = "服务重启中断，任务标记取消（M12-1 僵尸清理）"
            data["updated_at"] = _now()
            try:
                state_file.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                cleaned += 1
            except OSError:
                continue
        return cleaned

    def _run(self, task_id: str, job: Callable[[], dict]) -> None:
        state = self._tasks[task_id]
        if state.status is TaskStatus.CANCELLED:
            # M12-1：排队期间被取消 → 跳过执行，直接确认终态
            self._broadcast(task_id, {
                "type": "done", "status": TaskStatus.CANCELLED.value,
                "task_id": task_id, "error": state.error,
            })
            self._cancel_flags.pop(task_id, None)
            return
        self._update(state, status=TaskStatus.RUNNING)
        self._broadcast(task_id, {"type": "status", "status": "running"})
        try:
            result = job()
        except TaskCancelledError as exc:
            # M12-1：协作式取消在检查点中止（中断现场已由管线落盘）
            self._set_cancelled(state, task_id, f"用户取消（协作式中止：{exc}）")
            self._cancel_flags.pop(task_id, None)
            return
        except Exception as exc:  # noqa: BLE001 —— 任务失败转终态（可观测）
            self._update(
                state, status=TaskStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )
            self._broadcast(task_id, {
                "type": "done", "status": TaskStatus.FAILED.value,
                "task_id": task_id, "error": state.error,
            })
            self._cancel_flags.pop(task_id, None)
            return
        with self._lock:
            flag = self._cancel_flags.get(task_id)
            cancelled_in_race = flag is not None and flag.is_set()
        if cancelled_in_race:
            # M12-1：取消请求与完成竞态 → 用户意图优先（结果作废）
            self._set_cancelled(state, task_id, "用户取消（与完成竞态，结果作废）")
            self._cancel_flags.pop(task_id, None)
            return
        with self._lock:
            state.result = result
            state.status = TaskStatus.SUCCEEDED
            state.updated_at = _now()
        self._persist(state)
        self._broadcast(task_id, {
            "type": "done", "status": TaskStatus.SUCCEEDED.value,
            "task_id": task_id, "result": result,
        })
        self._cancel_flags.pop(task_id, None)

    def _set_cancelled(self, state: TaskState, task_id: str, error: str) -> None:
        """M12-1：协作式取消终态（更新 + 落盘 + 广播）。"""
        self._update(state, status=TaskStatus.CANCELLED, error=error)
        self._broadcast(task_id, {
            "type": "done", "status": TaskStatus.CANCELLED.value,
            "task_id": task_id, "error": error,
        })

    # ------------------------------------------------------------------
    # 进度事件（Pipeline on_event / ModelClient on_call 汇入口）
    # ------------------------------------------------------------------

    def on_pipeline_event(self, task_id: str, kind: str, data: dict) -> None:
        """Pipeline 进度钩子汇入口：更新状态并广播。"""
        state = self._tasks.get(task_id)
        if state is None:
            return
        if kind == "stage":
            self._update(state, stage=str(data.get("stage", "")))
            payload = {"type": "stage", "stage": state.stage,
                       "tokens": state.tokens_used}
        elif kind == "project":
            self._update(
                state, project_id=data.get("project_id"),
                project_dir=str(data.get("project_dir", "")),
            )
            payload = {"type": "project", "project_id": state.project_id,
                       "tokens": state.tokens_used}
        elif kind == "tokens":
            with self._lock:
                state.tokens_used += int(data.get("tokens", 0))
                state.updated_at = _now()
            payload = {"type": "tokens", "tokens": state.tokens_used,
                       "model": data.get("model", "")}
        elif kind == "module_done":
            payload = {"type": "module_done", **data,
                       "tokens": state.tokens_used}
        else:
            payload = {"type": kind, **data}
        self._broadcast(task_id, payload)

    # ------------------------------------------------------------------
    # 查询（内存 → 磁盘）与订阅
    # ------------------------------------------------------------------

    def get(self, task_id: str) -> dict | None:
        """任务状态查询：内存优先；重启后从项目 sessions/ 恢复。"""
        with self._lock:
            state = self._tasks.get(task_id)
        if state is not None:
            return self._state_dict(state)
        return self._load_from_disk(task_id)

    def _load_from_disk(self, task_id: str) -> dict | None:
        if not self._projects_root.is_dir():
            return None
        for session_file in self._projects_root.glob(f"*/sessions/{_STATE_FILE}"):
            try:
                data = json.loads(session_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("task_id") == task_id:
                return data
        return None

    def subscribe(self, task_id: str) -> queue.Queue:
        """注册 SSE 订阅队列（断线重连 = 重新订阅 + 首帧全量快照）。"""
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._lock:
            self._subscribers.setdefault(task_id, []).append(q)
        return q

    def unsubscribe(self, task_id: str, q: queue.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(task_id, [])
            if q in subs:
                subs.remove(q)

    # ------------------------------------------------------------------
    # 内部：状态变更 / 落盘 / 广播
    # ------------------------------------------------------------------

    def _update(self, state: TaskState, **fields) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(state, key, value)
            state.updated_at = _now()
        self._persist(state)

    def _persist(self, state: TaskState) -> None:
        """状态落盘（M8-3：项目确定后写 sessions/task_state.json）。"""
        if not state.project_dir:
            return
        try:
            path = Path(state.project_dir) / "sessions" / _STATE_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self._state_dict(state), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass  # 落盘失败不影响任务（内存态仍可查询）

    @staticmethod
    def _state_dict(state: TaskState) -> dict:
        return {
            "task_id": state.task_id,
            "kind": state.kind,
            "status": state.status.value,
            "requirement": state.requirement,
            "project_id": state.project_id,
            "project_dir": state.project_dir,
            "stage": state.stage,
            "tokens_used": state.tokens_used,
            "error": state.error,
            "result": state.result,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
        }

    def _broadcast(self, task_id: str, event: dict) -> None:
        with self._lock:
            subs = list(self._subscribers.get(task_id, []))
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # 订阅者消费过慢：丢进度帧，状态可经 GET 兜底
