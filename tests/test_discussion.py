"""DiscussionEngine 单元测试（TDD 先行，LLM 全部 mock）。

依据：规格文档 v0.3.1 3.4 节 + 11.1 / 11.3 / 11.5：
- 3.4 流程：主 LLM 初始方案 → 开发/测试副 LLM 评审（8.2 JSON）→ 主 LLM 汇总修订；
- 11.1：一轮 = 初始方案 → 开发评审 → 测试评审 → 主 LLM 汇总；
  默认 ≤3 轮；第 N 轮汇总必须直接产出收敛的最终 spec，不再提出开放问题；
- 11.3：循环检测触发（论点重复达上限）→ 冻结副 LLM 发言权，
  主 LLM 收权基于已积累论点直接裁决结束讨论；
- 11.5：spec 确认收敛 ≤3 次，第 3 次后主 LLM 主动合并意见输出最终 spec；
- 15.3：评审意见 JSON 解析失败 → 主 LLM 依原始文本归纳，不强求结构化打分。

调用序列约定（引擎真实消耗，脚本须按序供给）：
N 轮讨论（评审有弱点、逐轮变化）= 初始方案 + N×(dev评审, test评审)
+ (N-1)×主 LLM 修订 + 1 次最终收敛裁决。
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.orchestrator import DiscussionEngine, DiscussionOutcome
from app.utils.model_client import LLMResponse


def review_json(weaknesses: list | None = None, risks: list | None = None) -> str:
    return json.dumps(
        {
            "scores": {"feasibility": 7, "security": 7, "maintainability": 7},
            "strengths": ["技术选型合理"],
            "weaknesses": weaknesses if weaknesses is not None else ["权限控制描述不够详细"],
            "risks": risks if risks is not None else ["数据合规风险"],
        },
        ensure_ascii=False,
    )


POSITIVE_REVIEW = json.dumps(
    {
        "scores": {"feasibility": 9, "security": 9, "maintainability": 9},
        "strengths": ["方案完善"],
        "weaknesses": [],
        "risks": [],
    },
    ensure_ascii=False,
)


class ScriptedLLM:
    """按脚本顺序返回结果的桩。记录每次调用。"""

    def __init__(self, scripts: list[str]):
        self.scripts = list(scripts)
        self.calls: list[dict] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append({"model": model, "messages": messages, "json_mode": json_mode})
        content = self.scripts.pop(0) if self.scripts else "默认输出"
        return LLMResponse(model=model, content=content, input_tokens=10, output_tokens=5)

    @property
    def remaining(self) -> int:
        return len(self.scripts)


def positive_scripts(initial: str = "初始方案：使用 SQLite。") -> list[str]:
    """1 轮即收敛的讨论脚本（评审无弱点无风险）。"""
    return [initial, POSITIVE_REVIEW, POSITIVE_REVIEW, "最终收敛 spec：项目目标与模块划分。"]


def varying_scripts(rounds: int, initial: str = "初始方案：使用 SQLite。") -> list[str]:
    """N 轮「有弱点且逐轮变化」的讨论脚本（不触发循环检测）。"""
    scripts = [initial]
    for i in range(rounds):
        scripts.append(review_json(weaknesses=[f"权限描述不足（第{i + 1}轮新问题）"]))
        scripts.append(review_json(weaknesses=[f"接口定义模糊（第{i + 1}轮新问题）"]))
        if i < rounds - 1:
            scripts.append(f"修订方案 v{i + 1}：吸收双方意见。")
    scripts.append("最终收敛 spec：项目目标与模块划分。")
    return scripts


def make_engine(llm, settings=None, file_manager=None) -> DiscussionEngine:
    return DiscussionEngine(
        llm=llm,
        main_model="gpt-4o",
        dev_model="deepseek-chat",
        test_model="claude-3-5-sonnet",
        settings=settings or Settings(),
        file_manager=file_manager,
        project_id="demo" if file_manager else None,
    )


@pytest.fixture
def fm(tmp_path):
    from app.tools.file_manager import FileManager
    return FileManager(projects_root=tmp_path / "projects")


def _create(fm):
    return fm.create_project("demo").project_id


class TestDiscussionFlow:
    def test_full_round_sequence(self, fm):
        # 11.1：一轮 = 初始 → dev 评审 → test 评审 → 主汇总（收敛裁决）
        llm = ScriptedLLM(positive_scripts())
        engine = make_engine(llm, file_manager=fm)
        engine.run_discussion("需求", _create(fm))
        models = [c["model"] for c in llm.calls]
        assert models == ["gpt-4o", "deepseek-chat", "claude-3-5-sonnet", "gpt-4o"]

    def test_reviews_use_json_mode(self, fm):
        llm = ScriptedLLM(positive_scripts())
        engine = make_engine(llm, file_manager=fm)
        engine.run_discussion("需求", _create(fm))
        # dev/test 评审调用应请求 JSON 模式（8.2 结构）
        assert llm.calls[1]["json_mode"] is True
        assert llm.calls[2]["json_mode"] is True

    def test_outcome_contains_spec_and_summary(self, fm):
        llm = ScriptedLLM(positive_scripts())
        engine = make_engine(llm, file_manager=fm)
        outcome = engine.run_discussion("需求", _create(fm))
        assert isinstance(outcome, DiscussionOutcome)
        assert "spec" in outcome.spec_md
        assert outcome.rounds_completed == 1

    def test_discussion_summary_persisted(self, fm):
        # 6.3/8.5：discussion_summary.md 保存方案讨论摘要与评审意见
        project_id = _create(fm)
        llm = ScriptedLLM(positive_scripts())
        outcome = engine_run(fm, llm, project_id)
        handle = fm.get_project(project_id)
        assert handle is not None
        summary = (handle.root / "sessions" / "discussion_summary.md").read_text(
            encoding="utf-8"
        )
        assert "评审" in summary
        # spec.md 同步落盘且与返回值一致（6.3）
        spec_file = (handle.root / "spec.md").read_text(encoding="utf-8")
        assert spec_file == outcome.spec_md


def engine_run(fm, llm, project_id):
    engine = make_engine(llm, file_manager=fm)
    return engine.run_discussion("需求", project_id)


class TestRoundLimit:
    def test_stops_at_max_rounds(self, fm):
        # 11.1：默认 ≤3 轮；脚本供给 5 轮，实际只消耗 3 轮
        llm = ScriptedLLM(varying_scripts(5))
        engine = make_engine(llm, file_manager=fm)
        outcome = engine.run_discussion("需求", _create(fm))
        assert outcome.rounds_completed == 3
        assert outcome.converged is True
        assert outcome.frozen is False
        assert llm.remaining > 0  # 未耗尽 → 第 4/5 轮未发生

    def test_converges_early_if_no_new_issues(self, fm):
        # 评审无弱点且无风险 → 下一轮直接收敛（省 token）
        llm = ScriptedLLM(positive_scripts())
        engine = make_engine(llm, file_manager=fm)
        outcome = engine.run_discussion("需求", _create(fm))
        assert outcome.rounds_completed == 1
        assert outcome.converged is True

    def test_final_round_forces_convergence(self, fm):
        # 11.1 达标行为：最后一轮汇总直接产出收敛 spec，不再提开放问题
        llm = ScriptedLLM(varying_scripts(3))
        engine = make_engine(llm, file_manager=fm)
        outcome = engine.run_discussion("需求", _create(fm))
        assert outcome.converged is True
        # 最后一次调用是主 LLM 的收敛裁决
        assert llm.calls[-1]["model"] == "gpt-4o"


class TestLoopInterruption:
    def test_loop_freezes_sub_llms(self, fm):
        # 11.3：论点重复达上限 → 冻结副 LLM 发言，主 LLM 收权裁决
        repeated_review = review_json(weaknesses=["权限控制需要细化到角色级别"])
        scripts = [
            "初始方案",
            repeated_review,  # R1 dev（计数 0）
            repeated_review,  # R1 test（计数 1）
            "修订 v1",         # R1 修订
            repeated_review,  # R2 dev（计数 2 → 达上限冻结）
            "最终收敛 spec",   # 主 LLM 收权裁决
        ]
        llm = ScriptedLLM(scripts)
        settings = Settings(loop_repeat_limit=2)
        engine = make_engine(llm, settings=settings, file_manager=fm)
        outcome = engine.run_discussion("需求", _create(fm))
        assert outcome.frozen is True
        assert outcome.rounds_completed == 2
        assert outcome.spec_md  # 冻结后主 LLM 直接产出最终 spec

    def test_frozen_skips_remaining_reviews(self, fm):
        # 冻结后不再调用副 LLM（R2 的测试评审被跳过）
        repeated_review = review_json(weaknesses=["数据库选型应当改为 PostgreSQL"])
        scripts = [
            "初始方案",
            repeated_review,  # R1 dev（计数 0）
            repeated_review,  # R1 test（计数 1）
            "修订 v1",
            repeated_review,  # R2 dev（计数 2 → 冻结）
            "最终收敛 spec",
            "不应被消耗",      # 若 R2 test 评审未被跳过，此项将被耗尽
        ]
        llm = ScriptedLLM(scripts)
        settings = Settings(loop_repeat_limit=2)
        engine = make_engine(llm, settings=settings, file_manager=fm)
        outcome = engine.run_discussion("需求", _create(fm))
        assert outcome.frozen is True
        assert llm.remaining == 1  # 「不应被消耗」仍在 → 测试评审被跳过
        # 收敛裁决为最后一次 LLM 调用
        assert llm.calls[-1]["model"] == "gpt-4o"


class TestReviewParsingFallback:
    def test_unparseable_review_falls_back_to_text(self, fm):
        # 15.3：评审意见解析失败 → 主 LLM 依原始文本归纳，流程不卡死
        dev_text = "我认为方案可行，但权限部分太粗糙"
        scripts = ["初始方案"]
        for i in range(3):
            scripts.append(dev_text)        # dev：非 JSON → 降级为原文
            scripts.append(review_json())   # test：正常 JSON
            if i < 2:
                scripts.append(f"修订 v{i + 1}")
        scripts.append("最终收敛 spec")
        llm = ScriptedLLM(scripts)
        engine = make_engine(llm, file_manager=fm)
        outcome = engine.run_discussion("需求", _create(fm))
        assert outcome.rounds_completed == 3  # 走满轮数上限，流程未卡死
        assert outcome.spec_md
        # 非 JSON 评审原文进入了摘要（供主 LLM 归纳）
        assert "权限部分太粗糙" in outcome.discussion_summary

    def test_all_reviews_unparseable_still_completes(self, fm):
        # 全部评审均非 JSON → 逐轮降级为文本，仍能走完并产出 spec
        scripts = ["初始方案"]
        for i in range(3):
            scripts.append(f"开发意见（第{i + 1}轮）：接口需要重新设计以适配场景{i}")
            scripts.append(f"测试意见（第{i + 1}轮）：验收标准缺少边界{i}")
            if i < 2:
                scripts.append(f"修订 v{i + 1}")
        scripts.append("最终收敛 spec")
        llm = ScriptedLLM(scripts)
        engine = make_engine(llm, file_manager=fm)
        outcome = engine.run_discussion("需求", _create(fm))
        assert outcome.rounds_completed == 3
        assert outcome.frozen is False
        assert outcome.spec_md


class TestSpecConfirm:
    def test_confirm_immediately(self, fm):
        llm = ScriptedLLM(positive_scripts())
        engine = make_engine(llm, file_manager=fm)
        project_id = _create(fm)
        outcome = engine.run_discussion("需求", project_id)
        result = engine.confirm_spec(outcome, "确认")
        assert result.confirmed is True
        assert result.final is True
        assert result.spec_md == outcome.spec_md
        assert llm.remaining == 0  # 确认不触发 LLM 调用

    def test_user_modification_updates_spec(self, fm):
        llm = ScriptedLLM(positive_scripts() + ["修订后的 spec：加入权限章节"])
        engine = make_engine(llm, file_manager=fm)
        project_id = _create(fm)
        outcome = engine.run_discussion("需求", project_id)
        result = engine.confirm_spec(outcome, "把权限部分再细化一下")
        assert result.confirmed is False
        assert result.final is False
        assert "权限" in result.spec_md
        assert result.rounds == 1

    def test_confirm_converges_after_limit(self, fm):
        # 11.5：修改意见 ≤3 次，第 3 次后主 LLM 收敛合并输出最终 spec
        llm = ScriptedLLM(
            positive_scripts() + ["修订1", "修订2", "最终收敛合并版"]
        )
        engine = make_engine(llm, file_manager=fm)
        project_id = _create(fm)
        outcome = engine.run_discussion("需求", project_id)
        r1 = engine.confirm_spec(outcome, "改1")
        assert r1.confirmed is False and r1.final is False
        r2 = engine.confirm_spec(outcome, "改2")
        assert r2.confirmed is False and r2.final is False
        r3 = engine.confirm_spec(outcome, "改3")
        assert r3.rounds == 3
        assert r3.final is True
        assert r3.spec_md == "最终收敛合并版"
        # 再提意见也不再修改、不再调用 LLM
        r4 = engine.confirm_spec(outcome, "还想改")
        assert r4.final is True
        assert r4.spec_md == "最终收敛合并版"
        assert llm.remaining == 0


class TestMessageRecording:
    """M11-2：讨论消息记录（对话流图数据源）。"""

    def test_messages_roles_and_order(self, fm):
        # 1 轮收敛：pm → dev_review → test_review → pm_converge
        llm = ScriptedLLM(positive_scripts())
        engine = make_engine(llm, file_manager=fm)
        engine.run_discussion("需求", _create(fm))
        roles = [m["role"] for m in engine.messages]
        assert roles == ["pm", "dev_review", "test_review", "pm_converge"]
        # 模型归属与角色一致（PM=主力档，评审A=dev 档，评审B=test 档）
        assert engine.messages[0]["model"] == "gpt-4o"
        assert engine.messages[1]["model"] == "deepseek-chat"
        assert engine.messages[2]["model"] == "claude-3-5-sonnet"
        # 全部消息带内容
        assert all(m["content"].strip() for m in engine.messages)

    def test_messages_round_numbering(self, fm):
        # 2 轮讨论：修订轮次正确递增（显式限定 max_discussion_rounds=2，
        # 否则默认 3 轮上限会让有弱点的评审继续跑第 3 轮）
        llm = ScriptedLLM(varying_scripts(2))
        engine = make_engine(
            llm, settings=Settings(max_discussion_rounds=2), file_manager=fm
        )
        engine.run_discussion("需求", _create(fm))
        rounds = [m["round"] for m in engine.messages]
        assert rounds == [0, 1, 1, 1, 2, 2, 2]  # pm0 → r1(评A/评B/修订) → r2(评A/评B) → 收敛
        assert engine.messages[3]["role"] == "pm_revise"
        assert engine.messages[-1]["role"] == "pm_converge"

    def test_messages_persisted_to_disk(self, fm):
        # 落盘 sessions/discussion_messages.json（流图数据源，审计口径）
        llm = ScriptedLLM(positive_scripts())
        engine = make_engine(llm, file_manager=fm)
        pid = _create(fm)
        engine.run_discussion("需求", pid)
        path = fm.get_project(pid).root / "sessions" / "discussion_messages.json"
        assert path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert [m["role"] for m in data] == ["pm", "dev_review", "test_review", "pm_converge"]

    def test_no_file_manager_no_crash(self):
        # 无 file_manager（纯讨论模式）→ 记录在内存，不落盘不报错
        llm = ScriptedLLM(positive_scripts())
        engine = make_engine(llm, file_manager=None)
        engine.run_discussion("需求", None)
        assert len(engine.messages) == 4
