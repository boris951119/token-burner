# -*- coding: utf-8 -*-
"""刀M GenSkill：路由纯函数 + 渲染 + 修复定向（TDD，用例先于实现）。

夹具从 81bc 死因倒推：触发式文案的呈现规范（S3）+ 修复红字反查位置句。
"""
from __future__ import annotations

from app.skills_gen import (
    detect_skills, render_skills_summary, repair_directive,
)

# 最小真实题面（sheet 任务 REQ-1-1-1 节选，引号事实 + home/editor 宿主短语）
_REQ_TEXT = """## 模块：ui_home
### REQ-1-1-1 View and Open a Workbook（验收标准）
Users view available workbooks on the workbook home page. Each record
displays "Last updated: 2026-09-29" and provides a link whose accessible
name is "Q3 Sales". After the user clicks the link, the editor displays
the same "Last updated: 2026-09-29".
- 场景：Open a workbook
GIVEN: The visitor starts at the application home page in a fresh browser
session. The evaluation seed contains the seeded workbook "Q3 Sales".
WHEN: The user opens the workbook home page and clicks the visible
"Q3 Sales" workbook entry.
THEN: The editor displays worksheet "Sheet1" and the workbook name
"Q3 Sales" beside the named control.
"""

_GITHUB_REQ = """### REQ-1-1-1 Sign in to GitHub（验收标准）
The sign-in page displays "Sign in to GitHub" and a link "Create an
account" on the sign-in page.
"""

_NON_UI_REQ = """Write a python function that sorts a list of numbers.
No UI, no web server, pure algorithm."""


def test_s3_detected_for_ui_requirements():
    for text in (_REQ_TEXT, _GITHUB_REQ):
        skills = detect_skills(text)
        assert [s.sid for s in skills] == ["S3-contract-presentation"]


def test_no_skill_for_non_ui_requirement():
    assert detect_skills(_NON_UI_REQ) == []


def test_render_summary_contains_rules_and_gate():
    out = " ".join(render_skills_summary(detect_skills(_REQ_TEXT)).split())
    assert "S3" in out and "契约呈现" in out
    assert "服务端渲染" in out          # 核心硬规则在场
    assert "JS 常量" in out             # 81bc 死因点名（空白归一后匹配）
    assert "runtime-html" in out        # 配对闸 id 可追溯


def test_render_filters_by_surface():
    skills = detect_skills(_REQ_TEXT)
    assert render_skills_summary(skills, surface="ui") != ""
    assert render_skills_summary(skills, surface="data") == ""   # S3=ui 不灌数据面
    assert render_skills_summary(skills, surface=None) != ""     # 不过滤=全量


def test_repair_directive_binds_positions_not_prose():
    """修复红字反查清单：skill 规范 + 每条 REQ 的位置句（防裸原则洗白）。"""
    failure = ('REQ-1-1-1 编译清单[种子文案] "Last updated" 未出现在'
               '入口可达页面')
    d = repair_directive(failure, _REQ_TEXT)
    assert "契约呈现" in d                      # skill 全文随药
    assert "REQ-1-1-1" in d                     # 定位到红字需求
    assert "home" in d.lower()                  # 位置句落到宿主页
    assert "操作后" in d or "触发" in d          # 触发式文案的呈现指令（反 81bc）


def test_repair_directive_empty_when_no_req_match():
    assert repair_directive("与需求无关的失败信息", _REQ_TEXT) == ""
    assert repair_directive("REQ-9-9-9 任意红字", _REQ_TEXT) == ""   # 清单无此节点
    assert repair_directive("REQ-1-1-1 红字", "") == ""              # 无题面
