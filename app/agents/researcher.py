"""Researcher 角色（规格第 4 章，v0.5 Beta / M10）。

角色定位（4.1）：可选前置角色，在编程任务前按需激活，不属于固定团队编制。
v0.5 交付「用户提供资料注入」降级版（4.6）：用户粘贴文档片段，
系统完成结构化摘要（四段式：来源/版本/用法示例/已知坑点）与注入；
联网调研通道（M10-5）独立开关，后续灰度。

决策归属（总则 D.1）：
- 大模型：从资料中提炼摘要内容；
- 程序：JSON 契约与四段字段校验（sources/versions 非空强制——
  规格 19 章「调研结果可能有误 → 要求标注来源与版本」）、
  预算熔断、缓存命中、触发条件判定、注入前的数据边界治理。

成本控制（4.4）：
- 独立预算 research_budget（默认 20k），独立于任务总预算之外、
  经 llm.call_log 计入全局消耗日志；
- 研究结果缓存复用，键 = sha256(技术栈+API+版本+资料)——
  降级模式下资料是摘要的唯一来源，必须参与键；联网模式（M10-5）
  将改用纯三元组键。

失败方向单一：摘要生成失败 / 预算耗尽 / 校验不通过 → 返回 None
（研究跳过，任务继续），不阻塞主管线、不新增任务失败模式。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.tools.prompt_templates import RESEARCH_BRIEF_SYSTEM, RESEARCH_BRIEF_USER
from app.utils.parse import parse_json
from app.utils.untrusted import sanitize_untrusted

# ---------------------------------------------------------------------------
# 触发条件（4.5，量化）
# ---------------------------------------------------------------------------

# 条件②：主 LLM 评估 reason 标注陌生技术栈 → 程序确定性检测信号词。
# 仅在 research="auto" 时参与判定；"on" 为用户显式触发，无需检测。
_NOVEL_STACK_PATTERN = re.compile(
    r"陌生|新技术|不常见|冷门|小众|新框架|新库|新版本|前沿|未普及|较新"
)


@dataclass
class ResearchDecision:
    """触发判定结果（程序确定性职责，总则 D.1：激活决策归用户）。"""

    triggered: bool
    source: str = ""       # user | assessment
    stack: str = ""        # 缓存键与摘要定位用（需求截取）
    reason: str = ""


def should_research(
    requirement: str,
    route_reason: str,
    research_mode: str,
    researcher_enabled: bool,
) -> ResearchDecision:
    """触发判定（4.5 三条件的前两条；第三条「修复失败建议」在管线层）。

    research_mode（本次任务入参）：
    - "on"：用户显式指定需要调研（条件①）→ 直接触发；
    - "auto"：允许程序按条件②自动触发（评估 reason 命中陌生栈信号词）；
    - "off"（缺省）：不触发。

    前置：researcher_enabled 总开关关闭 → 一律不触发（回归保证）。
    """
    stack = requirement.strip()[:60]
    if not researcher_enabled:
        return ResearchDecision(triggered=False, stack=stack)
    if research_mode == "on":
        return ResearchDecision(
            triggered=True, source="user", stack=stack,
            reason="用户显式指定需要调研（4.5 条件①）",
        )
    if research_mode == "auto" and route_reason \
            and _NOVEL_STACK_PATTERN.search(route_reason):
        return ResearchDecision(
            triggered=True, source="assessment", stack=stack,
            reason=f"评估标注陌生技术栈（4.5 条件②）：{route_reason[:80]}",
        )
    return ResearchDecision(triggered=False, stack=stack)


# ---------------------------------------------------------------------------
# 四段式结构化摘要（4.2）
# ---------------------------------------------------------------------------

@dataclass
class ResearchBrief:
    """结构化技术摘要（来源/版本/用法示例/已知坑点）。"""

    sources: list[str] = field(default_factory=list)
    versions: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    pitfalls: list[str] = field(default_factory=list)

    def render(self) -> str:
        """渲染为注入文本（四段式 markdown）。"""
        parts = ["### 来源", *[f"- {s}" for s in self.sources],
                 "", "### 版本", *[f"- {v}" for v in self.versions],
                 "", "### 用法示例", *[f"- {e}" for e in self.examples],
                 "", "### 已知坑点", *[f"- {p}" for p in self.pitfalls]]
        return "\n".join(parts)

    def to_json(self) -> str:
        return json.dumps({
            "sources": self.sources, "versions": self.versions,
            "examples": self.examples, "pitfalls": self.pitfalls,
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "ResearchBrief | None":
        """从缓存 JSON 反序列化；结构损坏返回 None（确定性校验）。"""
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
        return cls._validate(value)

    @classmethod
    def _validate(cls, value: Any) -> "ResearchBrief | None":
        """契约校验（程序确定性职责）：
        - 四键均为 list[str]（examples/pitfalls 允许空，宁缺毋编）；
        - sources/versions 强制非空（规格 19 章：标注来源与版本）。
        校验不通过返回 None（方向单一：视同无有效摘要）。
        """
        if not isinstance(value, dict):
            return None
        fields: dict[str, list[str]] = {}
        for name in ("sources", "versions", "examples", "pitfalls"):
            items = value.get(name)
            if not isinstance(items, list) \
                    or not all(isinstance(x, str) and x.strip() for x in items):
                return None
            fields[name] = [x.strip() for x in items]
        if not fields["sources"] or not fields["versions"]:
            return None
        return cls(**fields)


# ---------------------------------------------------------------------------
# 研究缓存（4.4：相同查询不重复消耗）
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS research (
    key TEXT PRIMARY KEY,
    brief TEXT NOT NULL,
    created_at REAL NOT NULL,
    tokens INTEGER NOT NULL DEFAULT 0
)
"""


def _cache_key(stack: str, api: str, version: str, material: str) -> str:
    """缓存键：sha256(技术栈+API+版本+资料)。

    三元组（4.4）+ 资料哈希——降级模式下资料是摘要的唯一事实来源，
    资料不同则摘要不同；联网模式（M10-5）资料由系统获取，可改纯三元组。
    """
    raw = f"{stack}\x00{api}\x00{version}\x00{material}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ResearchCache:
    """研究结果缓存（SQLite 单文件，与 embedding 缓存同构）。

    隐私口径与 M4 一致：键是哈希、值是摘要；用户资料原文不落盘
    （仅参与哈希运算）。摘要本身会在 sessions/research_brief.md
    留档（可审计要求），属于项目产物而非全局缓存。
    线程安全：内部互斥锁。
    """

    def __init__(self, db_path: Path | str, ttl_days: int = 7):
        self.ttl_seconds = max(0, ttl_days) * 86400
        self.hits = 0
        self.saved_tokens = 0
        self._lock = threading.Lock()
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def lookup(self, key: str) -> tuple[ResearchBrief | None, int]:
        with self._lock:
            row = self._conn.execute(
                "SELECT brief, created_at, tokens FROM research WHERE key=?",
                (key,),
            ).fetchone()
        if row is None:
            return None, 0
        brief_json, created_at, tokens = row
        if time.time() - created_at > self.ttl_seconds:
            # ttl_seconds=0 → 写入即过期（极端配置的确定性语义）
            with self._lock:
                self._conn.execute("DELETE FROM research WHERE key=?", (key,))
                self._conn.commit()
            return None, 0
        brief = ResearchBrief.from_json(brief_json)
        if brief is None:
            return None, 0
        self.hits += 1
        saved = int(tokens or 0)
        self.saved_tokens += saved
        return brief, saved

    def put(self, key: str, brief: ResearchBrief, tokens: int = 0) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO research VALUES (?, ?, ?, ?)",
                (key, brief.to_json(), time.time(), int(tokens)),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ---------------------------------------------------------------------------
# Researcher 角色
# ---------------------------------------------------------------------------

class Researcher:
    """Researcher：资料 → 四段式结构化摘要（独立预算 + 缓存复用）。"""

    def __init__(
        self,
        llm: Any,
        model: str,
        settings: Any,
        budget_guard: Any = None,
        cache: ResearchCache | None = None,
    ):
        self.llm = llm
        self.model = model
        self.settings = settings
        # 独立预算（4.4）：由调用方创建 BudgetGuard(research_budget)；
        # None = 不设限（测试便利），生产路径必须传入
        self.budget_guard = budget_guard
        self.cache = cache
        # 最近一次失败原因（可观测；成功时清空）
        self.last_error = ""

    # ------------------------------------------------------------------

    def generate_brief(
        self, material: str, stack: str = "", api: str = "",
        version: str = "",
    ) -> ResearchBrief | None:
        """资料 → 结构化摘要。

        顺序：缓存命中 → 直接复用（零调用零消耗）；
        未命中 → LLM 生成（独立预算内）→ 契约校验（失败重试 1 次）
        → 写缓存。

        失败方向单一：资料为空 / 预算耗尽 / 校验不通过 → 返回 None
        并在 last_error 留痕，研究跳过、任务继续。
        """
        self.last_error = ""
        if not material.strip():
            self.last_error = "研究资料为空，跳过研究"
            return None

        key = _cache_key(stack, api, version, material)
        if self.cache is not None:
            cached, _saved = self.cache.lookup(key)
            if cached is not None:
                return cached

        if self.budget_guard is not None:
            try:
                self.budget_guard.ensure_allowed()
            except Exception as exc:  # BudgetExceededError
                self.last_error = f"研究预算耗尽，跳过研究（{exc}）"
                return None

        for attempt in (1, 2):
            brief = self._one_pass(material, stack, api, version)
            if brief is not None:
                if self.cache is not None:
                    self.cache.put(key, brief, tokens=self._used_tokens)
                return brief
            if attempt == 1 and self.budget_guard is not None:
                try:
                    self.budget_guard.ensure_allowed()
                except Exception as exc:
                    self.last_error = f"研究预算耗尽，跳过研究（{exc}）"
                    return None
        self.last_error = self.last_error or "摘要契约校验连续两次不通过"
        return None

    # ------------------------------------------------------------------

    def _one_pass(
        self, material: str, stack: str, api: str, version: str
    ) -> ResearchBrief | None:
        """单次生成：LLM 调用 → JSON 解析 → 契约校验。

        资料（用户粘贴的第三方文本）属不可信输入——进入提示词前
        统一经数据边界治理（M7-6 同构，注入点为研究提示词）。
        """
        before = self._call_log_len()
        try:
            response = self.llm.chat(
                self.model,
                [
                    {"role": "system", "content": RESEARCH_BRIEF_SYSTEM},
                    {"role": "user", "content": RESEARCH_BRIEF_USER.format(
                        stack=stack or "（未指定）",
                        api=api or "（未指定）",
                        version=version or "（未指定）",
                        # M7-6：资料不可信，包裹数据边界后注入
                        material=sanitize_untrusted(material),
                    )},
                ],
                json_mode=True,
            )
        except Exception as exc:
            self.last_error = f"研究调用失败：{type(exc).__name__}: {exc}"
            return None
        self._record_usage(before)
        value, _detail = parse_json(response.content, location="research_brief")
        brief = ResearchBrief._validate(value)
        if brief is None:
            self.last_error = "摘要契约校验不通过（四段字段缺失或来源/版本为空）"
        return brief

    # ------------------------------------------------------------------

    def _call_log_len(self) -> int:
        return len(getattr(self.llm, "call_log", []) or [])

    def _record_usage(self, before: int) -> None:
        """独立预算记账：从 call_log 增量累计（计入全局日志，4.4）。

        测试桩无 call_log 时按 0 处理（预算不累计但不报错）。
        """
        self._used_tokens = sum(
            int(e.get("input_tokens", 0)) + int(e.get("output_tokens", 0))
            for e in (getattr(self.llm, "call_log", []) or [])[before:]
        )
        if self.budget_guard is not None and self._used_tokens:
            self.budget_guard.record(self._used_tokens)
