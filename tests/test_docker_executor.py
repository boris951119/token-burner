"""Docker 执行器测试（M2-1 架构 / M2-2 基础执行 / M2-3 安全策略）。

分层：
- 单元测试：注入 FakeDockerRunner，全封闭（不依赖 Docker）——
  安全旗标、pytest 解析、超时 kill、预扫描拦截、镜像拉取；
- 工厂测试：降级链路（缺省进程模式、Docker 开关与可用性组合）；
- live 测试：skipif 守护，仅在有 Docker 的环境执行（Linux/Docker Desktop）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.config import Settings
from app.execution.docker_executor import DockerExecutor, _parse_node_tap
from app.execution.executor import ExecutionStatus
from app.execution.factory import build_executor
from app.execution.local_executor import LocalExecutor
from app.execution.safe_executor import SafeExecutor


class FakeDockerRunner:
    """按 docker 子命令分流的可编程桩（记录全部调用）。"""

    def __init__(self, run_result: subprocess.CompletedProcess | None = None,
                 run_exc: Exception | None = None,
                 image_present: bool = True, probe_ok: bool = True):
        self.calls: list[tuple[list[str], float | None]] = []
        self.run_result = run_result or subprocess.CompletedProcess(
            [], 0, stdout="1 passed in 0.01s", stderr=""
        )
        self.run_exc = run_exc
        self.image_present = image_present
        self.probe_ok = probe_ok

    def __call__(self, cmd: list[str], timeout: float | None = None):
        self.calls.append((cmd, timeout))
        sub = cmd[1] if len(cmd) > 1 else ""
        if sub == "info":
            rc = 0 if self.probe_ok else 1
            return subprocess.CompletedProcess(cmd, rc, "24.0.7" if rc == 0 else "", "")
        if sub == "image":
            rc = 0 if self.image_present else 1
            return subprocess.CompletedProcess(cmd, rc, "", "")
        if sub == "run":
            if self.run_exc is not None:
                raise self.run_exc
            return self.run_result
        return subprocess.CompletedProcess(cmd, 0, "", "")  # kill / pull 等

    def calls_of(self, sub: str) -> list[list[str]]:
        return [cmd for cmd, _ in self.calls if len(cmd) > 1 and cmd[1] == sub]


def _make_executor(**kw) -> tuple[DockerExecutor, FakeDockerRunner]:
    fake = FakeDockerRunner(**{k: v for k, v in kw.items()
                               if k in FakeDockerRunner.__init__.__code__.co_varnames})
    executor = DockerExecutor(
        image=kw.get("image", "python:3.11-slim"),
        network_enabled=kw.get("network_enabled", False),
        project_code_dir=kw.get("project_code_dir"),
        runner=fake,
        prober=lambda: fake.probe_ok,  # 探测是零参调用（与 runner 签名不同）
        language=kw.get("language", "python"),
        node_image=kw.get("node_image", "node:20-slim"),
        mem_limit=kw.get("mem_limit"),
        cpus=kw.get("cpus"),
        pids_limit=kw.get("pids_limit"),
        tmpfs_size=kw.get("tmpfs_size"),
    )
    return executor, fake


# ---------------------------------------------------------------------------
# 单元：M2-3 安全旗标 / M2-2 执行语义
# ---------------------------------------------------------------------------

class TestDockerSecurityFlags:
    def test_run_command_has_all_security_flags(self):
        executor, fake = _make_executor()
        result = executor.run("def run():\n    return 1\n",
                              "def test_run():\n    assert True\n",
                              timeout=30, module="m")
        assert result.status is ExecutionStatus.SUCCESS
        cmd = fake.calls_of("run")[0]
        for flag in ("--read-only", "--user", "65534:65534",
                     "--tmpfs", "/tmp:rw,noexec,nosuid", "--network", "none"):
            assert flag in cmd, f"缺少安全旗标 {flag}"
        # 代码目录只读挂载 + 工作目录
        volumes = [cmd[i + 1] for i, part in enumerate(cmd) if part == "-v"]
        assert any(v.endswith(":/work:ro") for v in volumes)
        assert cmd[cmd.index("-w") + 1] == "/work"
        # 容器命名（超时 kill 依赖）+ --rm 自清理
        assert cmd[cmd.index("--name") + 1].startswith("token_burner_exec_")
        assert "--rm" in cmd
        # pytest 参数
        assert cmd[-6:] == ["python", "-m", "pytest", "test_m.py", "-q", "--no-header"]

    def test_network_enabled_omits_isolation(self):
        executor, fake = _make_executor(network_enabled=True)
        executor.run("x = 1\n", "", timeout=30, module="m")
        cmd = fake.calls_of("run")[0]
        assert "--network" not in cmd

    def test_project_code_dir_mounted_readonly(self, tmp_path):
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        executor, fake = _make_executor(project_code_dir=code_dir)
        executor.run("x = 1\n", "", timeout=30, module="m")
        cmd = fake.calls_of("run")[0]
        volumes = [cmd[i + 1] for i, part in enumerate(cmd) if part == "-v"]
        assert any(v.endswith(":/code:ro") for v in volumes)
        assert "PYTHONPATH=/code" in cmd


class TestDockerExecutionSemantics:
    def test_pytest_success_parsed(self):
        executor, _ = _make_executor()
        result = executor.run("x = 1\n", "", timeout=30, module="m")
        # FakeDockerRunner 默认 run 结果 stdout="1 passed"（有测试分支语义）
        executor2, fake2 = _make_executor()
        result2 = executor2.run(
            "def run():\n    return 1\n",
            "def test_run():\n    assert True\n",
            timeout=30, module="m",
        )
        assert result2.status is ExecutionStatus.SUCCESS
        assert result2.test_results == [{"passed": 1, "failed": 0}]

    def test_pytest_failure_maps_failed(self):
        executor, _ = _make_executor(
            run_result=subprocess.CompletedProcess(
                [], 1, stdout="1 failed", stderr="AssertionError")
        )
        result = executor.run("x = 1\n", "def test_x():\n    assert 0\n",
                              timeout=30, module="m")
        assert result.status is ExecutionStatus.FAILED
        assert result.test_results == [{"passed": 0, "failed": 1}]

    def test_direct_run_success_and_output_match(self):
        executor, _ = _make_executor(
            run_result=subprocess.CompletedProcess([], 0, stdout="hello", stderr="")
        )
        result = executor.run("print('hello')\n", "", timeout=30,
                              expected_output="hello", module="m")
        assert result.status is ExecutionStatus.SUCCESS

    def test_direct_run_output_mismatch(self):
        executor, _ = _make_executor(
            run_result=subprocess.CompletedProcess([], 0, stdout="other", stderr="")
        )
        result = executor.run("print('other')\n", "", timeout=30,
                              expected_output="hello", module="m")
        assert result.status is ExecutionStatus.FAILED
        assert "预期输出不匹配" in result.message

    def test_timeout_kills_container(self):
        executor, fake = _make_executor(
            run_exc=subprocess.TimeoutExpired(cmd=[], timeout=30)
        )
        result = executor.run("import time\ntime.sleep(60)\n", "",
                              timeout=30, module="m")
        assert result.status is ExecutionStatus.TIMEOUT
        assert "熔断" in result.message
        kills = fake.calls_of("kill")
        assert len(kills) == 1
        assert kills[0][2].startswith("token_burner_exec_")  # cmd[2] = 容器名

    def test_prescan_blocks_before_any_docker_call(self):
        executor, fake = _make_executor()
        result = executor.run("import socket\nsocket.socket()\n", "",
                              timeout=30, module="m")
        assert result.status is ExecutionStatus.BLOCKED
        assert fake.calls == []  # 未触碰 Docker

    def test_ensure_image_pulls_when_missing(self):
        executor, fake = _make_executor(image_present=False)
        executor.run("x = 1\n", "", timeout=30, module="m")
        pulls = fake.calls_of("pull")
        assert len(pulls) == 1
        assert pulls[0][2] == "python:3.11-slim"  # cmd[2] = 镜像名

    def test_unavailable_docker_fails_without_execution(self):
        executor, fake = _make_executor(probe_ok=False)
        result = executor.run("x = 1\n", "", timeout=30, module="m")
        assert result.status is ExecutionStatus.FAILED
        assert "Docker 守护进程不可用" in result.message
        assert fake.calls_of("run") == []


# ---------------------------------------------------------------------------
# 单元：M2-5 多语言镜像（Node.js 预热，v0.5 TS 支持基础）
# ---------------------------------------------------------------------------

_TAP_OK = "ok 1 - test_add\n# pass 3\n# fail 0\n"
_TAP_BAD = "not ok 1 - test_sub\n# pass 1\n# fail 2\n"


class TestNodeTapParsing:
    def test_tap_summary_parsed(self):
        assert _parse_node_tap(_TAP_OK) == {"passed": 3, "failed": 0}

    def test_tap_failure_counts(self):
        assert _parse_node_tap(_TAP_BAD) == {"passed": 1, "failed": 2}

    def test_empty_output_zeroed(self):
        assert _parse_node_tap("") == {"passed": 0, "failed": 0}
        assert _parse_node_tap(None) == {"passed": 0, "failed": 0}  # type: ignore[arg-type]


class TestDockerNodeLanguage:
    def test_invalid_language_rejected(self):
        with pytest.raises(ValueError, match="python / node"):
            DockerExecutor(language="ruby")

    def test_node_language_resolves_node_image(self):
        executor, _ = _make_executor(language="node")
        assert executor.image == "node:20-slim"

    def test_python_language_keeps_python_image(self):
        executor, _ = _make_executor(image="python:3.11-slim")
        assert executor.image == "python:3.11-slim"

    def test_node_direct_run_command(self):
        executor, fake = _make_executor(
            language="node",
            run_result=subprocess.CompletedProcess([], 0, stdout="hi", stderr=""),
        )
        result = executor.run("console.log('hi')\n", "", timeout=30, module="m")
        assert result.status is ExecutionStatus.SUCCESS
        cmd = fake.calls_of("run")[0]
        # cmd 尾部 = [镜像, *argv]：node 镜像 + 直接运行 .js
        assert cmd[-3:] == ["node:20-slim", "node", "m.js"]

    def test_node_test_command_uses_builtin_runner(self):
        executor, fake = _make_executor(
            language="node",
            run_result=subprocess.CompletedProcess([], 0, stdout=_TAP_OK, stderr=""),
        )
        result = executor.run(
            "function add(a, b) {\n  return a + b\n}\nmodule.exports = { add }\n",
            "const { add } = require('./m')\n"
            "const assert = require('node:assert')\n"
            "assert.strictEqual(add(1, 2), 3)\n",
            timeout=30, module="m",
        )
        assert result.status is ExecutionStatus.SUCCESS
        assert result.test_results == [{"passed": 3, "failed": 0}]
        assert "node --test 通过（3 项）" in result.message
        cmd = fake.calls_of("run")[0]
        # cmd 尾部 = [镜像, *argv]：node 镜像 + 内置 test runner
        assert cmd[-4:] == ["node:20-slim", "node", "--test", "test_m.js"]

    def test_node_test_failure_maps_failed(self):
        executor, _ = _make_executor(
            language="node",
            run_result=subprocess.CompletedProcess([], 1, stdout=_TAP_BAD, stderr=""),
        )
        result = executor.run("function sub() {\n  return 0\n}\n",
                              "assert.strictEqual(sub(1), 1)\n",
                              timeout=30, module="m")
        assert result.status is ExecutionStatus.FAILED
        assert result.test_results == [{"passed": 1, "failed": 2}]
        assert result.message == "node --test 未通过"

    def test_node_security_flags_unchanged(self):
        # M2-5 只换镜像与命令，M2-3/M2-4 隔离与配额旗标必须原样保留
        executor, fake = _make_executor(
            language="node", mem_limit="512m", cpus=1.0,
            pids_limit=128, tmpfs_size="64m",
            run_result=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        )
        executor.run("console.log(1)\n", "", timeout=30, module="m")
        cmd = fake.calls_of("run")[0]
        for flag in ("--read-only", "--user", "65534:65534", "--network", "none",
                     "--memory", "--memory-swap", "--cpus", "--pids-limit"):
            assert flag in cmd, f"node 容器缺少旗标 {flag}"

    def test_node_js_source_passes_prescan_without_crash(self):
        # M2-5 边界固化：JS 源码非 Python 语法 → 预扫描静默放行（不崩溃），
        # 首道防线为容器级隔离；JS 静态扫描属 v0.5 TS 支持范围
        executor, fake = _make_executor(
            language="node",
            run_result=subprocess.CompletedProcess([], 0, stdout="hi", stderr=""),
        )
        result = executor.run("const cp = require('child_process')\n",
                              "", timeout=30, module="m")
        assert result.status is ExecutionStatus.SUCCESS
        assert fake.calls_of("run") != []  # 放行到容器执行


class TestExecutorFactory:
    def test_safe_mode_never_docker(self):
        settings = Settings(docker_executor_enabled=True)
        assert isinstance(build_executor("safe", settings), SafeExecutor)

    def test_auto_defaults_to_local_process(self):
        # 缺省 docker_executor_enabled=False → 进程级（与 v0.3.1 行为一致）
        assert isinstance(build_executor("auto", Settings()), LocalExecutor)

    def test_auto_docker_enabled_but_unavailable_falls_back(self, monkeypatch):
        monkeypatch.setattr(DockerExecutor, "available", staticmethod(lambda: False))
        settings = Settings(docker_executor_enabled=True)
        assert isinstance(build_executor("auto", settings), LocalExecutor)

    def test_auto_docker_enabled_and_available_uses_container(self, monkeypatch):
        monkeypatch.setattr(DockerExecutor, "available", staticmethod(lambda: True))
        settings = Settings(docker_executor_enabled=True)
        executor = build_executor("auto", settings)
        assert isinstance(executor, DockerExecutor)
        assert executor.image == settings.docker_image

    def test_factory_default_language_is_python(self, monkeypatch):
        # M2-5：上游调用方未传 language → python 行为完全不变
        monkeypatch.setattr(DockerExecutor, "available", staticmethod(lambda: True))
        executor = build_executor("auto", Settings(docker_executor_enabled=True))
        assert isinstance(executor, DockerExecutor)
        assert executor.language == "python"
        assert executor.image == Settings().docker_image

    def test_factory_language_node_uses_node_image(self, monkeypatch):
        monkeypatch.setattr(DockerExecutor, "available", staticmethod(lambda: True))
        settings = Settings(docker_executor_enabled=True)
        executor = build_executor("auto", settings, language="node")
        assert isinstance(executor, DockerExecutor)
        assert executor.language == "node"
        assert executor.image == settings.docker_node_image

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValueError, match="safe 或 auto"):
            build_executor("wat", Settings())


# ---------------------------------------------------------------------------
# live（有 Docker 的环境才执行：Linux / Docker Desktop）
# ---------------------------------------------------------------------------

docker_live = pytest.mark.skipif(
    not DockerExecutor.available(), reason="本机无 Docker（live 测试跳过）"
)


@docker_live
class TestDockerLive:
    def test_hello_world_pytest_in_container(self, tmp_path):
        executor = DockerExecutor(project_code_dir=tmp_path)
        result = executor.run(
            "def add(a, b):\n    return a + b\n",
            "from m import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
            timeout=120, module="m",
        )
        assert result.status is ExecutionStatus.SUCCESS, \
            f"stdout={result.stdout}\nstderr={result.stderr}"

    def test_node_hello_world_in_container(self):
        # M2-5 live：node:20-slim 镜像 + 内置 test runner 闭环（首次会拉镜像）
        executor = DockerExecutor(language="node")
        result = executor.run(
            "function add(a, b) {\n  return a + b\n}\nmodule.exports = { add }\n",
            "const test = require('node:test')\n"
            "const assert = require('node:assert')\n"
            "const { add } = require('./m')\n"
            "test('add', () => {\n  assert.strictEqual(add(1, 2), 3)\n})\n",
            timeout=300, module="m",
        )
        assert result.status is ExecutionStatus.SUCCESS, \
            f"stdout={result.stdout}\nstderr={result.stderr}"
        assert result.test_results[0]["passed"] >= 1

    def test_timeout_fuse_in_container(self):
        executor = DockerExecutor()
        result = executor.run("import time\ntime.sleep(60)\n", "",
                              timeout=5, module="slow")
        assert result.status is ExecutionStatus.TIMEOUT

    def test_readonly_root_fs_blocks_writes_outside_tmp(self):
        # 只读根文件系统：写 / 前缀路径（非 /tmp）必须失败
        executor = DockerExecutor()
        code = (
            "import os\n"
            "try:\n"
            "    with open('/attack.txt', 'w') as f:\n"
            "        f.write('x')\n"
            "    print('WRITE_OK')\n"
            "except PermissionError:\n"
            "    print('WRITE_BLOCKED')\n"
        )
        result = executor.run(code, "", timeout=60, module="m")
        assert result.status is ExecutionStatus.SUCCESS
        assert "WRITE_BLOCKED" in result.stdout
        assert "WRITE_OK" not in result.stdout

    def test_no_network_by_default(self):
        # 容器无网络：连接外网地址必须快速失败（socket 被预扫描拦截前
        # 无法验证网络，这里用 os 层无法绕过——用 urllib 会被预扫描拦，
        # 故以 DNS 解析失败验证；预扫描拦截网络 API 属第一道防线）
        executor = DockerExecutor()
        code = (
            "import socket\n"
            "try:\n"
            "    socket.gethostbyname('example.invalid')\n"
            "    print('NET_OK')\n"
            "except OSError:\n"
            "    print('NET_BLOCKED')\n"
        )
        # socket 在黑名单 → 预扫描直接拦截（容器层是第二道防线）
        result = executor.run(code, "", timeout=30, module="m")
        assert result.status is ExecutionStatus.BLOCKED
