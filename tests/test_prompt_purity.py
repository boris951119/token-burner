# -*- coding: utf-8 -*-
"""随包提示词纯度回归（批次#46）。

取证链（全免费）：`app/prompts/write_code_system.md` 的「文案硬契约」段
原先拿官方 keep 题面的字面串当例子（"Take a note" / "Sprint goals" /
"Reminders"）。40 份已知交付里 3 份把这些串写进了**别的题目**的交付物：
- 06/14（bookstack 域：books/chapters/pages 表）→ 种子里凭空多出
  `INSERT INTO demo VALUES (1, 'Take a note')` 与 `create_book(..., "Take a note")`；
- 17（Q&A/booking 域）→ 直接长在渲染出的页面上：`<h1>Take a note</h1>`、
  `placeholder="Sprint goals"`。
官方 6 道题面 grep：这三个串只在 keep 的 requirements 里出现——也就是说
非 keep 题的需求里根本没有它们，模型唯一的来源就是随包提示词。

提示词是每次跑都必发的常量，所以这类污染的频次=100% 的暴露面，命中与否
只看模型当次是否肯抄。收口口径：提示词不给任何内容域示例串，需求原文是
唯一来源。
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "app" / "prompts"
sys.path.insert(0, str(ROOT))

# 题目专名（官方题面自有词汇）：出现在随包提示词里=跨题污染源。
# 只列区分度高的写法——"keep" 这种常用词不入表，否则假红一片。
TASK_PROPER_NOUNS = (
    "Take a note", "Sprint goals", "Reminders", "Google Keep",
    "BookStack", "PrestaShop", "StackOverflow", "Stack Overflow",
    "12306", "携程", "ShortLink", "Create a page",
)


def _all_prompt_text() -> list[tuple[str, str]]:
    out = []
    for p in sorted(PROMPTS.glob("*.md")):
        out.append((p.name, p.read_text(encoding="utf-8")))
    return out


class TestPromptPurity:
    def test_every_prompt_file_is_read(self):
        """扫描集不能是空的（目录改名/漏读会让本测试静默空过）。"""
        files = _all_prompt_text()
        names = {n for n, _ in files}
        assert len(files) >= 20, len(files)
        assert all(t.strip() for _, t in files), "存在空提示词文件"
        for must in ("write_code_system.md", "fix_code_system.md"):
            assert must in names, must

    def test_no_task_proper_nouns_in_shipped_prompts(self):
        hits = []
        for name, text in _all_prompt_text():
            low = text.lower()
            hits += [f"{name}: {noun}" for noun in TASK_PROPER_NOUNS
                     if noun.lower() in low]
        assert not hits, f"随包提示词含题目专名（跨题污染源）: {hits}"

    def test_copy_contract_names_no_example(self):
        """逐字契约段必须「只说类别、不给样本」——给样本就会被抄进代码。"""
        text = (PROMPTS / "write_code_system.md").read_text(encoding="utf-8")
        seg = text[text.index("【文案硬契约"):]
        assert not re.search(r"如\s*[\"“][A-Za-z]", seg), seg[:200]
        assert "需求原文是唯一来源" in seg, "没写明唯一来源，下次还会加例子"
        assert "逐字" in seg and "禁止翻译" in seg, "契约本体被删没了"

    def test_loader_still_reads_the_edited_prompt(self):
        """改的是外置 md：确认加载器拿到的是新文本（打包/路径漂移即失败）。"""
        from app.tools import prompt_templates
        assert "本段刻意不给任何文案示例" in prompt_templates.WRITE_CODE_SYSTEM
        assert "Take a note" not in prompt_templates.WRITE_CODE_SYSTEM
