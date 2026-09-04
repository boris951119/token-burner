"""次要补齐项测试（TDD 先行）。

覆盖三项：
- 11.2：输出截断（finish_reason=length）按未完成处理——分块续写拼接，
  不静默丢弃；续写次数有上限，仍截断则标记 truncated 交调用方决策；
- 6.3：组队路径落盘 sessions/difficulty_assessment.md（评估可审计）；
- 14.2 严重度表：签名不匹配（signature_mismatch）为**警告**不阻断；
  missing / extra（自创接口）仍阻断；警告进入验证报告与模块文档。
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.utils.model_client import LLMResponse


# ---------------------------------------------------------------------------
# 11.2 输出截断分块续写
# ---------------------------------------------------------------------------


def _resp_dict(content: str, finish: str = "stop", in_tok=10, out_tok=5):
    return {
        "choices": [
            {"message": {"content": content}, "finish_reason": finish}
        ],
        "usage": {"prompt_tokens": in_tok, "completion_tokens": out_tok},
    }


class _ScriptedCompletion:
    """按脚本顺序返回响应的桩（记录每次调用的 messages）。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs["messages"])
        return self.responses.pop(0)


class TestTruncationContinuation:
    @pytest.fixture(autouse=True)
    def _api_keys(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def _client(self, completion, **settings_over):
        from app.utils.model_client import ModelClient

        return ModelClient(
            Settings(**settings_over), completion_fn=completion
        )

    def test_length_triggers_continuation_and_concatenates(self):
        # 首次 length 截断 → 续写一次，内容拼接完整。
        # v1.0 V2.1（bench_v1 取证）：句中截断时续写头部的真实换行被剥除
        # （GLM 续写惯以换行开头，裸拼接产生 unterminated string literal），
        # 拼接结果不再含该换行——原期望「前半\n# 后半部分」随之修正。
        completion = _ScriptedCompletion([
            _resp_dict("def foo():\n    pass\n# 前半", finish="length"),
            _resp_dict("\n# 后半部分", finish="stop"),
        ])
        client = self._client(completion)
        result = client.chat("gpt-4o", [{"role": "user", "content": "写代码"}])
        assert result.content == "def foo():\n    pass\n# 前半# 后半部分"
        assert not result.truncated  # 续写后完整
        assert len(completion.calls) == 2

    def test_continuation_sends_partial_as_assistant(self):
        # 续写调用携带 assistant 部分内容 + 「继续」指令（上下文接续）
        completion = _ScriptedCompletion([
            _resp_dict("前半", finish="length"),
            _resp_dict("后半", finish="stop"),
        ])
        client = self._client(completion)
        client.chat("gpt-4o", [{"role": "user", "content": "写"}])
        cont_messages = completion.calls[1]
        roles = [m["role"] for m in cont_messages]
        assert "assistant" in roles
        assert any("继续" in m["content"] for m in cont_messages)

    def test_all_continuations_exhausted_marks_truncated(self):
        # 续写上限耗尽仍 length → truncated=True（按未完成交调用方，不静默）
        responses = [_resp_dict(f"块{i}", finish="length") for i in range(4)]
        completion = _ScriptedCompletion(responses)
        client = self._client(completion)  # 默认上限 2 次续写
        result = client.chat("gpt-4o", [{"role": "user", "content": "写"}])
        assert result.truncated
        assert len(completion.calls) == 3  # 1 次原始 + 2 次续写
        assert result.content == "块0块1块2"

    def test_stop_finish_no_continuation(self):
        # 正常 stop → 单次调用，无续写
        completion = _ScriptedCompletion([_resp_dict("完整输出")])
        client = self._client(completion)
        result = client.chat("gpt-4o", [{"role": "user", "content": "写"}])
        assert result.content == "完整输出"
        assert not result.truncated
        assert len(completion.calls) == 1

    def test_tokens_accumulated_across_continuations(self):
        # 续写的 token 用量全部计入累计与预算（11.0 总闸语义）
        completion = _ScriptedCompletion([
            _resp_dict("前半", finish="length", in_tok=100, out_tok=50),
            _resp_dict("后半", in_tok=120, out_tok=30),
        ])
        client = self._client(completion)
        result = client.chat("gpt-4o", [{"role": "user", "content": "写"}])
        assert result.total_tokens == 300  # 两次调用合并
        assert client.total_tokens_used == 300


# ---------------------------------------------------------------------------
# 6.3 difficulty_assessment.md 落盘
# ---------------------------------------------------------------------------


def _assessment() -> str:
    return json.dumps(
        {"difficulty_score": 7, "difficulty_level": "中", "task_type": "编程",
         "reason": "多模块系统", "estimated_files": 7},
        ensure_ascii=False,
    )


def _review() -> str:
    return json.dumps(
        {"scores": {"feasibility": 9, "security": 9, "maintainability": 9},
         "strengths": ["完善"], "weaknesses": [], "risks": []},
        ensure_ascii=False,
    )


class TestDifficultyAssessmentPersisted:
    def test_team_flow_persists_assessment(self, tmp_path):
        # 组队路径：评估结果落盘 sessions/difficulty_assessment.md
        from tests.test_pipeline import ScriptedLLM
        from tests.test_shared_regression import FakeExecutor
        from app.pipeline import Pipeline
        from app.tools.file_manager import FileManager

        fm = FileManager(projects_root=tmp_path / "projects")
        scripts = [
            _assessment(), "初始方案", _review(), _review(), "最终 spec",
            json.dumps({"modules": [
                {"name": "user", "responsibility": "用户", "dependencies": [], "priority": 1}
            ]}, ensure_ascii=False),
            json.dumps({"imports": [], "exports": ["core_fn"],
                        "public_api": ["core_fn"], "dependencies": []},
                       ensure_ascii=False),
            "def core_fn():\n    return 1\n", "TEST",
        ]
        pipeline = Pipeline(
            llm=ScriptedLLM(scripts), executor=FakeExecutor(["SUCCESS"]),
            settings=Settings(), file_manager=fm,
        )
        result = pipeline.run(
            requirement="开发用户系统",
            models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe", spec_confirm="确认",
        )
        assert result.kind == "team_flow"
        handle = fm.get_project(result.project_id)
        md = (handle.root / "sessions" / "difficulty_assessment.md").read_text(encoding="utf-8")
        assert "7" in md            # 难度分
        assert "编程" in md         # 任务类型
        assert "多模块系统" in md   # 评估理由
        assert "estimated_files" in md or "预估" in md or "7" in md  # 预估文件数


# ---------------------------------------------------------------------------
# 14.2 签名不匹配降为警告
# ---------------------------------------------------------------------------


_CONTRACT = {
    "imports": [],
    "exports": ["core_fn(a, b)"],
    "public_api": ["core_fn(a, b)"],
    "dependencies": [],
}


class TestSignatureMismatchWarning:
    def test_check_implementation_severity_split(self):
        # 14.2 严重度表：signature_mismatch=警告；missing/extra=阻断
        from app.utils.interface_check import check_implementation

        code = "def core_fn(a):\n    return a\n\n\ndef extra_fn():\n    return 1\n"
        issues = check_implementation("user", code, _CONTRACT)
        kinds = {i.kind for i in issues}
        assert "signature_mismatch" in kinds
        assert "extra" in kinds
        warnings = [i for i in issues if i.kind == "signature_mismatch"]
        assert all(i.severity == "warning" for i in warnings)
        blockers = [i for i in issues if i.kind != "signature_mismatch"]
        assert all(i.severity == "blocking" for i in blockers)

    def test_dev_loop_warns_but_passes_gate(self, tmp_path):
        # 仅签名不匹配 → 门禁通过（警告），不进修复循环
        from app.agents.dev_loop import DevLoopEngine
        from app.tools.file_manager import FileManager
        from tests.test_shared_regression import FakeExecutor, ScriptedLLM

        fm = FileManager(projects_root=tmp_path / "projects")
        project_id = fm.create_project("demo").project_id
        code = "def core_fn(a):\n    return a\n"  # 契约 (a, b) → 签名不符
        llm = ScriptedLLM([code, "TEST"])
        engine = DevLoopEngine(
            llm=llm, dev_model="deepseek-chat", test_model="claude",
            executor=FakeExecutor(["SUCCESS"]), settings=Settings(),
            file_manager=fm,
        )
        result = engine.run_module(
            "user", project_id=project_id, contract=_CONTRACT
        )
        assert result.status.value == "SUCCESS"
        assert result.fix_attempts == 0       # 警告不消耗修复轮
        assert "签名不一致" in result.message  # 警告可见（不静默）
        # 12.7：警告同步进模块文档
        md = (fm.get_project(project_id).root / "modules" / "user.md")
        assert not md.exists() or "签名不一致" in md.read_text(encoding="utf-8")

    def test_missing_still_blocks(self, tmp_path):
        # missing（契约声明未实现）仍阻断 → 进修复循环
        from app.agents.dev_loop import DevLoopEngine
        from app.tools.file_manager import FileManager
        from tests.test_shared_regression import FakeExecutor, ScriptedLLM

        fm = FileManager(projects_root=tmp_path / "projects")
        project_id = fm.create_project("demo").project_id
        code = "def other_fn():\n    return 1\n"  # core_fn 缺失
        llm = ScriptedLLM([code, "TEST", "def core_fn(a, b):\n    return a + b\n"])
        engine = DevLoopEngine(
            llm=llm, dev_model="deepseek-chat", test_model="claude",
            executor=FakeExecutor(["SUCCESS", "SUCCESS"]), settings=Settings(),
            file_manager=fm,
        )
        result = engine.run_module(
            "user", project_id=project_id, contract=_CONTRACT
        )
        assert result.fix_attempts == 1  # 阻断项触发修复
