"""Executor 抽象层（规格文档 3.6.2 节、8.4 节、第 17 章第一阶段任务）。

统一接口：run(code, tests, timeout) -> ExecutionResult
- 安全审阅模式实现见 safe_executor.py（MVP）；
- 自动验证模式（本地进程）见 local_executor.py（Alpha v0.4）；
- 自动验证模式（Docker 容器）见 docker_executor.py（Alpha v0.4，M2）；
- 透明性原则：Dev / Test Agent 无需感知当前模式，仅依赖 ExecutionResult
  驱动后续流程（3.6.2）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ExecutionStatus(Enum):
    """执行状态（8.4 节）。

    语义：SKIPPED = 安全模式未执行；SUCCESS / FAILED = 沙箱执行结果；
    TIMEOUT = 触发 30s 熔断；BLOCKED = 高危操作被拦截（3.6.3）。
    """

    SKIPPED = "SKIPPED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    BLOCKED = "BLOCKED"


@dataclass
class ExecutionResult:
    """Executor 的统一返回结构（8.4 节）。"""

    status: ExecutionStatus
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    test_results: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    message: str = ""


class Executor(ABC):
    """执行器抽象接口：对上层 Agent 屏蔽安全 / 自动模式差异。"""

    # 自动验证模式：项目 code/ 目录（跨模块/_shared 依赖解析）；
    # 安全模式不用，保持接口一致
    project_code_dir: Path | None = None

    def bind_project_code_dir(self, path: Path | str) -> None:
        """M2：绑定项目 code/ 目录（Pipeline 在任务级调用）。"""
        self.project_code_dir = Path(path)

    @abstractmethod
    def run(
        self,
        code: str,
        tests: str,
        timeout: int,
        expected_output: str = "",
        module: str = "",
    ) -> ExecutionResult:
        """执行（或提示执行）给定代码与测试。

        Args:
            code: 待运行的代码内容（安全模式下用于生成运行指令说明）。
            tests: 可独立运行的测试文件内容（可为空）。
            timeout: 超时秒数（安全模式不实际使用，保持接口一致）。
            expected_output: 预期输出（安全模式下附于运行指令，降低手动验证成本）。
            module: 模块名（LocalExecutor 用于命名文件与依赖解析；
                SafeExecutor 忽略，接口向后兼容）。

        Returns:
            统一的 ExecutionResult。
        """
