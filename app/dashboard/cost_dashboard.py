"""成本统计仪表盘（规格文档 8.5 节、11.0 节）。

session 级 token 明细（表 1 口径）：每次调用的 input/output、
按模型 / 环节聚合、预算对比与剩余、落盘 logs/cost_report.json。

环节归属（StageTracker）为纯程序规则：按 system 提示词首句分类，
零 LLM 参与（总则 D：校验与统计走程序）。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

# 环节关键词 → 环节名（按提示模板 system 首句的确定性规则）
_STAGE_RULES: list[tuple[str, str]] = [
    ("需求评估专家", "评估"),
    ("项目经理", "方案讨论"),
    ("架构师", "拆分接口"),
    ("开发工程师", "开发"),
    ("测试工程师", "测试"),
]


@dataclass
class CallRecord:
    """单次调用记录。"""

    model: str
    stage: str
    input_tokens: int
    output_tokens: int

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


class StageTracker:
    """环节归属：system 提示词 → 环节名（确定性，无 LLM）。"""

    @staticmethod
    def stage_of(system_hint: str) -> str:
        for keyword, stage in _STAGE_RULES:
            if keyword in system_hint:
                return stage
        return "其他"

    @staticmethod
    def from_messages(messages: list[dict]) -> str:
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        return StageTracker.stage_of(system)


class CostDashboard:
    """session 级成本仪表盘。"""

    def __init__(self, budget_tokens: int):
        self.budget_tokens = budget_tokens
        self.records: list[CallRecord] = []

    # ------------------------------------------------------------------

    def record(self, model: str, stage: str, input_tokens: int, output_tokens: int) -> None:
        self.records.append(
            CallRecord(model, stage, input_tokens, output_tokens)
        )

    @classmethod
    def from_call_log(cls, call_log: list[dict], budget_tokens: int) -> "CostDashboard":
        """从 ModelClient.call_log 构建（须含 system_hint，否则归「其他」）。"""
        dashboard = cls(budget_tokens=budget_tokens)
        for entry in call_log:
            dashboard.record(
                model=entry.get("model", "?"),
                stage=StageTracker.stage_of(entry.get("system_hint", "")),
                input_tokens=entry.get("input_tokens", 0),
                output_tokens=entry.get("output_tokens", 0),
            )
        return dashboard

    # ------------------------------------------------------------------

    @property
    def total_tokens(self) -> int:
        return sum(r.total for r in self.records)

    def by_model(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.records:
            out[r.model] = out.get(r.model, 0) + r.total
        return out

    def by_stage(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.records:
            out[r.stage] = out.get(r.stage, 0) + r.total
        return out

    def input_output_totals(self) -> dict[str, int]:
        return {
            "input": sum(r.input_tokens for r in self.records),
            "output": sum(r.output_tokens for r in self.records),
        }

    # 预算（11.0） -------------------------------------------------------

    def budget_remaining(self) -> int:
        return max(0, self.budget_tokens - self.total_tokens)

    def budget_used_ratio(self) -> float:
        if self.budget_tokens <= 0:
            return 1.0
        return self.total_tokens / self.budget_tokens

    def is_over_budget(self) -> bool:
        return self.total_tokens > self.budget_tokens

    # 输出 ----------------------------------------------------------------

    def text_summary(self) -> str:
        io = self.input_output_totals()
        lines = [
            "========== 成本统计（session 级） ==========",
            f"总 token: {self.total_tokens}（输入 {io['input']} / 输出 {io['output']}）",
            f"预算: {self.budget_tokens} | 已用 {self.budget_used_ratio():.1%} | "
            f"剩余 {self.budget_remaining()}{'（超支！）' if self.is_over_budget() else ''}",
            "",
            "按模型:",
        ]
        for model, tokens in self.by_model().items():
            lines.append(f"  {model}: {tokens}")
        lines.append("按环节:")
        for stage, tokens in self.by_stage().items():
            lines.append(f"  {stage}: {tokens}")
        return "\n".join(lines)

    def persist(self, directory: Path) -> Path:
        """落盘 logs/cost_report.json（8.5）。"""
        path = Path(directory) / "cost_report.json"
        payload = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "budget_tokens": self.budget_tokens,
            "total_tokens": self.total_tokens,
            "input_output": self.input_output_totals(),
            "by_model": self.by_model(),
            "by_stage": self.by_stage(),
            "calls": [
                {
                    "model": r.model,
                    "stage": r.stage,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                }
                for r in self.records
            ],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path
