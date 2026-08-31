"""M2-4 资源配额测试：容器 CPU / 内存 / 磁盘 / 进程数限制，超限终止。

设计锚点（v0.4.md M2-4、config M2-4 注释）：
- 配额旗标：--memory(+--memory-swap 同值禁 swap) / --cpus / --pids-limit /
  tmpfs size（唯一可写目录 → 磁盘配额）；
- 超限终止语义：内核 OOM kill / pids 超限 → 容器 exit 137 → FAILED
  且 message 注明资源超限（不误报为普通测试失败）；
- None = 不加旗标（B6 行为完全不变）；工厂按 Settings 透传；
- 配额缺省开启（docker_mem_limit=512m 等，安全姿态宁严勿松）。

单元测试用 FakeDockerRunner（全封闭，不依赖 Docker）；live 测试
skipif 守护，仅在有 Docker 的环境验证真实 OOM 终止。
"""

from __future__ import annotations

import subprocess

import pytest

from app.config import Settings
from app.execution.docker_executor import DockerExecutor
from app.execution.executor import ExecutionStatus
from app.execution.factory import build_executor
from tests.test_docker_executor import FakeDockerRunner


def _make(**kw) -> tuple[DockerExecutor, FakeDockerRunner]:
    fake = FakeDockerRunner(**{k: v for k, v in kw.items()
                               if k in FakeDockerRunner.__init__.__code__.co_varnames})
    executor = DockerExecutor(
        image=kw.get("image", "python:3.11-slim"),
        network_enabled=kw.get("network_enabled", False),
        project_code_dir=kw.get("project_code_dir"),
        runner=fake,
        prober=lambda: fake.probe_ok,
        mem_limit=kw.get("mem_limit"),
        cpus=kw.get("cpus"),
        pids_limit=kw.get("pids_limit"),
        tmpfs_size=kw.get("tmpfs_size"),
    )
    return executor, fake


# ---------------------------------------------------------------------------
# 配额旗标组装
# ---------------------------------------------------------------------------

class TestQuotaFlags:
    def test_all_quota_flags_present(self):
        executor, fake = _make(
            mem_limit="512m", cpus=1.0, pids_limit=128, tmpfs_size="64m",
        )
        executor.run("x = 1\n", "", timeout=30, module="m")
        cmd = fake.calls_of("run")[0]
        assert cmd[cmd.index("--memory") + 1] == "512m"
        assert cmd[cmd.index("--memory-swap") + 1] == "512m"  # 禁 swap
        assert cmd[cmd.index("--cpus") + 1] == "1.0"
        assert cmd[cmd.index("--pids-limit") + 1] == "128"
        assert "/tmp:rw,noexec,nosuid,size=64m" in cmd  # 磁盘配额并入 tmpfs

    def test_none_means_no_quota_flags(self):
        """B6 兼容：全部 None → 不出现任何配额旗标。"""
        executor, fake = _make()
        executor.run("x = 1\n", "", timeout=30, module="m")
        cmd = fake.calls_of("run")[0]
        for flag in ("--memory", "--memory-swap", "--cpus", "--pids-limit"):
            assert flag not in cmd
        assert "/tmp:rw,noexec,nosuid" in cmd  # 原样（无 size 段）
        assert not any("size=" in part for part in cmd)

    def test_partial_quota(self):
        executor, fake = _make(mem_limit="256m")  # 仅内存
        executor.run("x = 1\n", "", timeout=30, module="m")
        cmd = fake.calls_of("run")[0]
        assert "--memory" in cmd
        assert "--cpus" not in cmd
        assert "--pids-limit" not in cmd


# ---------------------------------------------------------------------------
# 超限终止语义（exit 137）
# ---------------------------------------------------------------------------

class TestQuotaKillSemantics:
    def test_oom_exit_137_direct_run(self):
        executor, _ = _make(
            run_result=subprocess.CompletedProcess([], 137, stdout="", stderr="Killed"),
        )
        result = executor.run("x = []\nwhile True:\n    x.append(b'x' * 1024)\n",
                              "", timeout=30, module="m")
        assert result.status is ExecutionStatus.FAILED
        assert result.exit_code == 137
        assert "资源超限" in result.message
        assert "M2-4" in result.message

    def test_oom_exit_137_pytest_branch(self):
        executor, _ = _make(
            run_result=subprocess.CompletedProcess(
                [], 137, stdout="", stderr="Killed"),
        )
        result = executor.run("x = 1\n", "def test_x():\n    assert 0\n",
                              timeout=30, module="m")
        assert result.status is ExecutionStatus.FAILED
        assert "资源超限" in result.message  # 不误报为普通 pytest 失败

    def test_normal_failure_not_mislabeled(self):
        executor, _ = _make(
            run_result=subprocess.CompletedProcess([], 1, stdout="", stderr="boom"),
        )
        result = executor.run("raise SystemExit(1)\n", "", timeout=30, module="m")
        assert result.status is ExecutionStatus.FAILED
        assert "资源超限" not in result.message


# ---------------------------------------------------------------------------
# 配置校验与工厂透传
# ---------------------------------------------------------------------------

class TestQuotaConfigAndFactory:
    def test_defaults_valid_and_nonempty(self):
        s = Settings()  # 缺省即合法（配额缺省开启）
        assert s.docker_mem_limit == "512m"
        assert s.docker_cpus == 1.0
        assert s.docker_pids_limit == 128
        assert s.docker_tmpfs_size == "64m"

    def test_invalid_size_format_rejected(self):
        with pytest.raises(ValueError, match="docker 大小格式"):
            Settings(docker_mem_limit="512MB")
        with pytest.raises(ValueError, match="docker 大小格式"):
            Settings(docker_tmpfs_size="abc")

    def test_invalid_cpus_and_pids_rejected(self):
        with pytest.raises(ValueError, match="docker_cpus"):
            Settings(docker_cpus=0)
        with pytest.raises(ValueError, match="docker_pids_limit"):
            Settings(docker_pids_limit=8)

    def test_factory_passes_quota(self, monkeypatch):
        monkeypatch.setattr(DockerExecutor, "available", staticmethod(lambda: True))
        settings = Settings(docker_executor_enabled=True)
        executor = build_executor("auto", settings)
        assert executor.mem_limit == "512m"
        assert executor.cpus == 1.0
        assert executor.pids_limit == 128
        assert executor.tmpfs_size == "64m"


# ---------------------------------------------------------------------------
# live（有 Docker 的环境才执行：真实 OOM 终止验证）
# ---------------------------------------------------------------------------

docker_live = pytest.mark.skipif(
    not DockerExecutor.available(), reason="本机无 Docker（live 测试跳过）"
)


@docker_live
class TestQuotaLive:
    def test_memory_hog_killed_by_quota(self):
        """内存配额真实终止：256m 上限下吃 512m 必被 OOM kill。"""
        executor, _ = _make(mem_limit="256m")
        result = executor.run(
            "x = []\nwhile True:\n    x.append(b'x' * (1024 * 1024))\n",
            "", timeout=60, module="m",
        )
        assert result.status is ExecutionStatus.FAILED
        assert result.exit_code == 137
        assert "资源超限" in result.message
