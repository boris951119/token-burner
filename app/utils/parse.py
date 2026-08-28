"""JSON 解析四级降级（规格文档第 15 章输出容错、第 17 章第一阶段任务）。

降级链路（15.1，由宽松到严格逐级尝试，命中即用）：
1. 原生解析：直接 json.loads；
2. 提取 JSON 块：从前后缀文本中提取最外层 {...}/[...] 块；
3. 程序容错修复（确定性、零 token，15.1 第 3 级）：
   补缺失右括号、裸单引号换双引号、去除末尾逗号；
4. 强制 JSON 响应属于 model_client 调用侧参数（response_format），
   本模块不做网络动作，仅在其失败后的文本上重跑 1~3 级。

15.2 LLM 辅助修复：默认关闭，由调用方（orchestrator）按配置自行接入，
本模块保持零 LLM 依赖。

对外接口（15.5）：
    parse_json(text) -> (value | None, ParseDetail)
ParseDetail 记录失败阶段、采用策略、错误信息（15.4 可观测性），
供 logs/ 落盘统计「哪些环节最易解析失败」。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

# 提取最外层 { } 或 [ ] 块（考虑字符串内的括号转义与嵌套）
_BLOCK_START = {"{", "["}

# markdown 围栏：```json / ```JSON / ``` 等语言标记变体（行首）
_FENCE_OPEN = re.compile(r"^[ \t]*```[ \t]*[A-Za-z0-9]*[ \t]*\n?", re.MULTILINE)
_FENCE_CLOSE = re.compile(r"^[ \t]*```[ \t]*$", re.MULTILINE)


@dataclass
class ParseDetail:
    """单次解析尝试的结果细节（15.4 可观测）。"""

    strategy: str          # native / extract_block / repair / failed
    success: bool
    error: str | None      # 最终失败原因（成功时为 None）
    location: str = ""     # 触发位置（如 difficulty_assessment / review / module_list）


def parse_json(
    text: str,
    location: str = "",
    programmatic_repair: bool = True,
) -> tuple[Any | None, ParseDetail]:
    """解析 LLM 输出文本中的 JSON。

    Args:
        text: 原始模型输出。
        location: 触发位置标识（用于失败统计，15.4）。
        programmatic_repair: 是否启用第 3 级程序容错修复（15.5 配置项）。

    Returns:
        (解析结果或 None, ParseDetail)
    """
    if not text or not text.strip():
        return None, ParseDetail("failed", False, "输入文本为空", location)

    # 第 1 级：原生解析
    value = _try_loads(text)
    if value is not _FAILED:
        return value, ParseDetail("native", True, None, location)

    # 第 2 级：剥离 markdown 围栏后提取 JSON 块（产品审计问题 6）
    unfenced = _strip_fences(text)
    block = _extract_outermost_block(unfenced)
    if block is not None:
        value = _try_loads(block)
        if value is not _FAILED:
            return value, ParseDetail("extract_block", True, None, location)

    # 第 3 级：程序容错修复（对提取块或净化文本修复后重试）
    if programmatic_repair:
        candidate = block if block is not None else unfenced
        repaired = _repair_common_damage(candidate)
        value = _try_loads(repaired)
        if value is not _FAILED:
            return value, ParseDetail("repair", True, None, location)
        # 提取块修复失败时，再试一次原文修复（块提取可能截断）
        if block is not None:
            repaired_raw = _repair_common_damage(unfenced)
            value = _try_loads(repaired_raw)
            if value is not _FAILED:
                return value, ParseDetail("repair", True, None, location)

    # 全部失败
    return None, ParseDetail(
        "failed",
        False,
        f"四级降级全部失败（位置: {location or '未知'}）: 文本前 80 字符 "
        f"{text[:80]!r}",
        location,
    )


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

_FAILED = object()  # 哨兵：区分「解析成功得到 None」与「解析失败」


def _try_loads(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return _FAILED


def _strip_fences(text: str) -> str:
    """剥离 markdown 围栏（第 2 级前置净化，产品审计问题 6）。

    处理模式：
    - 围栏对（```json ... ```）：去掉开闭标记；
    - 只有开启围栏：去掉开启标记（尾部内容保留，多为 JSON 本体）；
    - 围栏内 JSON 截断 + 围栏闭合后续写文字：闭围栏后的文字截掉
      （残缺块交第 3 级补括号修复）；
    - 多个围栏块：保留含 {/[ 的块（说明性围栏丢弃）。

    无围栏时原样返回（零开销路径）。
    """
    if "```" not in text:
        return text

    opens = list(_FENCE_OPEN.finditer(text))
    if not opens:
        # 围栏标记非行首（罕见）：不处理，走原逻辑
        return text

    # 按围栏切段：open 之后到下一个 open（或闭围栏/文末）为一段内容
    segments: list[str] = []
    for idx, match in enumerate(opens):
        content_start = match.end()
        # 段终点 = 下一个开启围栏位置
        content_end = (
            opens[idx + 1].start() if idx + 1 < len(opens) else len(text)
        )
        content = text[content_start:content_end]
        # 去掉本段内容末尾的闭围栏行（可能带后续换行前的空白）
        close = _FENCE_CLOSE.search(content)
        if close:
            content = content[: close.start()]
        segments.append(content.rstrip("\n"))

    # 取含 JSON 起始字符的段；否则取最长段（可能 JSON 里没有 {}？保守）
    json_segments = [s for s in segments if "{" in s or "[" in s]
    if json_segments:
        return "\n".join(json_segments)
    return max(segments, key=len) if segments else text


def _extract_outermost_block(text: str) -> str | None:
    """提取文本中最外层完整的 {...} 或 [...] 块。

    扫描时跳过字符串字面量内的括号（简单状态机），
    并使用栈匹配确保取到完整闭合块。
    """
    start = -1
    for i, ch in enumerate(text):
        if ch in _BLOCK_START:
            start = i
            break
    if start < 0:
        return None

    stack: list[str] = []
    in_string = False
    escape = False
    closer = {"{": "}", "[": "]"}

    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in _BLOCK_START:
            stack.append(ch)
        elif ch in closer.values():
            if stack and closer[stack[-1]] == ch:
                stack.pop()
                if not stack:
                    return text[start : i + 1]
            else:
                # 括号不匹配（如字符串外出现了孤立右括号），从头再找下一个块起点
                return _extract_outermost_block(text[start + 1 :])
    # 未闭合的残缺块：返回从起点到文末的部分块，
    # 交由第 3 级程序容错修复补齐括号（15.1：补缺失右括号）
    if stack:
        return text[start:]
    return None


# 末尾逗号：}] 或 ], 或 ,} 等右侧多余逗号
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")

# 裸单引号键或值（不含字符串内单引号场景的简单启发式：
# 仅当整个文本不含双引号键时才整体替换，避免误伤）
_SINGLE_QUOTED_KEY = re.compile(r"(?<!\\)'([^']*)'")


def _repair_common_damage(text: str) -> str:
    """程序容错修复（15.1 第 3 级，确定性、零 token）。

    修补顺序：裸单引号 → 末尾逗号 → 残缺块尾逗号后非法残余 → 缺失右括号。
    """
    candidate = text.strip()

    # 裸单引号 → 双引号：仅当没有双引号包裹的键时启用整体替换（保守启发式）
    if "'" in candidate and '"' not in candidate:
        candidate = _SINGLE_QUOTED_KEY.sub(r'"\1"', candidate)

    # 去除末尾逗号
    candidate = _TRAILING_COMMA.sub(r"\1", candidate)
    candidate = re.sub(r",\s*$", "", candidate)

    # 括号不平衡（残缺块）时：截断顶层最后一个逗号后的非法残余，
    # 再去掉悬挂逗号（如 '{"a": 1, 说明完毕' → '{"a": 1'）
    if _is_unbalanced(candidate):
        candidate = _strip_garbage_after_last_top_level_comma(candidate)
        candidate = _TRAILING_COMMA.sub(r"\1", candidate)
        candidate = re.sub(r",\s*$", "", candidate)

    # 补缺失的右括号（按栈深逐个补齐）
    candidate = _close_unbalanced_brackets(candidate)

    return candidate


# JSON 值的合法起始字符（数字、负号、字符串、容器、true/false/null）
_VALUE_START = set('-0123456789" {[tfn')


def _is_unbalanced(text: str) -> bool:
    stack: list[str] = []
    in_string = False
    escape = False
    closer = {"{": "}", "[": "]"}
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in _BLOCK_START:
            stack.append(ch)
        elif ch in closer.values():
            if stack:
                stack.pop()
    return bool(stack)


def _strip_garbage_after_last_top_level_comma(text: str) -> str:
    """截断顶层最后一个逗号之后的非法残余内容。

    仅当残余不以 JSON 值起始字符开头时才截断（确定性判定），
    例：'{"a": 1, 说明完毕' → '{"a": 1'。
    """
    last_comma = -1
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in _BLOCK_START:
            depth += 1
        elif ch in ("}", "]"):
            depth -= 1
        elif ch == "," and depth >= 1:
            last_comma = i
    if last_comma < 0:
        return text
    rest = text[last_comma + 1 :].strip()
    if rest and rest[0] not in _VALUE_START:
        return text[:last_comma]
    return text


def _close_unbalanced_brackets(text: str) -> str:
    stack: list[str] = []
    in_string = False
    escape = False
    closer = {"{": "}", "[": "]"}
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in _BLOCK_START:
            stack.append(ch)
        elif ch in closer.values():
            if stack:
                stack.pop()
    # 栈中剩余即缺失的闭合括号
    return text + "".join(closer[c] for c in reversed(stack))
