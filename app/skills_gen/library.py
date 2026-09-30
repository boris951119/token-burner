# -*- coding: utf-8 -*-
"""刀M：生成规范 skill 库（GenSkill）——方法/呈现类幻觉的对症层。

设计定稿（INBOX-016 f7a386d，双边对齐）：
- **WHAT/HOW 分离**：逐字事实（要出现什么串、在哪个页面）走所有权
  checklist 注入（既有刀C 通道）；本库只放 HOW（呈现/装配规范）。
  skill 永不替代 checklist，checklist 不进 skill 槽。
- **每个 skill 必须配对机械闸**——没有闸的 skill 是许愿（提示词可被
  无视，v55-github 死文案字典已实证）。
- **反模式（永久清单）**：禁止把触发式文案升格为 home surface 必见
  ——那是 81bc 假修环的结构因；触发式缺口的闸是"非死字典"检查
  （B 档，后置），不是 GET / 常驻。
- **无对照红绿差的 skill 是负债**：入库即登记配对闸与实验协议，
  两跑无差则删 skill 留闸。

与平台 `skills/`（SDK 用法 skill）分离：本库服务**代码生成提示词**。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GenSkill:
    sid: str
    title: str
    triggers: tuple[str, ...]   # 题面关键词（小写匹配），命中才注入
    surface: str                # "all" | "ui" | "data" | "assembly"
    prompt: str                 # 硬规则文本（≤15 行；后排饥饿教训）
    gate: str                   # 配对闸 id（可追溯、可执行）
    enabled: bool = True        # 预注册纪律：无夹具红绿差不下发（下架留档）
    disabled_reason: str = ""


_S3_PROMPT = """\
- 题面引号内的 UI 文案（按钮名/报错/提示/链接名）必须以**服务端渲染的
  可见 HTML 文本**出现在页面上，逐字一致，禁止同义改写。
- 报错与校验提示渲染在**对应控件旁**（表单字段下方或旁边）。
- 触发式文案（校验失败、操作结果提示）：实现真实触发路径，文案必须在
  服务端模板源码中存在、动作后渲染于触发控件旁——**禁止**只写进 JS
  常量或字典、禁止 display:none/hidden 隐藏、禁止仅由 API 返回不落页面。
- **禁止**把多条需求的文案堆砌在无功能装饰页上充数（装饰性实现，
  评测按可见性断言必判红）。"""

# 注册表（宁少勿滥：每条都有 81bc/v55-github 级取证背书才入）
_REGISTRY: tuple[GenSkill, ...] = (
    GenSkill(
        sid="S3-contract-presentation",
        title="契约呈现规范",
        triggers=("workbook", "worksheet", "spreadsheet", "表格", "工作簿",
                  "sign in", "sign up", "repository", "登录", "注册",
                  "home page", "页面", "按钮", "表单", "web app"),
        surface="ui",
        prompt=_S3_PROMPT,
        gate="J'-runtime-html + K-decorative + 金丝雀sidecar",
        # 预注册裁决（09-29 夹具 A/B）：B-easy 5/5 vs 5/5（无 headroom）、
        # B-hard 0/5 vs 2/5（失效类被路由鲁棒性混淆，p≈0.44 不显著）、
        # A 修复 3/3@1.0轮 vs 3/3@2.0轮（无收益证据）→ 按"两跑无显著差
        # 则删 skill 留闸"下架；闸与机制保留，待真实 81bc 树判别实验。
        enabled=False,
        disabled_reason="无夹具红绿差支持（实验A/B 09-29，/tmp/skill_ab "
                        "协议与数据见 INBOX-016）；闸保留，skill 待判别力"
                        "夹具复测后再启用",
    ),
)


def detect_skills(requirement: str) -> list[GenSkill]:
    """题面关键词 → 命中的 skill（照抄 domain_kernels.detect_domains 路由模式）。"""
    text = (requirement or "").lower()
    if not text:
        return []
    return [s for s in _REGISTRY
            if s.enabled and any(t in text for t in s.triggers)]


def render_skills_summary(skills: list[GenSkill],
                          surface: str | None = None) -> str:
    """渲染注入块；surface 给定时按面过滤（None=全量）。空集返回空串。"""
    picked = [s for s in skills
              if surface is None or s.surface in ("all", surface)]
    if not picked:
        return ""
    parts = ["## 生成规范（skill，硬约束；配对闸见各条标注）"]
    for s in picked:
        parts.append(f"\n### {s.sid} · {s.title}［闸: {s.gate}］\n{s.prompt}")
    return "\n".join(parts)


_REQ_RE = re.compile(r"REQ-[\w.-]+")


def repair_directive(issue_text: str, requirement: str = "",
                     max_reqs: int = 5, checklists=None) -> str:
    """修复定向注入：红字 REQ 反查验收清单 → skill 全文 + 位置句下药。

    位置句来自 fact_surfaces（编译期宿主页标签），**不是**裸原则——
    裸原则会被解读成"塞进任意模板"（81bc 十一次误诊的直接教训）。
    触发式文案（behavior_expectations）按反模式口径出指令：实现触发
    路径 + 模板中存在 + 控件旁渲染，**不要求**常驻首页。
    无 REQ 命中 / 无清单 → 空串（零行为变化）。
    """
    if not issue_text or not requirement:
        return ""
    req_ids = list(dict.fromkeys(_REQ_RE.findall(issue_text)))[:max_reqs]
    if not req_ids:
        return ""
    if checklists is None:
        from app.acceptance_compile import compile_checklists_from_text

        checklists = compile_checklists_from_text(requirement)
    by_id = {c.req_id: c for c in checklists}
    blocks: list[str] = []
    for rid in req_ids:
        ck = by_id.get(rid)
        if ck is None:
            continue
        lines: list[str] = [f"- {rid}："]
        for fact, surfaces in list(ck.fact_surfaces.items())[:6]:
            hosts = "/".join(s for s in surfaces if s != "unknown") or "对应页面"
            lines.append(f"  - 「{fact}」须出现在 **{hosts}** 的对应控件旁，"
                         "服务端渲染可见")
        for fact in ck.behavior_expectations[:3]:
            lines.append(f"  - 「{fact}」是**操作后出现的反馈文案**：实现真实"
                         "触发路径，模板源码中存在、动作后渲染于触发控件旁"
                         "（无需常驻首页，禁止 JS 常量/隐藏）")
        if len(lines) > 1:
            blocks.append("\n".join(lines))
    if not blocks:
        return ""
    skills = detect_skills(requirement)
    body = render_skills_summary(skills, surface="ui")
    head = "## 本轮修复的呈现规范与位置指令（对红字需求强制）"
    tail = ("通用约束：修复只针对红字需求，禁止为让文案可见而堆砌装饰页"
            "或修改 tests/。")
    parts = [head] + ([body] if body else []) + blocks + [tail]
    return "\n".join(parts).replace(
        "## 生成规范（skill，硬约束；配对闸见各条标注）",
        "").strip()
