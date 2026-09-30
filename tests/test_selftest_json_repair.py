# -*- coding: utf-8 -*-
"""自测批生成 JSON 解析降级：杂讯容忍（09-30 flash-0731 8 连败尸检）。"""
from __future__ import annotations

import json

import pytest

from app.utils.selftest_gate import _parse_gen_payload

GOOD = json.dumps({"tests": [{
    "req_id": "REQ-1-1-1", "name": "open",
    "code": "import { test, expect } from '@playwright/test';\n"
            "test('open', async ({ page }) => { await page.goto('/'); });",
}]})


def _spec_ok(cleaned):
    assert len(cleaned) == 1
    rid, name, code = cleaned[0]
    assert rid == "REQ-1-1-1" and "@playwright/test" in code


def test_plain_json_still_works():
    _spec_ok(_parse_gen_payload(GOOD))


def test_markdown_fence_stripped():
    _spec_ok(_parse_gen_payload(f"```json\n{GOOD}\n```"))


def test_prose_wrapped_json():
    # flash-0731 实录形态：前后带说明散文
    _spec_ok(_parse_gen_payload(f"好的，以下是测试：\n{GOOD}\n希望有帮助。"))


def test_trailing_comma_repaired():
    bad = ('{"tests": [{"req_id": "REQ-1-1-1", "name": "open", "code": '
           '"import { test, expect } from \'@playwright/test\';\\n'
           "test('open', async ({ page }) => { await page.goto('/'); });\"},]}")
    _spec_ok(_parse_gen_payload(bad))


def test_single_quote_keys_repaired():
    """结构位单引号（键/字符串定界符）→ 双引号；字符串内单引号原样保留。

    注意不可构造"值内含单引号且值也用单引号包裹"的用例——那不是
    JSON 的任何方言，边界不可判定（无条件状态机也不可解）。
    """
    bad = ('{\'tests\': [{\'req_id\': \'REQ-1-1-1\', \'name\': "open (it\'s ok)", '
           '\'code\': '
           '"import { test, expect } from \'@playwright/test\';\\n'
           "test('open', async ({ page }) => { await page.goto('/'); });\"}]}")
    cleaned = _parse_gen_payload(bad)
    _spec_ok(cleaned)
    assert "it's ok" in cleaned[0][1] or cleaned[0][1] == "open (it's ok)"


def test_garbage_raises():
    with pytest.raises(Exception):
        _parse_gen_payload("完全不是 JSON 的东西")
    with pytest.raises(Exception):
        _parse_gen_payload("")
