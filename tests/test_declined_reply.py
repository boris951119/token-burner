"""M9-3 declined 出口语义测试：闲聊/无意义 → declined 附友好文案，三端适配。

设计锚点（v0.4.md M9-3）：
- 友好文案是确定性程序职责（不调 LLM——拒答本身就是为了省 token）；
- 固定文案不拼接需求原文，规避不可信文本进入 UI 的转义问题；
- 用户否认编程导致的 declined（15.3 确认链）保持原语义，无友好文案。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.main import _print_result
from app.orchestrator import Route, RoutingResult, TaskRouter
from app.pipeline import Pipeline, PipelineResult, DECLINED_REPLIES
from app.server import _result_dict
from app.tools.file_manager import FileManager
from app.utils.model_client import LLMResponse
from tests.test_fast_triage import ScriptedLLM, triage_json

_ROOT = Path(__file__).resolve().parent.parent


def _declined_route(task_type: str) -> RoutingResult:
    return RoutingResult(
        route=Route.DECLINED, task_type=task_type,
        difficulty_score=0, difficulty_level="未知", reason="[快判] r",
    )


def _pipeline(tmp_path, llm) -> Pipeline:
    return Pipeline(
        llm=llm, executor=None, settings=Settings(),
        file_manager=FileManager(projects_root=tmp_path / "projects"),
    )


# ---------------------------------------------------------------------------
# Pipeline：declined_reply 按意图填充
# ---------------------------------------------------------------------------

class TestPipelineDeclinedReply:
    def test_chitchat_gets_reply(self, tmp_path):
        result = _pipeline(tmp_path, ScriptedLLM([])).run(
            "你好", route=_declined_route("闲聊")
        )
        assert result.kind == "declined"
        assert result.declined_reply == DECLINED_REPLIES["闲聊"]
        assert "需求" in result.declined_reply  # 文案引导用户描述需求

    def test_meaningless_gets_distinct_reply(self, tmp_path):
        result = _pipeline(tmp_path, ScriptedLLM([])).run(
          "asdfgh", route=_declined_route("无意义")
        )
        assert result.declined_reply == DECLINED_REPLIES["无意义"]
        assert result.declined_reply != DECLINED_REPLIES["闲聊"]

    def test_unknown_task_type_falls_back(self, tmp_path):
        result = _pipeline(tmp_path, ScriptedLLM([])).run(
            "x", route=_declined_route("未知类型")
        )
        assert result.declined_reply != ""  # 默认兜底，永不为空

    def test_confirm_declined_keeps_empty_reply(self, tmp_path):
        """15.3 确认链拒绝：无友好文案（原语义不变）。"""
        llm = ScriptedLLM([])  # 评估解析失败 → 保守视作编程 + 确认
        result = _pipeline(tmp_path, llm).run("开发一个系统", confirmed_as_coding=False)
        assert result.kind == "declined"
        assert result.declined_reply == ""

    def test_declined_with_injected_route_skips_triage(self, tmp_path):
        """注入 route 直测管线：declined 分支自身零调用。

        注意：端到端时 FastTriage（M9-2）本就有 1 次轻量档 LLM 粗判调用
        （单次、不重试），「零调用」仅指 declined 分支不加任何调用。
        """
        llm = ScriptedLLM([])
        _pipeline(tmp_path, llm).run("你好", route=_declined_route("闲聊"))
        assert llm.calls == []


# ---------------------------------------------------------------------------
# 端到端：快判(闲聊, 高置信) → declined_reply（非空）
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_fast_triage_declined_carries_reply(self, tmp_path):
        settings = Settings(fast_triage_enabled=True)
        llm = ScriptedLLM([triage_json("闲聊", 0.95, "问候语")])
        pipeline = Pipeline(
            llm=llm, executor=None, settings=settings,
            file_manager=FileManager(projects_root=tmp_path / "projects"),
        )
        result = pipeline.run("你好")
        assert result.kind == "declined"
        assert result.declined_reply == DECLINED_REPLIES["闲聊"]


# ---------------------------------------------------------------------------
# 三端适配
# ---------------------------------------------------------------------------

class TestThreeEndpoints:
    def test_cli_prints_reply(self, capsys):
        _print_result(PipelineResult(
            kind="declined", declined_reply=DECLINED_REPLIES["闲聊"],
        ))
        assert DECLINED_REPLIES["闲聊"] in capsys.readouterr().out

    def test_cli_user_denied_keeps_old_message(self, capsys):
        _print_result(PipelineResult(kind="declined"))
        assert "用户否认" in capsys.readouterr().out

    def test_server_result_dict_includes_reply(self):
        payload = _result_dict(PipelineResult(
            kind="declined", declined_reply=DECLINED_REPLIES["无意义"],
        ))
        assert payload["declined_reply"] == DECLINED_REPLIES["无意义"]

    def test_server_result_dict_backward_compat(self):
        payload = _result_dict(PipelineResult(kind="declined"))
        assert payload["declined_reply"] == ""

    def test_client_html_renders_declined_reply(self):
        """client.html 单文件契约：存在 declined 分支并读取 declined_reply。"""
        html = (_ROOT / "client.html").read_text(encoding="utf-8")
        assert 'data.kind === "declined"' in html
        assert "data.declined_reply" in html
