"""项目级锁管理器（规格 M8-2：锁粒度从全局降到项目）。

文件写与 git 提交的竞争只发生在项目目录内，项目级互斥即可覆盖：
- 同一项目串行（防 /resume 与 /feedback 并发重建现场、并发写盘）；
- 不同项目完全并行（替换 server 全局 task_lock——旧锁把并发能力
  压成 1，M8 现状问题）。

锁实例按 project_id 惰性创建并常驻（数量以项目数为上界，本地
服务场景可忽略）；注册表自身的读写经一把元锁保护。
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from collections.abc import Iterator


class ProjectLockManager:
    """按项目 ID 的互斥锁注册表（with 语法使用）。"""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._registry_lock = threading.Lock()

    @contextmanager
    def acquire(self, project_id: str) -> Iterator[None]:
        """同一 project_id 串行进入；不同 project_id 互不阻塞。"""
        with self._registry_lock:
            lock = self._locks.setdefault(project_id, threading.Lock())
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    def is_locked(self, project_id: str) -> bool:
        """诊断辅助：项目锁当前是否被持有（非阻塞探测）。"""
        with self._registry_lock:
            lock = self._locks.get(project_id)
        return lock is not None and lock.locked()
