"""单任务 token 总预算闸门（规格文档 11.0 节，六层护栏第 0 层总闸）。

确定性程序护栏（总则 D.1：程序只承担校验与边界兜底，不参与决策）：
- 已用 ≥ 预算 × throttle_threshold（默认 90%）→ 省 token 模式（throttling），
  由编排层压缩讨论轮数、跳过非必要比对；
- 已用 ≥ 预算 → 超预算（exceeded），立即中止该任务并落盘
  「已完成部分 + 未完成清单 + 已耗 token」，交用户决定续跑或止损。

用量数据源：LLM 客户端在每次调用后 record()（input + output）。

活动护栏槽（2026-09-20 平台双跑取证）：验证/修复通道的零散 ModelClient
（auto_repair 等自建实例）不经过工厂接线，曾整体绕过预算护栏——
双题双跑各超支 3 倍+（7.0M/6.2M vs budget=2M，¥210 学费）。
管线创建护栏后在此登记，零散客户端兜底接入，堵住无上限失血。
"""

from __future__ import annotations

from typing import Callable


class BudgetExceededError(RuntimeError):
    """任务 token 总预算耗尽（11.0：立即中止，落盘交用户）。"""


class TaskCancelledError(RuntimeError):
    """任务被用户取消（M12-1 协作式取消：检查点抛出，任务体终止）。"""


_active_guard: "BudgetGuard | None" = None


def set_active_budget_guard(guard: "BudgetGuard | None") -> None:
    """登记当前任务的活动护栏（管线创建护栏时调用一次）。"""
    global _active_guard
    _active_guard = guard


def get_active_budget_guard() -> "BudgetGuard | None":
    """零散 ModelClient 兜底数据源：未显式接线时复用活动护栏。"""
    return _active_guard


def size_aware_budget(
    n_requirements: int,
    base: int = 800_000,
    per_requirement: int = 20_000,
    cap: int = 3_500_000,
) -> int:
    """按题面需求条数折算单任务 token 信封（48h 官方任务用）。

    总闸此前只有「配置里写死的数」这一个来源，而官方容器不带 config.json，
    于是生效值是代码缺省 200k（自动模式 ×2.5 = 500k）。9/23 全真彩排实测：
    四需求的最小一道题光生成+验收就烧到 518k——预算低于最小可完成成本时，
    撞墙的不是质量而是修复（三轮 LLM 修复全部瞬时抛在同一行「预算已耗尽」上，
    一步没走、墙钟照烧，最后交出一份明知是坏的交付）。故信封必须跟着题面
    体量走，并且留出验收+修复段。

    标定（9/23 用本地 8 份官方题面实测，n 取 ATOMIC 需求数，冒号后为历次
    真实跑完的总用量 / 信封对其倍率）：keep 32 条 537k → 2.7x，bookstack
    34 条 1.19M → 1.2x，stackoverflow 66 条 587k → 3.6x。固定项远大于变动
    项（最小一道题就要 518k），故基数取「已知最小完成成本」上浮一档，每条
    需求再加一线索的修复量；上限按最重一道题（ctrip 125 条）折算，超过即
    说明该题已超出单任务信封，宁可带着已完成部分交付也不追平顶格。
    """
    try:
        n = max(0, int(n_requirements))
    except (TypeError, ValueError):
        n = 0
    return int(min(cap, max(base, base + per_requirement * n)))


class BudgetGuard:
    """单任务预算护栏：累计用量 + 阈值判定 + 超限拦截。"""

    def __init__(self, budget_tokens: int, throttle_threshold: float = 0.9,
                 repair_reserve_ratio: float = 0.0):
        if not isinstance(budget_tokens, int) or isinstance(budget_tokens, bool) \
                or budget_tokens <= 0:
            raise ValueError(f"budget_tokens 必须为正整数，当前值: {budget_tokens!r}")
        if not 0.0 < throttle_threshold <= 1.0:
            raise ValueError(
                f"throttle_threshold 必须落在 (0, 1] 区间，当前值: {throttle_threshold!r}"
            )
        if not 0.0 <= repair_reserve_ratio < 1.0:
            raise ValueError(
                f"repair_reserve_ratio 必须落在 [0, 1) 区间，当前值: {repair_reserve_ratio!r}"
            )
        self.budget_tokens = budget_tokens
        self.throttle_threshold = throttle_threshold
        self.repair_reserve_ratio = repair_reserve_ratio
        self.used_tokens = 0
        # M12-1：协作式取消——任务取消旗标检查（ensure_allowed 复用本检查点）
        self._cancel_check: Callable[[], bool] | None = None
        self.cancelled = False

    # ------------------------------------------------------------------

    def record(self, total_tokens: int) -> None:
        """累计一次 LLM 调用的用量（input + output）。"""
        self.used_tokens += max(0, int(total_tokens))

    def attach_cancel_check(self, check: Callable[[], bool]) -> None:
        """M12-1：注入取消旗标检查（ensure_allowed 复用为取消检查点）。"""
        self._cancel_check = check

    @property
    def ratio(self) -> float:
        return self.used_tokens / self.budget_tokens

    @property
    def remaining(self) -> int:
        """距总闸还剩多少 token（可为负，表示已超支）。"""
        return self.budget_tokens - self.used_tokens

    @property
    def repair_reserve(self) -> int:
        """按配比折算出的修复保留额（0 表示未启用隔离）。"""
        return int(self.budget_tokens * self.repair_reserve_ratio)

    @property
    def repair_fund_intact(self) -> bool:
        """修复保留额尚未被动用——LLM 修复通道可以开工。"""
        return self.remaining > self.repair_reserve

    @property
    def throttling(self) -> bool:
        """省 token 模式（11.0：≥90% 压缩讨论轮数等）。

        启用修复保留额时提前到「预算 - 保留额」触发：前置阶段一旦越过这条线
        就地收敛，把保留段留给修复——总闸口径（exceeded）不受影响。
        """
        if self.repair_reserve_ratio <= 0.0:
            return self.ratio >= self.throttle_threshold
        return self.used_tokens >= min(
            self.budget_tokens * self.throttle_threshold,
            self.budget_tokens - self.repair_reserve,
        )

    @property
    def exceeded(self) -> bool:
        """超预算（11.0：立即中止该任务）。"""
        return self.used_tokens >= self.budget_tokens

    def ensure_allowed(self) -> None:
        """调用前检查：取消旗标 / 超预算即抛错（立即中止，不静默继续）。"""
        if self._cancel_check is not None and self._cancel_check():
            self.cancelled = True
            raise TaskCancelledError("任务已被用户取消（M12-1 协作式取消检查点）")
        if self.exceeded:
            raise BudgetExceededError(
                f"任务 token 总预算已耗尽: {self.summary()}（11.0 总闸）"
            )

    def summary(self) -> str:
        """用量摘要（落盘与看板展示）。"""
        return f"{self.used_tokens} / {self.budget_tokens} token（{self.ratio:.1%}）"
