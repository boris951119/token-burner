"""call_log 生命周期测试（产品审计问题 7 修复，TDD 先行）。

问题：
1. 跨任务污染——_build_dashboard 从全量 call_log 构建，上一任务的
   调用会被算进本任务的成本看板（预算基线切片只用于 guard，看板没用）；
2. 内存无限增长——call_log 跨任务只增不减，长会话（CLI 循环 / Web
   常驻）内存膨胀。

修复约定：
- Pipeline 维护任务级基线（_task_baseline）：看板只统计本任务切片；
- 团队流任务终态（完成 / 预算中止 / 中断 / 异常）后 finally 清空
  call_log——该任务的看板已构建并 persist 落盘，内存条目无后续消费者；
- resume 同样从自身基线起算（中断任务条目已随中断清场）。
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.pipeline import Pipeline
from app.tools.file_manager import FileManager


def _resp(content: str, finish: str = "stop"):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


class LoggingLLM:
    """记录 call_log 的桩（team_flow 最小剧本：评估→直答级路径不适用）。

    剧本驱动：每次 chat 弹出一个脚本项；直答路径用 direct_ 前缀剧本。
    """

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.call_log = []
        self.budget_guard = None

    def chat(self, model, messages, json_mode=False, **kw):
        from app.utils.model_client import LLMResponse
        if self.budget_guard is not None:
            self.budget_guard.ensure_allowed()  # 模拟 ModelClient 拦截行为
        content = self.scripts.pop(0)
        self.call_log.append({
            "model": model, "kind": "chat", "json_mode": json_mode,
            "input_tokens": 100, "output_tokens": 50,
            "content_chars": len(content),
            "system_hint": messages[0]["content"] if messages else "",
        })
        return LLMResponse(model=model, content=content,
                           input_tokens=100, output_tokens=50)

    def embed(self, model, text):
        return [0.0, 1.0]


class FakeExecutor:
    def run(self, code, tests, timeout, expected_output="", module=""):
        from app.execution.executor import ExecutionResult, ExecutionStatus
        return ExecutionResult(status=ExecutionStatus.SUCCESS)


def _assessment_json(score=7, files=7):
    return json.dumps({"task_type": "编程", "difficulty_score": score,
                       "reason": "多模块", "estimated_files": files},
                      ensure_ascii=False)


def _review():
    return json.dumps({"scores": {"feasibility": 9, "security": 9, "maintainability": 9},
                       "strengths": [], "weaknesses": [], "risks": []},
                      ensure_ascii=False)


def _split():
    return json.dumps({"modules": [
        {"name": "user", "responsibility": "用户", "dependencies": [], "priority": 1},
    ]}, ensure_ascii=False)


def _iface():
    return json.dumps({"imports": [], "exports": ["core_fn"],
                       "public_api": ["core_fn"], "dependencies": []},
                      ensure_ascii=False)


_SINGLE_MODULE_SCRIPTS = [
    _assessment_json(), "初始方案", _review(), _review(), "最终 spec",
    _split(), _iface(),
    "def core_fn():\n    return 1\n", "TEST_user",
]


def _pipeline(llm, fm):
    return Pipeline(llm=llm, executor=FakeExecutor(),
                    settings=Settings(), file_manager=fm)


@pytest.fixture
def fm(tmp_path):
    return FileManager(projects_root=tmp_path / "projects")


class TestCallLogLifecycle:
    def test_dashboard_excludes_prior_task_entries(self, fm):
        # 同一客户端：任务 1 直答（评估+回答，残留 2 条）→ 任务 2 团队流
        # → 看板只统计任务 2 的条目（切片隔离，不受残留污染）
        llm = LoggingLLM([
            '{"task_type": "基础", "difficulty_score": 1, "reason": "简单"}',
            "直答内容",
            *_SINGLE_MODULE_SCRIPTS,
        ])
        # 任务 1：直答（call_log 残留 2 条——直答路径无 finally 清理）
        r1 = _pipeline(llm, fm).run("你好")
        assert r1.kind == "direct_answer"
        leftover = len(llm.call_log)
        assert leftover == 2

        # 任务 2：团队流 → 看板只含任务 2 的 9 条调用（不含直答残留）
        result = _pipeline(llm, fm).run(
            "单模块系统", models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe", spec_confirm="确认",
        )
        assert result.kind == "team_flow"
        assert len(result.cost_dashboard.records) == len(_SINGLE_MODULE_SCRIPTS)
        assert llm.call_log == []  # 任务 2 结束也清场（直答残留一并释放）

    def test_team_flow_finally_clears_call_log(self, fm):
        # 团队流终态 → finally 清空 call_log（内存释放；看板已 persist）
        llm = LoggingLLM(_SINGLE_MODULE_SCRIPTS)
        result = _pipeline(llm, fm).run(
            "单模块系统", models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe", spec_confirm="确认",
        )
        assert result.kind == "team_flow"
        assert result.cost_dashboard.total_tokens > 0  # 看板已捕获
        assert llm.call_log == []                      # 内存已清

    def test_budget_stop_dashboard_is_task_scoped(self, fm):
        # 预算中止路径：看板仍含本任务全量（finally 之前构建），随后清空
        small = Settings(max_task_tokens=1)  # 极小预算 → 必然中止
        llm = LoggingLLM(_SINGLE_MODULE_SCRIPTS)
        pipeline = Pipeline(llm=llm, executor=FakeExecutor(),
                            settings=small, file_manager=fm)
        result = pipeline.run(
            "单模块系统", models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe", spec_confirm="确认",
        )
        assert result.kind == "budget_exceeded"
        assert result.cost_dashboard is not None
        assert llm.call_log == []

    def test_dashboard_persisted_before_clear(self, fm):
        # 清空前看板已落盘项目 logs/（审计不丢）
        llm = LoggingLLM(_SINGLE_MODULE_SCRIPTS)
        result = _pipeline(llm, fm).run(
            "单模块系统", models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe", spec_confirm="确认",
        )
        root = fm.get_project(result.project_id).root
        report = root / "logs" / "cost_report.json"
        assert report.is_file()
        payload = json.loads(report.read_text(encoding="utf-8"))
        assert payload["total_tokens"] > 0
