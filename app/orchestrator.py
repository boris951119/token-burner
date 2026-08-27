"""核心编排逻辑（规格文档第 17 章、第二阶段任务）。

已实现：
- 任务路由框架（3.2 节）：三分类路由 + 节流 + 边界护栏 + 保守降级；
- 团队组建（3.3 节 / 3.6 节 / 11.0 节）：模型校验、模式选择、
  项目目录创建、成本总预算闸门。

方案讨论、代码生成、修复循环等编排将在后续任务中扩展。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from app.config import Settings
from app.tools.prompt_templates import (
    CONVERGE_SPEC_SYSTEM,
    CONVERGE_SPEC_USER,
    INITIAL_PROPOSAL_SYSTEM,
    INITIAL_PROPOSAL_USER,
    REVIEW_PROPOSAL_SYSTEM,
    REVIEW_PROPOSAL_USER,
    REVISE_PROPOSAL_SYSTEM,
    REVISE_PROPOSAL_USER,
    SPEC_CONFIRM_FINAL_MERGE_SYSTEM,
    SPEC_CONFIRM_FINAL_MERGE_USER,
    SPEC_CONFIRM_REVISE_SYSTEM,
    SPEC_CONFIRM_REVISE_USER,
    TASK_ASSESSMENT_RECHECK_SYSTEM,
    TASK_ASSESSMENT_RECHECK_USER,
    TASK_ASSESSMENT_STRICT_REMINDER,
    TASK_ASSESSMENT_SYSTEM,
    TASK_ASSESSMENT_USER,
)
from app.utils.parse import parse_json
from app.utils.similarity import LoopDetector

if TYPE_CHECKING:
    from app.tools.file_manager import FileManager

VALID_TASK_TYPES = ("基础", "研究/分析", "编程")

# D.1 边界护栏：非编程判定 + 需求含执行类信号 → 触发复核
_EXECUTION_SIGNAL_PATTERN = re.compile(
    r"运行|执行|\.py\b|脚本|API|api|部署|跑一下|跑通"
)


class Route(Enum):
    """任务处理路径（3.2 节路由规则）。"""

    DIRECT_OUTPUT = "direct_output"                # 基础/研究·分析：主 LLM 直出
    DIRECT_SIMPLE_CODING = "direct_simple_coding"  # 简单编程节流：主 LLM 直出
    TEAM_FLOW = "team_flow"                        # 编程任务：完整团队流程


@dataclass
class RoutingResult:
    """路由决策结果（含评估元数据，供展示与落盘）。"""

    route: Route
    task_type: str
    difficulty_score: int
    difficulty_level: str
    reason: str
    rechecked: bool = False        # 是否触发过边界护栏复核
    fallback: bool = False         # 15.3 保守降级（解析失败）
    needs_user_confirm: bool = False  # 降级 / 高难度研究任务需用户确认
    suggest_review: bool = False   # 研究·分析 难度 ≥8：可选用一次评审确认


class TaskRouter:
    """需求评估与三分类路由（3.2 节）。

    决策归属（总则 D.1）：
    - 大模型：难度评估、任务类型判定；
    - 程序：JSON 结构与取值域校验、路由分发、边界信号检测与复核触发。
    """

    def __init__(self, llm: Any, main_model: str, settings: Settings):
        self.llm = llm
        self.main_model = main_model
        self.settings = settings

    def route(self, requirement: str) -> RoutingResult:
        assessment = self._assess(requirement)

        if assessment is None:
            # 15.3 硬回退：保守默认视作编程任务 + 提示用户手动确认
            return RoutingResult(
                route=Route.TEAM_FLOW,
                task_type="编程",
                difficulty_score=0,
                difficulty_level="未知",
                reason="评估输出解析失败，按保守默认视作编程任务",
                fallback=True,
                needs_user_confirm=True,
            )

        task_type = assessment["task_type"]
        score = assessment["difficulty_score"]

        # D.1 边界护栏：非编程判定 + 执行类关键词 → 请求复核（不发回自判）
        if task_type != "编程" and _EXECUTION_SIGNAL_PATTERN.search(requirement):
            assessment = self._recheck(requirement, task_type)
            task_type = assessment["task_type"]
            score = assessment["difficulty_score"]
            rechecked = True
        else:
            rechecked = False

        return self._dispatch(task_type, score, assessment, rechecked)

    # ------------------------------------------------------------------

    def _dispatch(
        self,
        task_type: str,
        score: int,
        assessment: dict,
        rechecked: bool,
    ) -> RoutingResult:
        base = dict(
            task_type=task_type,
            difficulty_score=score,
            difficulty_level=assessment.get("difficulty_level", "未知"),
            reason=assessment.get("reason", ""),
            rechecked=rechecked,
        )

        if task_type in ("基础", "研究/分析"):
            # 研究·分析 难度 ≥8：可选用一次评审确认（3.2 路由规则）
            suggest_review = task_type == "研究/分析" and score >= 8
            return RoutingResult(
                route=Route.DIRECT_OUTPUT,
                suggest_review=suggest_review,
                **base,
            )

        # task_type == "编程"
        if score <= self.settings.simple_threshold:
            # 简单编程节流（3.2）：主 LLM 直出、跳过完整团队
            return RoutingResult(route=Route.DIRECT_SIMPLE_CODING, **base)
        # 空白带（simple < score < 模块化阈值）与高难度均走标准团队流程
        return RoutingResult(route=Route.TEAM_FLOW, **base)

    # ------------------------------------------------------------------
    # 评估调用（含 15.3 重试与硬回退）
    # ------------------------------------------------------------------

    def _assess(self, requirement: str) -> dict | None:
        messages = [
            {"role": "system", "content": TASK_ASSESSMENT_SYSTEM},
            {"role": "user", "content": TASK_ASSESSMENT_USER.format(requirement=requirement)},
        ]
        strict_messages = [
            {
                "role": "system",
                "content": TASK_ASSESSMENT_SYSTEM + TASK_ASSESSMENT_STRICT_REMINDER,
            },
            *messages[1:],
        ]

        # 首次尝试 + 最多 max_parse_retries 次严格重试（15.3）
        attempts = [messages] + [strict_messages] * self.settings.max_parse_retries
        for i, msgs in enumerate(attempts):
            response = self.llm.chat(self.main_model, msgs, json_mode=True)
            value, _detail = parse_json(
                response.content, location="difficulty_assessment"
            )
            if value is not None and self._valid(value):
                return value
            if value is not None and not self._valid(value):
                # 结构/取值非法同样进入重试（取值域校验为确定性程序职责）
                continue
        return None

    def _recheck(self, requirement: str, original_type: str) -> dict:
        """边界护栏复核（D.1）：请求主 LLM 复核后重新决策，程序不改写结论。"""
        messages = [
            {
                "role": "system",
                "content": TASK_ASSESSMENT_RECHECK_SYSTEM.format(
                    task_type=original_type
                ),
            },
            {
                "role": "user",
                "content": TASK_ASSESSMENT_RECHECK_USER.format(
                    requirement=requirement
                ),
            },
        ]
        response = self.llm.chat(self.main_model, messages, json_mode=True)
        value, _detail = parse_json(response.content, location="recheck_assessment")
        if value is not None and self._valid(value):
            return value
        # 复核失败：维持原判定（大模型已给过结论，程序不越权改写）
        return {
            "task_type": original_type,
            "difficulty_score": 0,
            "difficulty_level": "未知",
            "reason": "复核输出解析失败，维持原判定",
        }

    @staticmethod
    def _valid(value: Any) -> bool:
        """确定性校验：task_type 三值之一且 difficulty_score 落在 0-10。"""
        if not isinstance(value, dict):
            return False
        if value.get("task_type") not in VALID_TASK_TYPES:
            return False
        score = value.get("difficulty_score")
        if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 10:
            return False
        return True


# ---------------------------------------------------------------------------
# 团队组建（3.3 节模型选择 / 3.6 节模式 / 11.0 预算闸门 / 3.1 步骤 5）
# ---------------------------------------------------------------------------


class TeamBuildError(ValueError):
    """团队组建失败（模型校验 / 模式校验 / 预算闸门 / 确认缺失）。"""


@dataclass
class TeamConfig:
    """已组建团队的运行配置（含项目目录与预算）。"""

    main_model: str
    dev_model: str
    test_model: str
    mode: str                 # safe | auto（3.6 双模）
    budget_tokens: int        # 11.0：按模式调整后的任务总预算
    project_id: str
    project_dir_name: str


class TeamBuilder:
    """编程任务的团队组建入口（3.1 步骤 5 / 3.3 节）。

    程序承担的均为确定性校验（总则 D.1）：
    - 三模型互异且均在预设列表（3.3）；
    - 模式合法（safe | auto）；
    - 自动模式须用户显式确认（3.6.3 / 19 章：成本放大明示）；
    - 预算闸门：按模式计算任务预算并落盘可审计。
    """

    def __init__(self, file_manager: FileManager, settings: Settings):
        self.file_manager = file_manager
        self.settings = settings

    def build(
        self,
        requirement: str,
        main_model: str,
        dev_model: str,
        test_model: str,
        mode: str = "safe",
        auto_mode_confirmed: bool = False,
    ) -> TeamConfig:
        """校验并组建团队，创建项目目录（含预算闸门检查）。"""
        self._check_models(main_model, dev_model, test_model)
        self._check_mode(mode)

        if mode == "auto" and not auto_mode_confirmed:
            raise TeamBuildError(
                "自动验证模式将使任务预算放大为标准预算的 "
                f"×{self.settings.auto_mode_budget_multiplier}，"
                "须在任务开始前经用户确认后传入 auto_mode_confirmed=True"
            )

        # 11.0 成本总预算闸门：按模式计算任务预算
        budget_tokens = self.settings.task_token_budget(mode)

        handle = self.file_manager.create_project(requirement)

        config = TeamConfig(
            main_model=main_model,
            dev_model=dev_model,
            test_model=test_model,
            mode=mode,
            budget_tokens=budget_tokens,
            project_id=handle.project_id,
            project_dir_name=handle.root.name,
        )
        self._persist_team_config(handle.root, config, requirement)
        return config

    def auto_mode_warning(self) -> str:
        """19 章：自动模式成本放大提示（供 UI 明示）。"""
        multiplier = self.settings.auto_mode_budget_multiplier
        return (
            f"自动验证模式预算为标准预算 ×{multiplier}，"
            f"当前任务预算将放大至 {self.settings.task_token_budget('auto')} token；"
            "确认继续请显式确认。"
        )

    # ------------------------------------------------------------------

    def _check_models(self, main_model: str, dev_model: str, test_model: str) -> None:
        for name in (main_model, dev_model, test_model):
            if name not in self.settings.models:
                raise TeamBuildError(
                    f"模型「{name}」不在预设列表中，可用模型: {self.settings.models}"
                )
        if len({main_model, dev_model, test_model}) != 3:
            raise TeamBuildError(
                f"主 LLM / 开发副 LLM / 测试副 LLM 必须选择三个不同的模型，"
                f"当前: ({main_model}, {dev_model}, {test_model})"
            )

    def _check_mode(self, mode: str) -> None:
        if mode not in ("safe", "auto"):
            raise TeamBuildError(
                f"执行模式必须为 safe（安全审阅）或 auto（自动验证），当前: {mode!r}"
            )

    def _persist_team_config(
        self, project_root: Any, config: TeamConfig, requirement: str
    ) -> None:
        """团队配置与预算落盘（第 5 章可审计）。"""
        data = {
            "main_model": config.main_model,
            "dev_model": config.dev_model,
            "test_model": config.test_model,
            "mode": config.mode,
            "budget_tokens": config.budget_tokens,
            "requirement": requirement,
        }
        path = project_root / "sessions" / "team_config.json"
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# 方案讨论（3.4 节 / 11.1 轮数上限 / 11.3 循环检测 / 11.5 spec 确认收敛）
# ---------------------------------------------------------------------------


@dataclass
class DiscussionOutcome:
    """方案讨论结果。"""

    spec_md: str                  # 最终 spec.md 内容
    rounds_completed: int         # 实际完成轮数（11.1：默认 ≤3）
    converged: bool               # 是否已收敛（轮数耗尽/无新意见/循环打断）
    frozen: bool                  # 11.3：是否触发循环检测冻结
    discussion_summary: str = ""  # 各轮摘要（8.5：discussion_summary.md）


@dataclass
class SpecConfirmResult:
    """spec 确认环节结果（11.5）。"""

    confirmed: bool     # 用户是否确认
    final: bool         # 是否已强制收敛（不再接受修改）
    spec_md: str
    rounds: int         # 已使用的修改次数


class DiscussionEngine:
    """方案讨论编排（3.4 节）：初始方案 → 双评审 → 汇总修订 → 收敛 spec。

    护栏落地：
    - 11.1 轮数上限：达上限后主 LLM 直接产出收敛 spec；
    - 11.3 循环检测：论点重复达上限 → 冻结副 LLM 发言，主 LLM 收权裁决；
    - 11.5 确认收敛：spec 确认修改 ≤3 次，第 3 次后主动合并意见。
    """

    def __init__(
        self,
        llm: Any,
        main_model: str,
        dev_model: str,
        test_model: str,
        settings: Settings,
        file_manager: FileManager | None = None,
        project_id: str | None = None,
    ):
        self.llm = llm
        self.main_model = main_model
        self.dev_model = dev_model
        self.test_model = test_model
        self.settings = settings
        self.file_manager = file_manager
        self.project_id = project_id
        self._detector = LoopDetector(settings)
        # 11.5 确认环节状态
        self._confirm_feedbacks: list[str] = []
        self._final_spec: str | None = None  # 强制收敛后的最终 spec（不再修改）

    # ------------------------------------------------------------------

    def run_discussion(self, requirement: str, project_id: str | None = None) -> DiscussionOutcome:
        """执行完整方案讨论，产出收敛的 spec.md。"""
        pid = project_id or self.project_id
        proposal = self._chat(
            self.main_model,
            [
                {"role": "system", "content": INITIAL_PROPOSAL_SYSTEM},
                {"role": "user", "content": INITIAL_PROPOSAL_USER.format(requirement=requirement)},
            ],
        )
        history: list[str] = [f"[初始方案]\n{proposal}"]
        summaries: list[str] = []
        rounds = 0
        frozen = False

        while rounds < self.settings.max_discussion_rounds:
            # 11.3：评审意见进入论点库检测（重复论点计数）；
            # 开发评审触发冻结时，本轮测试评审直接跳过（省 token）
            dev_review = self._get_review(requirement, proposal, self.dev_model, "开发工程师", "实现成本、技术可行性、模块划分合理性")
            rounds += 1
            if self._detector.check(dev_review).frozen:
                frozen = True
                summaries.append(
                    f"第 {rounds} 轮：\n- 开发评审：{dev_review}\n（循环打断：测试评审跳过）"
                )
                break

            test_review = self._get_review(requirement, proposal, self.test_model, "测试工程师", "可测试性、边界条件覆盖、验收标准明确性")
            if self._detector.check(test_review).frozen:
                frozen = True
                summaries.append(
                    f"第 {rounds} 轮：\n- 开发评审：{dev_review}\n- 测试评审：{test_review}\n（循环打断：冻结副 LLM 发言）"
                )
                break

            summaries.append(f"第 {rounds} 轮：\n- 开发评审：{dev_review}\n- 测试评审：{test_review}")

            # 无新弱点与风险 → 提前收敛（省 token）
            if _no_issues(dev_review) and _no_issues(test_review):
                break

            if rounds >= self.settings.max_discussion_rounds:
                break

            proposal = self._chat(
                self.main_model,
                [
                    {"role": "system", "content": REVISE_PROPOSAL_SYSTEM},
                    {"role": "user", "content": REVISE_PROPOSAL_USER.format(
                        proposal=proposal, dev_review=dev_review, test_review=test_review
                    )},
                ],
            )
            history.append(f"[第 {rounds} 轮修订]\n{proposal}")

        # 收敛裁决：轮数耗尽 / 循环打断 / 无新意见 → 主 LLM 产出最终 spec
        spec_md = self._chat(
            self.main_model,
            [
                {"role": "system", "content": CONVERGE_SPEC_SYSTEM},
                {"role": "user", "content": CONVERGE_SPEC_USER.format(
                    requirement=requirement, history="\n\n".join(history)
                )},
            ],
        )

        outcome = DiscussionOutcome(
            spec_md=spec_md,
            rounds_completed=rounds,
            converged=True,
            frozen=frozen,
            discussion_summary="\n\n".join(summaries),
        )
        self._persist_discussion(pid, outcome)
        return outcome

    # ------------------------------------------------------------------
    # 11.5 spec 确认收敛
    # ------------------------------------------------------------------

    def confirm_spec(self, outcome: DiscussionOutcome, user_reply: str) -> SpecConfirmResult:
        """处理用户对 spec 的确认 / 修改意见（11.5：≤3 次）。"""
        # 已强制收敛：任何后续意见都不再触发修改
        if self._final_spec is not None:
            return SpecConfirmResult(False, True, self._final_spec, len(self._confirm_feedbacks))

        if _is_confirmation(user_reply):
            return SpecConfirmResult(True, True, outcome.spec_md, len(self._confirm_feedbacks))

        self._confirm_feedbacks.append(user_reply)
        used = len(self._confirm_feedbacks)

        if used >= self.settings.max_spec_confirm_rounds:
            # 11.5：第 3 次后主动收敛合并，输出最终 spec，不再反复征询
            merged = self._chat(
                self.main_model,
                [
                    {"role": "system", "content": SPEC_CONFIRM_FINAL_MERGE_SYSTEM},
                    {"role": "user", "content": SPEC_CONFIRM_FINAL_MERGE_USER.format(
                        spec=outcome.spec_md,
                        feedback_history="\n".join(
                            f"{i + 1}. {fb}" for i, fb in enumerate(self._confirm_feedbacks)
                        ),
                    )},
                ],
            )
            self._final_spec = merged
            return SpecConfirmResult(False, True, merged, used)

        revised = self._chat(
            self.main_model,
            [
                {"role": "system", "content": SPEC_CONFIRM_REVISE_SYSTEM},
                {"role": "user", "content": SPEC_CONFIRM_REVISE_USER.format(
                    spec=outcome.spec_md, feedback=user_reply
                )},
            ],
        )
        return SpecConfirmResult(False, False, revised, used)

    # ------------------------------------------------------------------

    def _get_review(
        self, requirement: str, proposal: str, model: str, role: str, focus: str
    ) -> str:
        """副 LLM 评审（8.2 JSON；15.3 解析失败降级为原文归纳）。"""
        response = self.llm.chat(
            model,
            [
                {"role": "system", "content": REVIEW_PROPOSAL_SYSTEM.format(role=role, focus=focus)},
                {"role": "user", "content": REVIEW_PROPOSAL_USER.format(
                    requirement=requirement, proposal=proposal
                )},
            ],
            json_mode=True,
        )
        value, _detail = parse_json(response.content, location=f"review_{role}")
        if value is not None and isinstance(value, dict):
            # 结构化评审意见 → 紧凑文本（供修订与论点检测）
            return json.dumps(value, ensure_ascii=False)
        # 15.3 降级：主 LLM 依原始文本归纳，不强求结构化打分
        return response.content

    def _chat(self, model: str, messages: list[dict]) -> str:
        return self.llm.chat(model, messages).content

    def _persist_discussion(self, pid: str | None, outcome: DiscussionOutcome) -> None:
        """讨论结果落盘（6.3：spec.md + sessions/discussion_summary.md）。"""
        if not pid or self.file_manager is None:
            return
        handle = self.file_manager.get_project(pid)
        if handle is None:
            return
        (handle.root / "spec.md").write_text(outcome.spec_md, encoding="utf-8")
        summary = handle.root / "sessions" / "discussion_summary.md"
        summary.write_text(
            outcome.discussion_summary or "（无评审轮记录）", encoding="utf-8"
        )


def _is_confirmation(reply: str) -> bool:
    """用户确认判定（确定性：常见确认词）。"""
    return reply.strip() in ("确认", "y", "Y", "yes", "是", "同意", "ok", "OK")


def _no_issues(review_text: str) -> bool:
    """评审意见是否无弱点无风险（确定性解析，用于提前收敛判定）。"""
    try:
        data = json.loads(review_text)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    return not data.get("weaknesses") and not data.get("risks")
