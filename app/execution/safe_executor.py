"""安全审阅模式实现（规格文档 3.6.2 节、MVP 默认执行模式）。

行为：
- 不执行任何代码（第 19 章：安全模式不引入执行）；
- 返回 ExecutionResult(status=SKIPPED, message="请手动运行以下命令...")，
  附带完整运行指令与预期输出（3.6.2）；
- 生成可独立运行的测试文件时附带 pytest 运行指令（3.7 安全模式兼容）。
"""

from __future__ import annotations

from app.execution.executor import ExecutionResult, ExecutionStatus, Executor

_RUN_HEADER = (
    "安全模式：系统未执行任何代码，请手动运行以下命令并反馈结果（输入报错日志"
    "或运行输出，'exit' 结束）：\n"
)


class SafeExecutor(Executor):
    """安全审阅模式：AST 静态检查 + 用户手动运行反馈。"""

    def run(
        self,
        code: str,
        tests: str,
        timeout: int,
        expected_output: str = "",
        module: str = "",
    ) -> ExecutionResult:
        instructions = [_RUN_HEADER]
        instructions.append("1. 进入项目代码目录：cd projects/<项目目录>/code")
        instructions.append(
            "2. 运行模块程序：python -m <模块名>.<模块名>（如模块 user → python -m user.user）"
        )
        if tests.strip():
            instructions.append(
                "3. 回到项目根目录运行测试：python -m pytest tests/<模块名>/ -v"
            )
        if expected_output:
            instructions.append(f"预期输出：{expected_output}")

        return ExecutionResult(
            status=ExecutionStatus.SKIPPED,
            exit_code=None,          # 未执行，无退出码
            stdout="",               # 未执行，无输出
            stderr="",
            test_results=[],         # 真实运行结果由用户反馈（3.7）
            duration_ms=0,
            message="\n".join(instructions),
        )
