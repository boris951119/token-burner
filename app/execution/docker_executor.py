"""Docker 容器执行器（规格 M2-1/M2-2/M2-3，Alpha v0.4）。

架构（M2-1 设计决策）：
- 继承 Executor 抽象——Dev/Test Agent 与编排层零感知模式差异；
- 文件传输：代码写宿主临时目录 → 卷挂载进容器 → 执行 → 读输出 → 清理；
- 危险操作预扫描沿用 LocalExecutor 同一道 AST 黑名单——容器隔离之外的
  确定性第一道防线（宁可误报，绝不放过）；
- 超时熔断：docker CLI 层 subprocess timeout；超时后显式 docker kill
  （客户端进程被杀时容器仍在运行，--rm 保证 kill 后自清理）。

安全策略（M2-3，进程级隔离升级到容器级）：
- --read-only：容器根文件系统只读；
- --tmpfs /tmp:rw,noexec,nosuid：唯一可写目录（pytest 临时文件）；
- --network none：默认无网络（docker_network_enabled 可配置放开）；
- --user 65534:65534：非 root（nobody）运行；
- 代码目录与项目 code/ 目录均以 :ro 只读挂载。

安全边界声明（第 19 章）：容器级隔离（文件系统/网络/用户），资源配额
（CPU/内存/磁盘）属 M2-4（P1）；镜像单 Python 起步，多语言镜像属 M2-5。

降级链路（工厂层保证，本类不负责）：Docker 不可用时由
build_executor 降级 LocalExecutor，不阻塞使用。
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable

from app.execution.executor import ExecutionResult, ExecutionStatus, Executor
from app.execution.local_executor import (
    _parse_pytest_summary,
    scan_dangerous,
)

# runner: (cmd, timeout) -> CompletedProcess；TimeoutExpired 表示超时
DockerRunner = Callable[..., subprocess.CompletedProcess]

_PULL_TIMEOUT_SECONDS = 600  # 首次拉取镜像的宽限上限（远大于执行熔断 30s）

# M2-5：node --test TAP 汇总行（--test-reporter 默认 spec → 显式 tap 可解析）
_TAP_LINE = re.compile(r"^# (pass|fail) (\d+)\s*$", re.MULTILINE)


def _default_runner(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )


def _default_probe() -> bool:
    """Docker 守护进程可用性探测（docker info，5s 上限）。"""
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=5,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _parse_node_tap(stdout: str) -> dict[str, int]:
    """M2-5：解析 node --test 的 TAP 汇总（与 pytest 解析同构输出）。"""
    counts = {"pass": 0, "fail": 0}
    for match in _TAP_LINE.finditer(stdout or ""):
        counts[match.group(1)] = int(match.group(2))
    return {"passed": counts["pass"], "failed": counts["fail"]}


class DockerExecutor(Executor):
    """自动验证模式的容器级执行器：预扫描 + 卷挂载 + 只读/无网/非 root。"""

    def __init__(
        self,
        image: str = "python:3.11-slim",
        network_enabled: bool = False,
        project_code_dir: Path | str | None = None,
        runner: DockerRunner | None = None,
        prober: Callable[[], bool] | None = None,
        mem_limit: str | None = None,
        cpus: float | None = None,
        pids_limit: int | None = None,
        tmpfs_size: str | None = None,
        language: str = "python",
        node_image: str = "node:20-slim",
        platform: str = "any",
    ):
        if language not in ("python", "node"):
            raise ValueError(
                f"language 仅支持 python / node（M2-5 预热），当前: {language!r}"
            )
        self.language = language
        # M14-4：交付目标平台（危险预扫描的平台黑名单口径）
        self.platform = platform
        # M2-5：node 运行时解析到 Node.js 镜像；python 保持原镜像不变
        self.image = node_image if language == "node" else image
        self.network_enabled = network_enabled
        self.project_code_dir = Path(project_code_dir) if project_code_dir else None
        self._runner = runner or _default_runner
        self._probe = prober or _default_probe
        # M2-4 资源配额（None = 不加旗标，B6 行为不变；工厂按配置透传）
        self.mem_limit = mem_limit
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.tmpfs_size = tmpfs_size

    @staticmethod
    def available() -> bool:
        """工厂层降级判定：Docker 守护进程是否可用。"""
        return _default_probe()

    def run(
        self,
        code: str,
        tests: str,
        timeout: int,
        expected_output: str = "",
        module: str = "",
    ) -> ExecutionResult:
        # 第一道防线：AST 危险预扫描（与 LocalExecutor 同一黑名单）。
        # M2-5 边界：黑名单是 Python AST——JS 源码 parse 失败会被静默放行
        #（语法错误交上层静态门禁），node 运行时的首道防线暂为容器级隔离
        #（只读 fs/无网/非 root）；JS 静态扫描属 v0.5 TS 支持范围。
        issues = scan_dangerous(code, tests, platform=self.platform)
        if issues:
            return ExecutionResult(
                status=ExecutionStatus.BLOCKED,
                exit_code=None,
                message="危险操作已拦截（未执行）: " + "; ".join(issues),
            )

        if not self._probe():
            # 工厂层应已降级；运行时守护进程消失 → 明确失败（不可静默回退
            # 到进程执行——安全姿态宁严勿松，交上层决策）
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                exit_code=None,
                message="Docker 守护进程不可用（容器执行无法进行）",
            )

        module_name = module or "_module_"
        started = time.time()
        # M2-5：node 运行时 → .js 文件 + 内置 test runner（无 npm install，
        # 容器无网也能跑）；python 保持 pytest 流程不变
        ext = "js" if self.language == "node" else "py"
        with tempfile.TemporaryDirectory(prefix="token_burner_docker_") as tmp:
            tmp_dir = Path(tmp)
            (tmp_dir / f"{module_name}.{ext}").write_text(code, encoding="utf-8")
            if tests.strip():
                (tmp_dir / f"test_{module_name}.{ext}").write_text(
                    tests, encoding="utf-8"
                )
                if self.language == "node":
                    argv = ["node", "--test", f"test_{module_name}.{ext}"]
                else:
                    argv = ["python", "-m", "pytest", f"test_{module_name}.{ext}",
                            "-q", "--no-header"]
            elif self.language == "node":
                argv = ["node", f"{module_name}.{ext}"]
            else:
                argv = ["python", f"{module_name}.{ext}"]

            self._ensure_image()
            try:
                proc = self._docker_run(tmp_dir, argv, timeout)
            except subprocess.TimeoutExpired:
                return ExecutionResult(
                    status=ExecutionStatus.TIMEOUT,
                    exit_code=None,
                    duration_ms=int((time.time() - started) * 1000),
                    message=f"容器执行超时（>{timeout}s 熔断，M2-2）",
                )

        duration = int((time.time() - started) * 1000)
        # M2-4：资源超限终止语义——内核 OOM kill / pids 超限 → 容器 exit 137
        #（128+SIGKILL）；此时不解析测试结果，直接 FAILED 并注明原因
        if proc.returncode == 137:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                exit_code=137, stdout=proc.stdout, stderr=proc.stderr,
                duration_ms=duration,
                message="容器资源超限被终止（exit 137：内存 OOM / 进程数超限，M2-4）",
            )
        if tests.strip():
            if self.language == "node":
                test_results = [_parse_node_tap(proc.stdout)]
                if proc.returncode == 0:
                    return ExecutionResult(
                        status=ExecutionStatus.SUCCESS,
                        exit_code=0, stdout=proc.stdout, stderr=proc.stderr,
                        test_results=test_results, duration_ms=duration,
                        message=f"node --test 通过（{test_results[0]['passed']} 项）",
                    )
                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
                    test_results=test_results, duration_ms=duration,
                    message="node --test 未通过",
                )
            test_results = [_parse_pytest_summary(proc.stdout)]
            if proc.returncode == 0:
                return ExecutionResult(
                    status=ExecutionStatus.SUCCESS,
                    exit_code=0, stdout=proc.stdout, stderr=proc.stderr,
                    test_results=test_results, duration_ms=duration,
                    message=f"pytest 通过（{test_results[0]['passed']} 项）",
                )
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
                test_results=test_results, duration_ms=duration,
                message="pytest 未通过",
            )

        if proc.returncode != 0:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
                duration_ms=duration, message="运行失败（非零退出码）",
            )
        if expected_output and expected_output not in proc.stdout:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
                duration_ms=duration,
                message=f"预期输出不匹配：期望包含 {expected_output!r}",
            )
        return ExecutionResult(
            status=ExecutionStatus.SUCCESS,
            exit_code=0, stdout=proc.stdout, stderr=proc.stderr,
            duration_ms=duration, message="容器内运行成功",
        )

    # ------------------------------------------------------------------

    def _docker_run(
        self, work_dir: Path, argv: list[str], timeout: float
    ) -> subprocess.CompletedProcess:
        """组装并执行 docker run（M2-3 安全旗标 + M2-4 资源配额集中在此）。"""
        name = f"token_burner_exec_{uuid.uuid4().hex[:12]}"
        tmpfs = "/tmp:rw,noexec,nosuid"
        if self.tmpfs_size:
            tmpfs += f",size={self.tmpfs_size}"  # M2-4：可写目录磁盘上限
        cmd = [
            "docker", "run", "--rm", "--name", name,
            "--read-only",                       # 根文件系统只读
            "--tmpfs", tmpfs,                    # 唯一可写目录（含磁盘配额）
            "--user", "65534:65534",             # 非 root（nobody）
            "-v", f"{work_dir}:/work:ro",        # 被测代码只读挂载
            "-w", "/work",
        ]
        if self.mem_limit:
            # M2-4：内存上限；memory-swap 同值 → 禁 swap（配额不可逃逸）
            cmd += ["--memory", self.mem_limit,
                    "--memory-swap", self.mem_limit]
        if self.cpus is not None:
            cmd += ["--cpus", str(self.cpus)]
        if self.pids_limit is not None:
            cmd += ["--pids-limit", str(self.pids_limit)]
        if self.project_code_dir and self.project_code_dir.is_dir():
            # 跨模块/_shared 依赖：项目 code/ 目录只读挂载（PYTHONPATH 解析）
            cmd += [
                "-v", f"{self.project_code_dir}:/code:ro",
                "-e", "PYTHONPATH=/code",
            ]
        if not self.network_enabled:
            cmd += ["--network", "none"]
        cmd += [self.image, *argv]

        try:
            return self._runner(cmd, timeout=timeout)
        except subprocess.TimeoutExpired:
            # 熔断：客户端进程被杀后容器仍在运行 → 显式 kill（--rm 自清理）
            try:
                self._runner(["docker", "kill", name], timeout=10)
            except Exception:
                pass  # kill 失败不影响超时结论；--rm/垃圾容器交给 docker gc
            raise

    def _ensure_image(self) -> None:
        """镜像就绪保障（M2-1 生命周期：本地缺失时拉取，仅首次代价）。"""
        probe = self._runner(
            ["docker", "image", "inspect", self.image], timeout=10
        )
        if probe.returncode == 0:
            return
        pull = self._runner(
            ["docker", "pull", self.image], timeout=_PULL_TIMEOUT_SECONDS
        )
        if pull.returncode != 0:
            raise RuntimeError(
                f"docker pull {self.image} 失败: {(pull.stderr or '').strip()[:200]}"
            )
