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

import os
import time
from typing import Callable


class BudgetExceededError(RuntimeError):
    """任务 token 总预算耗尽（11.0：立即中止，落盘交用户）。"""


class TaskCancelledError(RuntimeError):
    """任务被用户取消（M12-1 协作式取消：检查点抛出，任务体终止）。"""


class TaskDeadlineError(TaskCancelledError):
    """运行墙钟见底（批次#58B）：不等平台强杀，自己先收手按现状交付。

    单列一类而不复用 TaskCancelledError：管线的终止分支按类型分派，
    「用户点了取消」与「到点强杀前收手」在中断报告与事件流里必须是
    两句话（宁可如实写「未完成」，不冒充别的终态）。
    """


_active_guard: "BudgetGuard | None" = None


def set_active_budget_guard(guard: "BudgetGuard | None") -> None:
    """登记当前任务的活动护栏（管线创建护栏时调用一次）。"""
    global _active_guard
    _active_guard = guard


def get_active_budget_guard() -> "BudgetGuard | None":
    """零散 ModelClient 兜底数据源：未显式接线时复用活动护栏。"""
    return _active_guard


# 修复余量系数（10-01 两轮标定）：完赛队伍实测 6.8M/4.86M=1.40×；
# 我方四次 run 精确烧满信封死于验收链（088dd22/9ac543c/sheet_p0/keep 彩排
# 100.4%——keep 实耗 2,168,210/折算 1,440,000=1.51×，死在自测生成中途，
# 交付树已落盘探针全绿）。折算口径只算生成段，验收+自测+修复段的钱
# 从未进公式。取 2.0（1.51 实测下界 + 自测未跑完的尾部 + 边际）。
REPAIR_HEADROOM = 2.0


def task_envelope(n_requirements: int, text_chars: int,
                  config_floor: int = 0, hard_cap: int = 0) -> int:
    """单任务实际信封：`min( max(题面折算, 配置托底), 硬帽 )`。

    两段语义各自有实证，缺一不可：

    ① **托底＝只抬不砍**（v41，run 088dd22be41b）：sheet 题折算 1,621,440 直接
       覆盖了配置里的 2,000,000，于是这一跑烧到 101.5% 断气、验收+修复段零执行，
       而账上还有 35 万 token 没用。折算口径的职责是给「条少字多」的题面加钱，
       从来不是给一份健康配置减钱。

    ② **硬帽**（批次#67，run 9ac543c41514）：①落地后信封从 162 万抬到 486 万，
       这一跑就**精确烧满 486 万（100.2%）**、又是死在自测闸前——总闸只是许可，
       烧钱的三处（模型思考 token、修复环整文件重发、自测闸生成 spec）各自没有闸，
       给多大烧多大。官方跑要留着 ① 不砍，但换私有 key 试跑必须能把单次成本
       （￥62.69 / 10 小时）压到可迭代的水位，所以这里要有一个**能砍下来**的上限。
       0 = 关闭（行为与 v41 一字不变）。
    """
    try:
        floor = int(config_floor or 0)
    except (TypeError, ValueError):
        # 配置里的脏值只允许被看成「没有托底」——启动折算不能换成一次崩溃
        floor = 0
    # 修复余量：×1.5 后再与托底/硬帽结算——「真实需要」含验收修复段，
    # 托底若低于加余量后的折算，照旧只抬不砍（三次 100% 断气的共同死因
    # 就是许可恰好卡在生成段成本线上）。
    envelope = max(
        int(size_aware_budget(n_requirements, text_chars) * REPAIR_HEADROOM),
        floor)
    try:
        cap = int(hard_cap)
    except (TypeError, ValueError):
        cap = 0
    # 帽子的失效方向必须朝「不加帽」：`int(1.5)` 会截成 1，一个手写的
    # 小数/布尔值若照单全收，等于把整跑预算换成一个 token——立刻断气，
    # 而日志上只看得出「信封好小」。托底脏值最多少给钱，硬帽脏值能把
    # 任务直接掐死，所以这一侧逐型拒绝。
    if isinstance(hard_cap, bool) or cap <= 0:
        cap = 0
    elif isinstance(hard_cap, float) and cap != hard_cap:
        cap = 0
    if cap > 0:
        envelope = min(envelope, cap)
    return envelope


def size_aware_budget(
    n_requirements: int,
    text_chars: int = 0,
    base: int = 800_000,
    per_requirement: int = 20_000,
    per_kchar: int = 30_000,
    cap: int = 5_000_000,
) -> int:
    """按题面折算单任务 token 信封（48h 官方任务用）：条数项与字数项取大。

    总闸此前只有「配置里写死的数」这一个来源，而官方容器不带 config.json，
    于是生效值是代码缺省 200k（自动模式 ×2.5 = 500k）。9/23 全真彩排实测：
    四需求的最小一道题光生成+验收就烧到 518k——预算低于最小可完成成本时，
    撞墙的不是质量而是修复（三轮 LLM 修复全部瞬时抛在同一行「预算已耗尽」上，
    一步没走、墙钟照烧，最后交出一份明知是坏的交付）。故信封必须跟着题面
    体量走，并且留出验收+修复段。

    条数项标定（9/23 用本地 8 份官方题面实测，n 取 ATOMIC 需求数，冒号后为
    历次真实跑完的总用量 / 信封对其倍率）：keep 32 条 537k → 2.7x，bookstack
    34 条 1.19M → 1.2x，stackoverflow 66 条 587k → 3.6x。固定项远大于变动
    项（最小一道题就要 518k），故基数取「已知最小完成成本」上浮一档，每条
    需求再加一线索的修复量。

    字数项（9/24 补，正式赛真题面逼出来的）：只按条数折算隐含一个假设——
    每条需求的文字量差不多。初赛六道实测每条需求 450~750 字符，全在这个
    窄带里，所以条数口径在初赛一直好用。正式赛两道题面出带：sheet 每条
    2,252 字符、github 每条 3,120 字符（keep 的 5.6 倍），条数口径于是
    反向给薄预算——github 47 条只分到 1.74M，而按实测「每千字题面 ≈30k
    token」（keep 完成跑 537k/17.8k 字）它需要 4.40M。系数**不加 base**：
    30k/千字 这个数本身就是从含固定开销的总用量除出来的，再加一次 base
    等于把固定项算两遍。取两式较大者 ⇒ 初赛六条信封数值一字不变（字数项
    在带内永远低于条数项），只有出带的题面才被这条抬高。上限随之从 3.5M
    提到 5.0M，容纳 github 的 4.40M。
    """
    try:
        n = max(0, int(n_requirements))
    except (TypeError, ValueError):
        n = 0
    try:
        chars = max(0, int(text_chars))
    except (TypeError, ValueError):
        chars = 0
    count_term = base + per_requirement * n
    char_term = per_kchar * chars // 1000
    return int(min(cap, max(base, count_term, char_term)))


# ----------------------------------------------------------------------
# 运行级墙钟（批次#58B）：48h 到点是「强杀」不是「暂停」
#
# 官方侧的超时/OOM 截断走 SIGKILL，信号处理接不住，那时末尾的导出根本
# 不会执行——已经写完的代码等于没写。判分口径是 avg_pass_rate 而 exit 1
# 不评分，所以「在还来得及的时候主动收尾」是唯一能把墙钟损失换成部分分
# 的动作。三个变量名依次取第一个有值的：runner 注入哪个没有文档可查，
# 而放弃读取等于放弃到期前收手的唯一机会；都没有则按《参赛须知》的
# 48 小时起表（本地彩排同样适用：闸只在最后 15 分钟才咬，平时零影响）。

TASK_TIME_ENV = ("TASK_MAX_SECONDS", "ARCBENCH_TASK_SECONDS",
                 "ARC_TASK_SECONDS", "TASK_TIMEOUT_SECONDS")
DEFAULT_TASK_SECONDS = 48 * 3600
# 收尾窗口：闸只在「剩余时间还不够把在飞的调用跑完 + 导出落盘」时咬合。
# 口径不是导出耗时（先清后写整棵树，秒级），而是**在飞调用的最坏尾巴**：
# 检查点只能在调用开始前拦，已经发出去的那次仍会跑完——单次墙钟 600s ×
# 备胎链 3 条腿 = 1800s，窗口小于它就等于「收手指令下达时我已经出局了」。
# 代价是每跑最多早停 30 分钟（48h 的 0.5%），换的是不被斩在写盘中间。
# 墙钟被配到 1200s 时尾巴变成 3600s，那一档靠验收前的「抢先导出」兜底。
DEFAULT_WIND_DOWN_SECONDS = 1800.0

_deadline_at: float | None = None
_task_total_seconds: float = 0.0
_deadline_source: str = "未起表"


def _env_seconds() -> "tuple[str, float] | None":
    """按 TASK_TIME_ENV 顺序读运行时长上限；脏值跳过、非正值作废。

    env 由人填，按不可信输入处理：起表发生在管线启动之前，一道保命闸
    不该成为最早的死因（裸 float() 遇 `TASK_MAX_SECONDS=48h` 直接把
    整跑换成一次启动异常）。返回 (变量名, 秒数)——用了哪个口径要能
    从启动横幅读出来，否则「平台注没注入上限」这件事永远查不到。
    """
    for name in TASK_TIME_ENV:
        raw = os.environ.get(name)
        if raw is None or not str(raw).strip():
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val > 0 and val == val:  # 排除 NaN 与负值
            return name, val
    return None


def arm_task_deadline(seconds: float | None = None) -> float:
    """起表：本次运行的墙钟上限（秒），返回生效值。

    seconds=None → 读环境变量 → 缺省 48h。重复调用以最后一次为准
    （续跑/测试重新起表）。
    """
    global _deadline_at, _task_total_seconds, _deadline_source
    try:
        total = None if seconds is None else float(seconds)
    except (TypeError, ValueError):
        total = None
    source = "入参"
    if total is None or total <= 0 or total != total:
        env = _env_seconds()
        if env is None:
            source, total = "缺省", float(DEFAULT_TASK_SECONDS)
        else:
            source, total = env[0], env[1]
    _deadline_source = source
    _deadline_at = time.monotonic() + total
    _task_total_seconds = total
    return total


def clear_task_deadline() -> None:
    """撤表（测试隔离用）：未起表时时间闸全程不生效。"""
    global _deadline_at, _task_total_seconds, _deadline_source
    _deadline_at = None
    _task_total_seconds = 0.0
    _deadline_source = "未起表"


def task_deadline_armed() -> bool:
    return _deadline_at is not None


def task_seconds_remaining(now: float | None = None) -> float | None:
    """距强杀还剩多少秒；未起表返回 None（调用方跳过时间闸检查）。

    now 供测试注入单调时钟读数。已过点如实返回负值——时间闸报假
    「还早」比报假「来不及」危险得多。
    """
    if _deadline_at is None:
        return None
    base = time.monotonic() if now is None else now
    return _deadline_at - base


def wind_down_pending(wind_down_seconds: float = DEFAULT_WIND_DOWN_SECONDS) -> bool:
    """模块级时间闸：未起表 ⇒ 永远 False（时间闸全程不生效）。

    给「没有 guard 在手」的调用方用（零散 ModelClient、编排段的无 LLM 收尾
    步骤）；有 guard 时优先走 BudgetGuard.wind_down_pending，窗口可注入。
    """
    left = task_seconds_remaining()
    return left is not None and left <= float(wind_down_seconds)


def deadline_brief() -> str:
    """墙钟现状一行话（启动横幅与中断报告用，含「上限是从哪来的」）。

    来源必须出现在文案里：平台到底注没注入运行上限，本地彩排按哪个口径
    跑的，事后只有这一行可查。
    """
    left = task_seconds_remaining()
    if left is None:
        return "运行墙钟未起表"
    if left < 0:
        return f"运行墙钟已过点 {-left / 60:.1f} 分钟（来源 {_deadline_source}）"
    return (f"运行墙钟余 {left / 3600:.2f}h / "
            f"{_task_total_seconds / 3600:.1f}h（来源 {_deadline_source}）")


class BudgetGuard:
    """单任务预算护栏：累计用量 + 阈值判定 + 超限拦截 + 墙钟检查点。"""

    def __init__(self, budget_tokens: int, throttle_threshold: float = 0.9,
                 repair_reserve_ratio: float = 0.0,
                 wind_down_seconds: float = DEFAULT_WIND_DOWN_SECONDS):
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
        self.wind_down_seconds = max(0.0, float(wind_down_seconds))
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

    @property
    def seconds_left(self) -> float | None:
        """距运行墙钟强杀还有多少秒（未起表=None，时间闸全程不生效）。"""
        return task_seconds_remaining()

    @property
    def wind_down_pending(self) -> bool:
        """剩余墙钟已不够再开一次调用后收尾——该收手把现状交付出去。

        判据是「够不够收尾」而不是「还剩多少」：宁可在剩 15 分钟时停下
        交一份少修一轮的产物，也不要赌最后一次调用——它一旦被强杀打断，
        换来的是 exit 1（0 分），而部分分本来已经拿到手了。
        """
        left = self.seconds_left
        return left is not None and left <= self.wind_down_seconds

    def ensure_allowed(self) -> None:
        """调用前检查：取消旗标 / 墙钟见底 / 超预算即抛错（不静默继续）。"""
        if self._cancel_check is not None and self._cancel_check():
            self.cancelled = True
            raise TaskCancelledError("任务已被用户取消（M12-1 协作式取消检查点）")
        if self.wind_down_pending:
            raise TaskDeadlineError(
                f"运行墙钟仅剩 {self.seconds_left:.0f}s（收尾窗口 "
                f"{self.wind_down_seconds:.0f}s），主动收手按现状交付："
                f"{deadline_brief()}，用量 {self.summary()}"
            )
        if self.exceeded:
            raise BudgetExceededError(
                f"任务 token 总预算已耗尽: {self.summary()}（11.0 总闸）"
            )

    def summary(self) -> str:
        """用量摘要（落盘与看板展示）。"""
        return f"{self.used_tokens} / {self.budget_tokens} token（{self.ratio:.1%}）"
