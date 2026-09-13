"""SWE-bench runner 回归测试(夜批 b1/b2 取证的缺陷防回潮)。

- ensure_family_env 接受 str envs_root(argparse 直传;曾 TypeError)
- 环境预检失败原因含 stderr(曾只看 stdout 得到空串)
- llm 闭包模型级回退链(备胎逐个尝试,全败才上抛)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import swebench_run  # noqa: E402


class TestEnsureFamilyEnv:
    def test_accepts_str_envs_root(self, tmp_path, monkeypatch):
        """b2 取证:argparse 传 str,Path 注解不自动转换曾 TypeError。"""
        import subprocess as sp

        def fake_run(*args, **kwargs):
            return sp.CompletedProcess(args, 0, stdout="", stderr="")

        monkeypatch.setattr(swebench_run.subprocess, "run", fake_run)
        # python.exe 已存在 → 不触发 conda create;pip 步骤已被上面的
        # monkeypatch 短路——本测试只验证 str→Path 转换与路径拼接逻辑
        fake_py = tmp_path / "envs" / "swebench_flask" / "python.exe"
        fake_py.parent.mkdir(parents=True)
        fake_py.write_text("", encoding="utf-8")
        name, py = swebench_run.ensure_family_env(
            "flask", "conda.exe", str(tmp_path / "envs"))
        assert name == "swebench_flask"
        assert py == str(fake_py)


class TestEnvPrecheckStderr:
    def test_failure_reason_includes_stderr(self, tmp_path, monkeypatch):
        """b1 取证:pytest 启动即崩时诊断全在 stderr,曾只看 stdout→空串。"""
        import subprocess as sp

        repo = tmp_path / "repo"
        repo.mkdir()

        def fake_run(cmd, **kwargs):
            if "--co" in cmd:  # 收集成功,节点在列
                return sp.CompletedProcess(cmd, 0,
                                           stdout="tests/a.py::t", stderr="")
            return sp.CompletedProcess(cmd, 1, stdout="",
                                       stderr="ModuleNotFoundError: x")

        monkeypatch.setattr(swebench_run.subprocess, "run", fake_run)
        ok, reason = swebench_run.env_precheck(repo, ["tests/a.py::t"], [], "py")
        assert not ok
        assert "ModuleNotFoundError" in reason, "stderr 必须进入失败原因"


class TestCanonicalizeP2P:
    def _patch_collect(self, monkeypatch, collected_lines):
        import subprocess as sp

        def fake_run(cmd, **kwargs):
            if "--co" in cmd:
                return sp.CompletedProcess(
                    cmd, 0, stdout="\n".join(collected_lines), stderr="")
            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(swebench_run.subprocess, "run", fake_run)

    def test_truncated_param_id_falls_back_to_function(self, tmp_path, monkeypatch):
        """b6 取证:P2P 参数化 ID 是官方 -v 输出按空白截断的伪影
        (`test[create_app2("foo",`)——精确节点收集不到,须退到函数级。"""
        repo = tmp_path / "repo"
        repo.mkdir()
        self._patch_collect(monkeypatch, [
            "tests/test_cli.py::test_locate_app[cliapp.app-None-testapp]",
            'tests/test_cli.py::test_locate_app[cliapp.factory-create_app2("foo", "bar")-x]',
            "tests/test_cli.py::test_other",
        ])
        ok, reason = swebench_run.env_precheck(
            repo,
            ['tests/test_cli.py::test_locate_app[cliapp.factory-create_app2("foo",',
             "tests/test_cli.py::test_other"],
            [], "py")
        assert ok, reason

    def test_genuinely_missing_node_still_fails(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        self._patch_collect(monkeypatch, ["tests/test_a.py::test_x"])
        ok, reason = swebench_run.env_precheck(
            repo, ["tests/test_a.py::test_gone"], [], "py")
        assert not ok
        assert "真缺失" in reason


class TestLlmFallbackChain:
    def _make_runner(self, monkeypatch, failures_by_model):
        """构造 run_instance 的 llm 闭包等价物:按模型记录失败。"""
        calls = []

        def chat(model, messages):
            calls.append(model)
            if model in failures_by_model:
                raise RuntimeError(f"degraded: {model}")
            return type("R", (), {"content": "ok"})()

        def llm(system, user, _chat=chat, _chain=None):
            messages = [{"role": "system", "content": system},
                        {"role": "user", "content": user}]
            chain = _chain or []
            for i, m in enumerate(chain):
                try:
                    return chat(m, messages).content
                except RuntimeError:
                    if i == len(chain) - 1:
                        raise
                    continue

        return llm, calls

    def test_fallback_on_primary_failure(self):
        """主模型退化 → 备胎接住;全部退化才上抛(b1 长挂烧 6023s 的根治)。"""
        llm, calls = self._make_runner(None, {"primary"})

        class _Chain:
            def __call__(self, system, user, _chain=None):
                return llm(system, user, _chain=["primary", "backup"])

        out = llm("s", "u", _chain=["primary", "backup"])
        assert out == "ok"
        assert calls == ["primary", "backup"]

    def test_all_degraded_raises(self):
        llm, _ = self._make_runner(None, {"primary", "backup"})
        with pytest.raises(RuntimeError):
            llm("s", "u", _chain=["primary", "backup"])


class TestChatResilientDeadline:
    """b9 取证：单实例 8396s——实例级硬顶到点必须立即拒绝。"""

    def _client(self, fail_models):
        class _R:
            content = "ok"

        class _C:
            def chat(self, model, messages):
                if model in fail_models:
                    raise RuntimeError(f"degraded: {model}")
                return _R()

        return _C()

    def test_deadline_exhausted_raises_before_calling(self):
        import swebench_run as sr

        called = []

        class _C:
            def chat(self, model, messages):
                called.append(model)
                raise RuntimeError("nope")

        with pytest.raises(RuntimeError, match="时间预算"):
            sr.chat_resilient(_C(), "m1", ["m2"], deadline=0.0,
                              messages=[])
        assert called == [], "deadline 已过不得发起任何调用"

    def test_chain_still_works_without_deadline(self):
        import swebench_run as sr

        out = sr.chat_resilient(self._client({"m1"}), "m1", ["m2"],
                                deadline=None, messages=[])
        assert out == "ok"

    def test_deadline_in_future_allows_call(self):
        import time as _t

        import swebench_run as sr

        out = sr.chat_resilient(self._client(set()), "m1", [],
                                deadline=_t.time() + 60, messages=[])
        assert out == "ok"
