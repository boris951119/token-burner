# -*- coding: utf-8 -*-
"""负面断言抽取（刀P2）——题面"不该出现"约束 → 可判分事实。

官方题面 anatomy（10-01 官方图 1）：GIVEN 明文含"系统不能有什么数据"。
两类形态（题面实测）：
1. 值不预存在：`The username ... 'nora-demo' ... are not registered.` /
   `The team name 'mobile-team' is not yet used ...`
   → 应用不得把这些值当作已存在数据（预置账号/预占名单）；
2. 敏感信息不回显：`passwords must not be echoed on the page`
   → 响应体不得出现密码明文。

判分语义（acceptance_judge 侧消费，本模块只管抽取）：
- ("not_preexisting", 值)：该值不得在页面/存储中被呈现为已存在数据；
- ("not_echoed", 字段)：该敏感字段值不得出现在页面响应体。

实现要点：GIVEN 常把 token 罗列在前一句、触发词（are not registered 等）
在后一句——负面窗口=触发句+其前一句（两句内 token 全收）。
"""
from __future__ import annotations

import re

_TOKEN = re.compile(r"`([^`]+)`")
_NEGATIVE = re.compile(
    r"(?:are|is)\s+not\s+registered|not\s+yet\s+used|"
    r"do(?:es)?\s+not\s+exist|not\s+pre-?existing|尚未注册|不存在", re.I)
_ECHOED = re.compile(
    r"(passwords?|credentials?|tokens?)\s+must\s+not\s+be\s+"
    r"(?:echoed|displayed|shown|revealed)", re.I)
_SENTENCE = re.compile(r"[^.\n]+[.\n]")
_STOP = {"the", "and", "not", "yet", "used", "registered", "are", "is",
         "in", "that", "organization", "with", "test"}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.findall(text) if s.strip()]


def _tokens(sentence: str) -> list[str]:
    # 只收反引号 token——题面原文的值全部反引号标注（9/29 sheet 实测 +
    # stage-1 nora-demo 同款）；裸词抓取会混入普通单词（are/test 等）。
    return [_unquote(t.strip()) for t in _TOKEN.findall(sentence)
            if len(t.strip()) >= 3]


def _unquote(tok: str) -> str:
    tok = " ".join(tok.split())  # 跨句窗口带入的换行规整为空格
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "`'\"":
        return tok[1:-1]
    return tok


def _echo_fields(sentence: str) -> list[str]:
    m = _ECHOED.search(sentence)
    if not m:
        return []
    field = {"passwords": "password"}.get(m.group(1).lower(),
                                          m.group(1).lower())
    return [field]


def extract_negative_assertions(requirement: str) -> list[tuple[str, str]]:
    """需求文本 → [("not_preexisting"|"not_echoed", 值/字段), ...]。

    负面窗口=触发句及其前一句（GIVEN 的 token 罗列常在前句）。
    去重保序；无非空结果返回 []。
    """
    text = requirement or ""
    if not text:
        return []
    sentences = _sentences(text)
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _push(kind: str, value: str) -> None:
        key = (kind, value)
        if key not in seen:
            seen.add(key)
            out.append(key)

    joined = "\n".join(sentences)
    for sentence in sentences:
        for field in _echo_fields(sentence):
            _push("not_echoed", field)
    for m in _NEGATIVE.finditer(joined):
        # 触发词位置向前取 420 字符窗口；token 只从反引号对里收
        # （窗口外的不收；跨行闭合的反引号对换行去除）
        window = joined[max(0, m.start() - 420):m.end()]
        for tok in re.findall(r"`([^`]+)`", window, re.S):
            tok = tok.replace("\n", "")  # 跨行闭合的反引号对：换行不是内容
            if len(tok) >= 3:
                _push("not_preexisting", tok)
    return out
