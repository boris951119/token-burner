# -*- coding: utf-8 -*-
"""自测闸环境退化（9/23 Linux 全真演练取证）：交付容器无 node 时，
旧实现先烧 token 生成 specs、再在 lint 处抛 FileNotFoundError 被上层
except 静默降级——钱花了、specs 全废、行为验收缺席且无从得知。
"""
import pytest

import app.utils.selftest_gate as sg


@pytest.fixture(autouse=True)
def _reset_probe():
    sg._node_probe = None
    yield
    sg._node_probe = None


def test_probe_reports_missing_node(monkeypatch):
    monkeypatch.setattr(sg.shutil, "which", lambda _name: None)
    assert "npx" in sg.node_unavailable_reason()


def test_probe_is_cached(monkeypatch):
    calls = []

    def fake_run(*a, **k):
        calls.append(1)
        raise RuntimeError("boom")

    monkeypatch.setattr(sg.shutil, "which", lambda _name: "/usr/bin/npx")
    monkeypatch.setattr(sg.subprocess, "run", fake_run)
    first = sg.node_unavailable_reason()
    assert "playwright 探测失败" in first
    assert sg.node_unavailable_reason() == first
    assert len(calls) == 1, "探测必须进程内只跑一次"


def test_gate_skips_before_spending_tokens(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("无 node 环境不得进入 specs 生成（烧 token）")

    monkeypatch.setenv("ARCBENCH_SELFTEST", "on")   # conftest 默认 off，需显式开闸
    monkeypatch.setattr(sg, "node_unavailable_reason",
                        lambda: "环境无 npx（node 未安装）")
    monkeypatch.setattr(sg, "ensure_selftests", boom)
    ok, report = sg.selftest_gate(tmp_path, "需求原文", settings=None)
    assert ok is False
    assert "自测闸跳过" in report and "npx" in report


def test_env_off_switch_still_first(tmp_path, monkeypatch):
    """ARCBENCH_SELFTEST=off 的关闭语义优先于环境探测（测试环境约定）。"""
    monkeypatch.setenv("ARCBENCH_SELFTEST", "off")
    monkeypatch.setattr(sg, "node_unavailable_reason",
                        lambda: (_ for _ in ()).throw(AssertionError))
    ok, report = sg.selftest_gate(tmp_path, "需求", settings=None)
    assert ok is False and "关闭" in report
