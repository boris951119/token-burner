"""执行器工厂（M2-1：按执行模式与 Docker 可用性构造执行器）。

降级链路（v0.4.md M2 关键设计决策）：
- safe → SafeExecutor（安全模式完全不受 Docker 依赖影响）；
- auto → docker_executor_enabled 且守护进程可用 → DockerExecutor（容器级）；
       否则 → LocalExecutor（进程级，缺省路径，不阻塞使用）。

替换 main.py / server.py 各自的 _build_executor 重复实现，
保证 CLI 与 API 的执行器构造口径一致。
"""

from __future__ import annotations

from app.config import Settings
from app.execution.docker_executor import DockerExecutor
from app.execution.executor import Executor
from app.execution.local_executor import LocalExecutor
from app.execution.safe_executor import SafeExecutor


def build_executor(
    mode: str, settings: Settings, language: str = "python"
) -> Executor:
    """3.6：按执行模式构造执行器（auto 按配置与可用性选容器/进程）。

    M2-5：language 为预热参数——缺省 python 行为不变；node 切换到
    Node.js 镜像（docker_node_image），供 v0.5 TS 支持时上游调用方启用。
    """
    if mode == "safe":
        return SafeExecutor()
    if mode != "auto":
        raise ValueError(f"执行模式必须为 safe 或 auto，当前: {mode!r}")
    if settings.docker_executor_enabled and DockerExecutor.available():
        return DockerExecutor(
            image=settings.docker_image,
            network_enabled=settings.docker_network_enabled,
            # M2-4：资源配额透传（配置校验已在 Settings 层完成）
            mem_limit=settings.docker_mem_limit,
            cpus=settings.docker_cpus,
            pids_limit=settings.docker_pids_limit,
            tmpfs_size=settings.docker_tmpfs_size,
            # M2-5：多语言镜像（node → node_image，python → image）
            language=language,
            node_image=settings.docker_node_image,
        )
    # M14-4：平台黑名单透传（windows 缺省拦 fcntl 等）
    return LocalExecutor(platform=settings.target_platform)
