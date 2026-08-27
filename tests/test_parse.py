"""parse 单元测试（TDD 先行）。

依据：规格文档 v0.3.1 第 15 章输出容错：
- 15.1 四级解析降级：原生 json.loads → 提取 {...}/[...] 块 → 程序容错修复
  （补右括号、裸单引号、末尾逗号等，确定性零 token）→ 强制 JSON 响应
  （由 model_client 侧负责，parse 侧体现为解析前的提示记录）；
- 15.2 LLM 辅助修复默认关闭；
- 15.4 每次失败记录：触发位置、失败阶段、降级策略、最终结果；
- 15.5 对外暴露 parse_json(text) -> (value | None, detail)。
"""

from __future__ import annotations

import json

from app.utils.parse import ParseDetail, parse_json


class TestLevel1Native:
    def test_valid_json(self):
        value, detail = parse_json('{"a": 1}')
        assert value == {"a": 1}
        assert detail.strategy == "native"
        assert detail.success is True

    def test_valid_array(self):
        value, detail = parse_json("[1, 2, 3]")
        assert value == [1, 2, 3]
        assert detail.strategy == "native"


class TestLevel2ExtractBlock:
    def test_json_with_surrounding_text(self):
        # 常见：模型输出前后带说明文字
        text = '好的，以下是评估结果：\n{"difficulty_score": 7, "task_type": "编程"}\n以上。'
        value, detail = parse_json(text)
        assert value == {"difficulty_score": 7, "task_type": "编程"}
        assert detail.strategy == "extract_block"

    def test_code_fence_json(self):
        # 常见：模型用 ```json 围栏包裹
        text = '```json\n{"a": 1}\n```'
        value, detail = parse_json(text)
        assert value == {"a": 1}
        assert detail.strategy == "extract_block"

    def test_array_block_extracted(self):
        text = "结果如下：[\"x\", \"y\"] 完毕"
        value, detail = parse_json(text)
        assert value == ["x", "y"]
        assert detail.strategy == "extract_block"

    def test_innermost_complete_object(self):
        # 提取最外层完整块：外层 {...} 含嵌套时整体解析
        text = '前置说明 {"outer": {"inner": 1}} 后置说明'
        value, _ = parse_json(text)
        assert value == {"outer": {"inner": 1}}


class TestLevel3ProgrammaticRepair:
    def test_missing_closing_brace(self):
        # 补缺失右括号
        value, detail = parse_json('{"a": 1')
        assert value == {"a": 1}
        assert detail.strategy == "repair"

    def test_missing_closing_bracket(self):
        value, detail = parse_json('{"list": [1, 2')
        assert value == {"list": [1, 2]}
        assert detail.strategy == "repair"

    def test_trailing_comma(self):
        # 去除末尾逗号
        value, detail = parse_json('{"a": 1, "b": [1, 2,],}')
        assert value == {"a": 1, "b": [1, 2]}
        assert detail.strategy == "repair"

    def test_single_quotes(self):
        # 裸单引号替换为双引号
        value, detail = parse_json("{'a': '中文值'}")
        assert value == {"a": "中文值"}
        assert detail.strategy == "repair"

    def test_repair_disabled_by_flag(self):
        # 15.5：程序容错修复可配置关闭
        value, detail = parse_json('{"a": 1', programmatic_repair=False)
        assert value is None
        assert detail.success is False

    def test_surrounding_text_plus_errors(self):
        # 级 2 + 级 3 可叠加：先提取块再修复
        text = '说明 {"a": 1, 说明完毕'
        value, detail = parse_json(text)
        assert value == {"a": 1}
        assert detail.strategy == "repair"


class TestTotalFailure:
    def test_plain_text_returns_none(self):
        value, detail = parse_json("这不是 JSON")
        assert value is None
        assert detail.success is False
        assert detail.error is not None

    def test_empty_text(self):
        assert parse_json("")[0] is None
        assert parse_json("   \n")[0] is None

    def test_invalid_repaired_json_returns_none(self):
        # 修复后仍无法解析 → None（不抛异常，流程不卡死）
        value, detail = parse_json("{完全不合法")
        assert value is None
        assert detail.success is False


class TestObservability:
    """15.4：失败可观测——detail 记录触发位置与各阶段尝试。"""

    def test_detail_records_location(self):
        _, detail = parse_json("坏文本", location="difficulty_assessment")
        assert detail.location == "difficulty_assessment"

    def test_detail_default_location(self):
        _, detail = parse_json("{}")
        assert detail.location == ""

    def test_detail_records_error_on_failure(self):
        _, detail = parse_json("坏文本", location="x")
        assert "x" in detail.error or detail.error

    def test_detail_is_dataclass_with_required_fields(self):
        # 字段齐备：策略、成功标志、错误、位置
        d = ParseDetail(strategy="native", success=True, error=None, location="")
        assert d.strategy == "native"
        assert d.success is True


class TestEdgeCases:
    def test_nested_braces_unbalanced_inside_string(self):
        # 字符串内的花括号不应干扰提取
        text = '{"text": "包含 { 符号的内容"}'
        value, _ = parse_json(text)
        assert value == {"text": "包含 { 符号的内容"}

    def test_unicode_content(self):
        value, _ = parse_json('{"任务类型": "编程", "原因": "复杂"}')
        assert value["任务类型"] == "编程"

    def test_json_with_newlines(self):
        value, _ = parse_json('{\n  "a": 1\n}')
        assert value == {"a": 1}

    def test_level1_not_confused_by_whitespace_prefixed(self):
        # 前置空白不影响原生解析
        value, detail = parse_json('  {"a": 1}  ')
        assert value == {"a": 1}
        assert detail.strategy == "native"

    def test_multiple_json_blocks_prefers_first(self):
        text = '{"a": 1} 中间文字 {"b": 2}'
        value, _ = parse_json(text)
        assert value == {"a": 1}
