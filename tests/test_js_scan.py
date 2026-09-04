"""M16-1 JS 静态危险扫描测试（v1.0 V2 批次）。

规格：scan_dangerous_js（require/import 黑名单 + eval 族 + node --check），
接入 LocalExecutor / DockerExecutor Node 链路。此前 JS 源码在 Python AST
扫描下静默放行（docker_executor 注释明示的技术债），node 运行时首道
防线只剩容器隔离。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.execution.local_executor import (  # noqa: E402
    LocalExecutor,
    scan_dangerous_js,
)
from app.execution.executor import ExecutionStatus  # noqa: E402

node_available = pytest.mark.skipif(
    shutil.which("node") is None, reason="本机无 Node.js（node 执行测试跳过）"
)

CLEAN_JS = """\
const fs = require('fs');
const path = require('path');

function read_config(p) {
    return fs.readFileSync(p, 'utf-8');
}

module.exports = { read_config };
"""


# ---------------------------------------------------------------------------
# 静态黑名单（node_check=False 隔离语法核验）
# ---------------------------------------------------------------------------

class TestModuleBlacklist:
    @pytest.mark.parametrize("snippet", [
        "const cp = require('child_process');",
        'const cp = require("child_process");',
        "const cp = require('node:child_process');",
        "import cp from 'child_process';",
        "import 'child_process';",
        "const cp = await import('child_process');",
        "export { exec } from 'child_process';",
    ])
    def test_forbidden_modules_blocked(self, snippet):
        issues = scan_dangerous_js(snippet, node_check=False)
        assert any("child_process" in i for i in issues)

    @pytest.mark.parametrize("mod", ["net", "tls", "http", "https", "vm",
                                     "dns", "cluster", "worker_threads"])
    def test_network_and_dynamic_modules_blocked(self, mod):
        assert scan_dangerous_js(
            f"const m = require('{mod}');", node_check=False)

    def test_relative_and_builtin_ok(self):
        """相对路径 / 非黑名单内建模块（path/fs/node:test）放行。"""
        assert scan_dangerous_js(
            "const t = require('node:test');\n"
            "const u = require('./utils');\n"
            "const p = require('path');\n",
            node_check=False) == []


class TestEvalFamily:
    @pytest.mark.parametrize("snippet", [
        "const f = eval('1 + 1');",
        "const f = new Function('return 1');",
        "const f = Function('return 1');",
    ])
    def test_eval_family_blocked(self, snippet):
        assert any("动态执行" in i for i in
                   scan_dangerous_js(snippet, node_check=False))

    def test_eval_like_names_not_flagged(self):
        """reeval / myFunction 等形近词不误报。"""
        assert scan_dangerous_js(
            "const a = reeval(x);\nconst b = myFunction(y);\n",
            node_check=False) == []


class TestFsMethodsAndDynamicRequire:
    @pytest.mark.parametrize("snippet", [
        "fs.unlinkSync(p);",
        "fs.rmSync(p, { recursive: true });",
        "fs.rmdir(p);",
        "fs.rename(a, b);",
        "await fs.promises.unlink(p);",
    ])
    def test_destructive_fs_blocked(self, snippet):
        assert any("fs." in i for i in
                   scan_dangerous_js(snippet, node_check=False))

    def test_read_write_fs_ok(self):
        assert scan_dangerous_js(
            "const s = fs.readFileSync(p);\nfs.writeFileSync(p, s);\n",
            node_check=False) == []

    def test_dynamic_require_blocked(self):
        assert any("动态 require" in i for i in scan_dangerous_js(
            "const m = require(userInput);", node_check=False))

    def test_literal_require_ok(self):
        assert scan_dangerous_js(
            "const m = require('path');", node_check=False) == []


class TestCommentStripping:
    def test_line_comment_not_flagged(self):
        assert scan_dangerous_js(
            "// const cp = require('child_process');\n"
            "const a = 1;\n",
            node_check=False) == []

    def test_block_comment_not_flagged(self):
        assert scan_dangerous_js(
            "/* const vm = require('vm'); */\nconst a = 1;\n",
            node_check=False) == []

    def test_url_string_not_treated_as_comment(self):
        """字符串里的 // 不是注释（引号感知），内容完整保留。"""
        assert scan_dangerous_js(
            'const u = "http://example.com";\n', node_check=False) == []


class TestLabels:
    def test_code_and_tests_both_scanned(self):
        issues = scan_dangerous_js(
            "const a = 1;\n",
            "const cp = require('child_process');\n",
            node_check=False)
        assert any(i.startswith("测试") for i in issues)


# ---------------------------------------------------------------------------
# node --check 语法核验
# ---------------------------------------------------------------------------

class TestNodeCheck:
    def test_syntax_error_flagged_when_node_present(self):
        """宿主有 node：语法错误在执行前被确定性拦截。"""
        if shutil.which("node") is None:
            pytest.skip("本机无 Node.js")
        issues = scan_dangerous_js("function broken( {\n")
        assert any("node --check" in i for i in issues)

    def test_valid_code_passes_with_check(self):
        if shutil.which("node") is None:
            pytest.skip("本机无 Node.js")
        assert scan_dangerous_js(CLEAN_JS) == []

    def test_no_node_degrades_silently(self, monkeypatch):
        """宿主无 node：语法核验跳过（不因环境缺失阻塞，执行阶段兜底）。"""
        monkeypatch.setattr(shutil, "which", lambda _: None)
        assert scan_dangerous_js("function broken( {\n") == []


# ---------------------------------------------------------------------------
# LocalExecutor Node 链路
# ---------------------------------------------------------------------------

class TestLocalExecutorNode:
    def test_invalid_language_rejected(self):
        with pytest.raises(ValueError, match="language"):
            LocalExecutor(language="ruby")

    def test_dangerous_js_blocked_before_execution(self):
        """child_process 代码在执行前被拦截（BLOCKED，零子进程）。"""
        executor = LocalExecutor(language="node")
        result = executor.run(
            "const cp = require('child_process');\ncp.execSync('dir');\n",
            "", timeout=10, module="m",
        )
        assert result.status is ExecutionStatus.BLOCKED
        assert "child_process" in result.message

    def test_eval_js_blocked(self):
        executor = LocalExecutor(language="node")
        result = executor.run(
            "const x = eval('1+1');\n", "", timeout=10, module="m")
        assert result.status is ExecutionStatus.BLOCKED

    @node_available
    def test_clean_module_runs(self):
        executor = LocalExecutor(language="node")
        result = executor.run(
            "console.log('hello-js');\n", "", timeout=30, module="m")
        assert result.status is ExecutionStatus.SUCCESS
        assert "hello-js" in result.stdout

    @node_available
    def test_node_test_runner(self):
        executor = LocalExecutor(language="node")
        code = ("function add(a, b) {\n  return a + b\n}\n"
                "module.exports = { add }\n")
        tests = (
            "const test = require('node:test')\n"
            "const assert = require('node:assert')\n"
            "const { add } = require('./m')\n"
            "test('add', () => {\n  assert.strictEqual(add(1, 2), 3)\n})\n"
        )
        result = executor.run(code, tests, timeout=60, module="m")
        assert result.status is ExecutionStatus.SUCCESS, \
            f"stdout={result.stdout}\nstderr={result.stderr}"
        assert result.test_results[0]["passed"] >= 1

    @node_available
    def test_syntax_error_fails_not_blocked(self):
        """语法错误不 BLOCKED（非危险操作）→ 执行失败进修复循环。"""
        executor = LocalExecutor(language="node")
        result = executor.run(
            "function broken( {\n", "", timeout=30, module="m")
        assert result.status is ExecutionStatus.FAILED
        assert "语法" in result.stderr or "SyntaxError" in result.stderr


# ---------------------------------------------------------------------------
# DockerExecutor Node 链路（FakeDockerRunner，不依赖 Docker）
# ---------------------------------------------------------------------------

class TestDockerExecutorNodeScan:
    def _make(self, **kw):
        from tests.test_docker_executor import _make_executor

        return _make_executor(**kw)

    def test_dangerous_js_blocked_without_container(self):
        """node 链路危险 JS 在容器启动前被拦截（fake 无 run 调用）。"""
        executor, fake = self._make(language="node")
        result = executor.run(
            "const cp = require('child_process');\n", "",
            timeout=30, module="m")
        assert result.status is ExecutionStatus.BLOCKED
        assert fake.calls_of("run") == []

    def test_clean_js_runs_node_argv(self):
        """干净 JS 走 node --test / node argv（node_check 关闭不误拦）。"""
        tap = subprocess.CompletedProcess(
            [], 0, stdout="# pass 1\n# fail 0\n", stderr="")
        executor, fake = self._make(language="node", run_result=tap)
        result = executor.run(
            "function add(a, b) {\n  return a + b\n}\n",
            "const test = require('node:test')\n"
            "test('add', () => {})\n",
            timeout=30, module="m")
        assert result.status is ExecutionStatus.SUCCESS
        assert result.test_results[0]["passed"] == 1
        cmd = fake.calls_of("run")[0]
        assert cmd[-4:] == ["node", "--test", "--test-reporter=tap",
                            "test_m.js"]

    def test_clean_js_no_tests_runs_entry(self):
        executor, fake = self._make(language="node")
        result = executor.run(
            "console.log('hi');\n", "", timeout=30, module="m")
        assert result.status is ExecutionStatus.SUCCESS
        cmd = fake.calls_of("run")[0]
        assert cmd[-2:] == ["node", "m.js"]

    def test_python_path_unchanged(self):
        """python 链路仍走 AST 扫描（fcntl 平台拦截回归锚点）。"""
        executor, fake = self._make()
        result = executor.run(
            "import fcntl\n", "", timeout=30, module="m",
        )
        # docker_executor 缺省 platform="any"：fcntl 放行（平台检查在门禁链）
        assert result.status is ExecutionStatus.SUCCESS
        assert fake.calls_of("run")  # 真实走容器执行


class TestFactoryLanguagePassThrough:
    def test_local_executor_gets_language(self):
        from app.execution.factory import build_executor

        executor = build_executor("auto", Settings_for_test(), language="node")
        assert isinstance(executor, LocalExecutor)
        assert executor.language == "node"

    def test_default_language_python(self):
        from app.execution.factory import build_executor

        executor = build_executor("auto", Settings_for_test())
        assert isinstance(executor, LocalExecutor)
        assert executor.language == "python"


def Settings_for_test():
    from app.config import Settings

    return Settings(docker_executor_enabled=False)
