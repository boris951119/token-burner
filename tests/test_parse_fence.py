"""JSON 围栏解析盲区测试（产品审计问题 6 修复，TDD 先行）。

问题：真实模型（尤其国产）常输出 markdown 围栏，块提取从首个 `{` 扫描
虽能容忍围栏，但常见损坏模式仍会失败——尤其是「围栏内截断 JSON +
围栏外续写文字」与「围栏围住了说明文字+JSON」的混合。

修复约定（第 2 级前置净化，零 LLM）：
- 显式剥除 ```json / ``` 围栏对（开启/闭合或只有开启）；
- 围栏内残缺（截断）时，截掉围栏闭合标记后的续写文字，
  交第 3 级补括号修复；
- 多个围栏块（模型先给说明再给 JSON）取含 `{`/`[` 的块。
"""

from __future__ import annotations

import pytest

from app.utils.parse import parse_json


class TestFencedJSON:
    def test_plain_fence_pair(self):
        # 标准 ```json 围栏对
        text = '```json\n{"a": 1}\n```'
        value, detail = parse_json(text)
        assert value == {"a": 1}
        assert detail.success

    def test_fence_with_prefix_suffix_text(self):
        # 前后缀说明 + 围栏
        text = '好的，以下是评估结果：\n```json\n{"score": 7}\n```\n以上。'
        value, _ = parse_json(text)
        assert value == {"score": 7}

    def test_truncated_json_inside_fence_with_trailing_text(self):
        # 核心盲区：围栏内 JSON 截断（无闭合括号）+ 围栏闭合后续写文字
        text = (
            "```json\n"
            '{"modules": [{"name": "user"}, {"name": "auth"'
            "\n```\n"
            "抱歉，输出被截断了，以上是部分模块。"
        )
        value, detail = parse_json(text)
        assert detail.success
        # 截断处补括号修复 → 最后一个完整元素保留
        assert isinstance(value, dict)
        names = [m["name"] for m in value["modules"]]
        assert "user" in names

    def test_unclosed_fence_only(self):
        # 只有开启围栏（模型忘了闭合）——尾部文字是 JSON 的一部分
        text = '```json\n{"a": [1, 2, 3]}\n'
        value, _ = parse_json(text)
        assert value == {"a": [1, 2, 3]}

    def test_text_fence_then_json_fence(self):
        # 两个围栏：第一个是说明（纯文字），第二个才是 JSON
        text = (
            "```text\n这里是分析说明\n```\n"
            '```json\n{"result": "ok"}\n```'
        )
        value, detail = parse_json(text)
        assert value == {"result": "ok"}

    def test_fence_language_variants(self):
        # 围栏语言标记变体：```JSON / ```json5 / 无标记 ```
        for fence in ("```JSON", "```json", "```", "``` json"):
            text = f"{fence}\n{{\"k\": \"v\"}}\n```"
            value, _ = parse_json(text)
            assert value == {"k": "v"}, f"围栏 {fence!r} 解析失败"

    def test_bare_json_still_native(self):
        # 无围栏裸 JSON 不受影响（第 1 级原生解析）
        value, detail = parse_json('{"a": 1}')
        assert value == {"a": 1}
        assert detail.strategy == "native"

    def test_fence_multiline_json(self):
        # 围栏内多行 JSON（真实输出常见格式）
        text = (
            "```json\n"
            "{\n  \"task_type\": \"编程\",\n"
            "  \"difficulty_score\": 6,\n"
            "  \"reason\": \"多模块系统\"\n"
            "}\n"
            "```"
        )
        value, _ = parse_json(text)
        assert value["task_type"] == "编程"
        assert value["difficulty_score"] == 6

    def test_nested_fence_truncated_array(self):
        # 围栏内截断的数组 + 围栏外续写
        text = "```json\n[1, 2, 3,\n```\n（截断）"
        value, detail = parse_json(text)
        assert detail.success
        assert value == [1, 2, 3]
