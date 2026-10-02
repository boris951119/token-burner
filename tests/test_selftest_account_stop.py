# -*- coding: utf-8 -*-
"""自测批账户级 LLM 错误止损（96a4a9f157 + 5382e37bbf07 尸检）。

账户死透（余额耗尽/鉴权失效）时所有腿共享同一账户：换腿=再买一遍同一条
错误，重试轮=第三遍。96a4 实测 16 批×3 腿全灭还赔掉 28 节点自测覆盖；
新语义=批内首腿命中即抛 LLMAccountError、外层停批跳过重试轮、已落盘
specs 保留（部分覆盖 > 零覆盖），node-free 判分段照跑。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.utils.selftest_gate as sg


def _req_text(n: int) -> str:
    return ("## 模块 a\n"
            + "\n\n".join(f"### REQ-1-{i}\n需求 {i}" for i in range(1, n + 1))
            + "\n")


def _ok_payload(rid: str) -> str:
    code = ("import { test, expect } from '@playwright/test';\n"
            "test('t', async ({ page }) => { await page.goto('/'); });")
    return json.dumps({"tests": [{"req_id": rid, "name": "s", "code": code}]})


def _ok_payload_batch(n: int) -> str:
    return json.dumps({"tests": [
        {"req_id": f"REQ-1-{i}", "name": "s", "code":
         ("import { test, expect } from '@playwright/test';\n"
          "test('t', async ({ page }) => { await page.goto('/'); });")}
        for i in range(1, n + 1)]})


class _S:
    models = ["openai/qwen3.8-max", "openai/deepseek-v4-pro"]


def _fake_mc(monkeypatch, script: list):
    """script 逐次消费：Exception 抛出、str 作为成功响应内容。"""
    import app.utils.model_client as mcmod

    calls: list[str] = []

    class _MC:
        def __init__(self, settings):
            pass

        def chat(self, model, messages):
            calls.append(model)
            act = script.pop(0) if script else RuntimeError("no script")
            if isinstance(act, Exception):
                raise act
            return type("R", (), {"content": act})()

    monkeypatch.setattr(mcmod, "ModelClient", _MC)
    return calls


INSUFFICIENT = ("LLM 调用失败（openai/qwen3.8-max）: litellm.APIError: "
                "APIError: Error code: 402 - "
                "{'error': {'message': 'insufficient balance'}}")


@pytest.mark.parametrize("msg", [
    INSUFFICIENT,
    "LLM 调用失败（openai/glm-5.3-flash）: litellm.AuthenticationError: "
    "Error code: 401 - invalid api key",
    "LLM 调用失败（openai/glm-5.3-flash）: Arrearage: 账户已欠费",
    "LLM 调用失败（m）: 余额不足，请充值后重试",
])
def test_account_fatal_patterns(msg):
    assert sg._ACCOUNT_FATAL_RE.search(msg), msg


@pytest.mark.parametrize("msg", [
    "LLM 调用失败（m）: ReadTimeout: connection timed out",
    "LLM 调用失败（m）: APIError: Error code: 429 - rate limit",  # 限流可重试
])
def test_transient_patterns_not_fatal(msg):
    assert not sg._ACCOUNT_FATAL_RE.search(msg), msg


def test_first_call_account_fatal_stops_all_batches(tmp_path, monkeypatch):
    """9 节点=2 批：首批首腿账户死 → 后批不发、换腿不发、重试轮不发。"""
    calls = _fake_mc(monkeypatch, [RuntimeError(INSUFFICIENT)] * 99)
    monkeypatch.setattr(sg, "lint_specs", lambda *a, **k: 0)
    result = sg.ensure_selftests(tmp_path, _req_text(9), _S())
    assert result is None, "零 spec 落盘 → None（闸走 node-free 判分）"
    assert calls == ["openai/qwen3.8-max"], (
        f"止损失败，烧了 {len(calls)} 次调用: {calls}")


def test_account_fatal_midway_keeps_partial_specs(tmp_path, monkeypatch):
    """批 0 成功、批 1 账户死：已落盘 8 节点 specs 保留，不触发重试轮。"""
    script = [_ok_payload_batch(8)] + [RuntimeError(INSUFFICIENT)] * 99
    calls = _fake_mc(monkeypatch, script)
    monkeypatch.setattr(sg, "lint_specs", lambda *a, **k: 0)
    result = sg.ensure_selftests(tmp_path, _req_text(9), _S())
    assert result is not None and Path(result).is_dir()
    assert len(list(Path(result).glob("*.spec.ts"))) == 8
    assert len(calls) == 2, f"批 1 首腿即止损，实际调用 {calls}"


def test_transient_error_still_rotates_legs(tmp_path, monkeypatch):
    """瞬时错误（超时）不得误伤既有换腿接力：第二腿接住即成功。"""
    calls = _fake_mc(monkeypatch, [
        RuntimeError("LLM 调用失败（openai/qwen3.8-max）: ReadTimeout"),
        _ok_payload("REQ-1-1"),
    ])
    monkeypatch.setattr(sg, "lint_specs", lambda *a, **k: 0)
    result = sg.ensure_selftests(tmp_path, _req_text(1), _S())
    assert result is not None
    assert calls == ["openai/qwen3.8-max", "openai/deepseek-v4-pro"]
    assert list(Path(result).glob("*.spec.ts"))
