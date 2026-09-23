"""Pipeline 端到端管线测试（TDD 先行，LLM 与 Executor 全 mock）。

依据：规格文档 3.1 节主流程、10.1 节 CLI 交互：
- 需求 → 评估路由 → 组队（预算闸门）→ 方案讨论（三层护栏）→
  spec 确认 → 模块拆分 → 接口契约 → 逐模块开发循环 → 交付物汇总；
- 交付物汇总（10.1 尾段）：项目目录、spec.md、模块代码、测试、
  验证报告与手动运行指引（安全模式）；
- 非编程任务：直接回答（DIRECT_OUTPUT），不创建项目目录；
- 简单编程：直出单文件代码（DIRECT_SIMPLE_CODING），不走团队流程；
- 保守降级（15.3）：评估解析失败 → 视作编程 + 需用户确认。
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.pipeline import Pipeline, PipelineResult
from app.utils.model_client import LLMResponse


class ScriptedLLM:
    """按序返回内容的多面手桩：记录调用（model, 首句类别）。

    与 ModelClient 对齐：支持 budget_guard 挂接（11.0 总闸）——
    调用前拦截超限、调用后累计用量。
    """

    def __init__(self, scripts: list[str]):
        self.scripts = list(scripts)
        self.calls: list[dict] = []
        self.call_log: list[dict] = []  # 与 ModelClient 对齐（8.5 仪表盘数据源）
        self.budget_guard = None        # 与 ModelClient 对齐（11.0 总闸）

    def chat(self, model, messages, json_mode=False):
        if self.budget_guard is not None:
            self.budget_guard.ensure_allowed()
        self.calls.append({"model": model, "json_mode": json_mode, "role": messages[0]["content"][:12]})
        content = self.scripts.pop(0) if self.scripts else "默认"
        self.call_log.append(
            {"model": model, "json_mode": json_mode, "input_tokens": 10,
             "output_tokens": 5, "content_chars": len(content),
             "system_hint": messages[0]["content"] if messages else ""}
        )
        response = LLMResponse(model=model, content=content, input_tokens=10, output_tokens=5)
        if self.budget_guard is not None:
            self.budget_guard.record(response.total_tokens)
        return response

    @property
    def remaining(self) -> int:
        return len(self.scripts)


class FakeExecutor:
    def __init__(self, statuses: list[str]):
        self.statuses = list(statuses)

    def run(self, code, tests, timeout, expected_output="", module=""):
        from app.execution.executor import ExecutionResult, ExecutionStatus
        status = self.statuses.pop(0) if self.statuses else "SUCCESS"
        return ExecutionResult(status=ExecutionStatus(status))


@pytest.fixture
def fm(tmp_path):
    from app.tools.file_manager import FileManager
    return FileManager(projects_root=tmp_path / "projects")


def assessment_json(task_type: str, score: int = 7) -> str:
    return json.dumps(
        {"difficulty_score": score, "difficulty_level": "中", "task_type": task_type,
         "reason": "理由"},
        ensure_ascii=False,
    )


def team_scripts() -> list[str]:
    """完整团队流程脚本：评估→初始方案→双评审→收敛spec→拆分→接口×3→码/测×3。"""
    positive = json.dumps(
        {"scores": {"feasibility": 9, "security": 9, "maintainability": 9},
         "strengths": ["完善"], "weaknesses": [], "risks": []},
        ensure_ascii=False,
    )
    split = json.dumps(
        {"modules": [
            {"name": "user", "responsibility": "用户管理", "dependencies": [], "priority": 1},
            {"name": "data", "responsibility": "数据存储", "dependencies": [], "priority": 1},
            {"name": "auth", "responsibility": "认证", "dependencies": ["user", "data"], "priority": 2},
        ]},
        ensure_ascii=False,
    )
    iface = lambda deps: json.dumps(
        {"imports": ["core_fn" for _ in deps] if deps else [],
         "exports": ["core_fn"],
         "public_api": ["core_fn"], "dependencies": deps},
        ensure_ascii=False,
    )
    # 与契约 exports 一致的可导入代码（auth 从 user/data 导入 core_fn）
    code_by_deps = lambda deps: (
        f"from {deps[0]} import core_fn as {deps[0]}_core_fn\n"
        f"from {deps[1]} import core_fn as {deps[1]}_core_fn\n"
        f"def core_fn():\n    return {deps[0]}_core_fn() + {deps[1]}_core_fn()\n"
        if deps else "def core_fn():\n    return 1\n"
    )
    # build_order：优先级升序 + 同级字典序 → data, user, auth
    dep_by_name = {"data": [], "user": [], "auth": ["user", "data"]}
    dep_sets = [dep_by_name[n] for n in ("data", "user", "auth")]
    scripts = [
        assessment_json("编程", 7),
        "初始方案",
        positive, positive,
        "最终 spec",
        split,
        iface([]), iface([]), iface(["user", "data"]),  # 接口按 split 顺序
    ]
    for deps in dep_sets:
        scripts.append(code_by_deps(deps))   # dev 写码（按 build_order 顺序）
        scripts.append("TEST")               # test 写测试
    return scripts


def make_pipeline(llm, executor, fm, settings=None) -> Pipeline:
    return Pipeline(
        llm=llm,
        executor=executor,
        settings=settings or Settings(),
        file_manager=fm,
    )


class TestDirectAnswer:
    def test_basic_task_direct_answer(self, fm):
        # 基础任务 → 直接回答，不建项目
        llm = ScriptedLLM([assessment_json("基础", 2), "直接回答内容"])
        result = make_pipeline(llm, FakeExecutor([]), fm).run("讲个笑话")
        assert result.kind == "direct_answer"
        assert result.answer == "直接回答内容"
        assert result.project_id is None
        assert not list(fm.projects_root.glob("*"))  # 未创建项目目录

    def test_research_task_direct_answer(self, fm):
        llm = ScriptedLLM([assessment_json("研究/分析", 8), "分析报告内容"])
        result = make_pipeline(llm, FakeExecutor([]), fm).run("分析区块链趋势")
        assert result.kind == "direct_answer"
        assert result.answer == "分析报告内容"


class TestSimpleCoding:
    def test_simple_coding_single_file(self, fm):
        # 简单编程（难度 ≤3）→ 直出单文件，不组队
        llm = ScriptedLLM([assessment_json("编程", 2), "print('hello')"])
        result = make_pipeline(llm, FakeExecutor([]), fm).run("写个 hello world")
        assert result.kind == "direct_code"
        assert result.answer == "print('hello')"
        assert result.project_id is None


class TestTeamFlow:
    def test_full_team_flow_deliverables(self, fm):
        # 完整团队流程 → 交付物齐备
        project_root = None
        llm = ScriptedLLM(team_scripts())
        pipeline = make_pipeline(llm, FakeExecutor(["SUCCESS"] * 3), fm)
        result = pipeline.run(
            "开发用户系统",
            models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe",
            spec_confirm="确认",
        )
        assert result.kind == "team_flow"
        assert result.project_id
        handle = fm.get_project(result.project_id)
        assert handle is not None
        root = handle.root
        # 交付物核验（6.3 + 10.1）：spec、模块、代码、测试、验证报告
        assert (root / "spec.md").is_file()
        assert (root / "modules" / "auth.md").is_file()
        assert (root / "interfaces.json").is_file()
        assert (root / "code" / "auth" / "auth.py").is_file()
        assert (root / "tests" / "auth" / "test_auth.py").is_file()
        assert (root / "changelog" / "auth" / "validation.md").is_file()

    def test_deliverable_summary_lists_components(self, fm):
        # 交付物汇总含：目录位置、模块清单、手动运行指引（安全模式）
        llm = ScriptedLLM(team_scripts())
        pipeline = make_pipeline(llm, FakeExecutor(["SUCCESS"] * 3), fm)
        result = pipeline.run(
            "开发用户系统",
            models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe",
            spec_confirm="确认",
        )
        summary = result.deliverable_summary
        assert str(result.project_dir) in summary
        assert "user" in summary and "auth" in summary
        assert "手动" in summary  # 安全模式手动运行指引

    def test_frozen_module_reported_in_summary(self, fm):
        # 有模块冻结 → 汇总如实报告（11.4：已知问题交用户）
        scripts = team_scripts()
        # 3 个模块全失败修复（3 码 + 3 测 + 每模块 3 轮修复码）
        scripts = scripts[:9]  # 评估+方案+评审+spec+拆分+接口
        for _ in range(3):
            scripts.append("x = broken(")  # 语法坏码 → 门禁失败
            scripts.append("TEST")
            scripts += ["x = 1", "x = 1", "x = 1"]  # 3 轮修复（接口门禁失败→冻结）
        llm = ScriptedLLM(scripts)
        settings = Settings(max_fix_rounds=3)
        pipeline = make_pipeline(llm, FakeExecutor([]), fm, settings=settings)
        result = pipeline.run(
            "开发用户系统",
            models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe",
            spec_confirm="确认",
        )
        assert result.kind == "team_flow"
        assert "冻结" in result.deliverable_summary or "失败" in result.deliverable_summary


class TestConservativeFallback:
    def test_unparseable_assessment_needs_confirm(self, fm):
        # 15.3：评估解析全失败 → 视作编程 + 需用户确认
        llm = ScriptedLLM(["不是JSON", "不是JSON", "不是JSON", "不是JSON", "直接输出"])
        pipeline = make_pipeline(llm, FakeExecutor([]), fm)
        result = pipeline.run("含糊需求")
        assert result.kind == "needs_confirm"
        assert result.needs_user_confirm is True

    def test_confirmed_fallback_enters_team_flow(self, fm):
        # 用户确认后 → 完整团队流程
        scripts = ["坏", "坏", "坏", "坏"] + team_scripts()[1:]
        llm = ScriptedLLM(scripts)
        pipeline = make_pipeline(llm, FakeExecutor(["SUCCESS"] * 3), fm)
        result = pipeline.run(
            "含糊需求",
            confirmed_as_coding=True,
            models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe",
            spec_confirm="确认",
        )
        assert result.kind == "team_flow"
        assert result.project_id

    def test_declined_fallback_not_entered(self, fm):
        # 用户否认是编程任务 → 终止（不消耗后续 token）
        llm = ScriptedLLM(["坏", "坏", "坏", "坏"])
        pipeline = make_pipeline(llm, FakeExecutor([]), fm)
        result = pipeline.run("含糊需求", confirmed_as_coding=False)
        assert result.kind == "declined"
        assert result.project_id is None
        assert llm.remaining == 0

    def test_generated_modules_importable_in_same_process(self, fm):
        # 回归：模块文件与模块同名（非 main.py）→ 多模块同进程导入互不冲突
        import os
        import subprocess
        import sys

        llm = ScriptedLLM(team_scripts())
        pipeline = make_pipeline(llm, FakeExecutor(["SUCCESS"] * 3), fm)
        result = pipeline.run(
            "开发用户系统",
            models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe",
            spec_confirm="确认",
        )
        handle = fm.get_project(result.project_id)
        code_root = handle.root / "code"
        # 同一 PYTHONPATH 下依次导入三模块（此前 main.py 命名会互相覆盖）
        probe = (
            "import sys; sys.path[:0] = [r'%s', r'%s', r'%s']; "
            "import user, data, auth; "
            "print(user.__file__); print(auth.__file__)"
            % (code_root / "user", code_root / "data", code_root / "auth")
        )
        # M17-2：stdout 走临时文件而非管道——CI runner 上管道捕获偶发
        # 返回 None（根因未明），文件承载语义确定
        out_file = handle.root / "_probe_stdout.txt"
        with open(out_file, "w", encoding="utf-8") as fh:
            proc = subprocess.run(
                [sys.executable, "-c", probe],
                stdout=fh, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", timeout=30,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            )
        assert proc.returncode == 0, proc.stderr
        content = out_file.read_text(encoding="utf-8")
        out_file.unlink(missing_ok=True)
        assert "auth.py" in content  # auth 来自 auth.py 而非 user/main.py
        assert "user.py" in content


class TestDirectChatLegRelay:
    """直出路径的换腿兜底（批次#22 同族：最便宜的出口原先最脆）。"""

    class _Flaky:
        def __init__(self, fail_first: bool, exc: Exception | None = None):
            self.calls: list[str] = []
            self.fail_first = fail_first
            self.exc = exc or RuntimeError("网关 m-a 调用失败: Timeout")

        def chat(self, model, messages, json_mode=False):
            self.calls.append(model)
            if self.fail_first and len(self.calls) == 1:
                raise self.exc
            return LLMResponse(model=model, content="直答内容",
                               input_tokens=1, output_tokens=1)

    def _pipeline(self, llm, fm):
        return make_pipeline(llm, FakeExecutor([]), fm,
                             settings=Settings(models=["m-a", "m-b"]))

    def test_gateway_timeout_falls_to_next_leg(self, fm):
        llm = self._Flaky(fail_first=True)
        out = self._pipeline(llm, fm)._direct_chat("系统提示", "讲个笑话")
        assert out == "直答内容"
        assert llm.calls == ["m-a", "m-b"]

    def test_healthy_first_leg_no_extra_call(self, fm):
        llm = self._Flaky(fail_first=False)
        assert self._pipeline(llm, fm)._direct_chat("s", "x") == "直答内容"
        assert llm.calls == ["m-a"]

    def test_config_error_does_not_walk_the_roster(self, fm):
        # 缺密钥换腿也没用（同供应商同密钥）：直穿交上层报 503
        from app.utils.model_client import MissingApiKeyError
        llm = self._Flaky(fail_first=True,
                          exc=MissingApiKeyError("需要环境变量 X"))
        with pytest.raises(MissingApiKeyError):
            self._pipeline(llm, fm)._direct_chat("s", "x")
        assert llm.calls == ["m-a"]

    def test_budget_exhausted_does_not_walk_the_roster(self, fm):
        from app.utils.budget import BudgetExceededError
        llm = self._Flaky(fail_first=True, exc=BudgetExceededError("总闸"))
        with pytest.raises(BudgetExceededError):
            self._pipeline(llm, fm)._direct_chat("s", "x")
        assert llm.calls == ["m-a"]


class TestSplitDegradation:
    """批次#24：拆分/接口环节的两种「形状未知」都不该谋杀整跑。

    彩排取证：SplitError 直穿 run 的 except Exception 分支＝现场落盘后
    继续上抛 = 整跑 rc=1 零交付；而 15.3 降级评估把分数与文件数都写成
    占位 0，should_modularize 顺理成章判假——大需求被当成小任务塞进
    单模块。两处同向修：形状未知按大做，实在拆不动退回单模块交一份能跑
    的代码，好过零分。
    """

    def test_degraded_assessment_still_modularizes(self, fm, monkeypatch):
        from app.agents.module_builder import ModuleBuilder

        seen: list[str] = []
        original = ModuleBuilder.split_spec

        def spy(self, spec_md, project_id=None, requirement=""):
            seen.append(spec_md)
            return original(self, spec_md, project_id=project_id,
                            requirement=requirement)

        monkeypatch.setattr(ModuleBuilder, "split_spec", spy)
        scripts = ["坏", "坏", "坏", "坏"] + team_scripts()[1:]
        pipeline = make_pipeline(
            ScriptedLLM(scripts), FakeExecutor(["SUCCESS"] * 3), fm
        )
        result = pipeline.run(
            "含糊需求",
            confirmed_as_coding=True,
            models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe",
            spec_confirm="确认",
        )
        assert result.kind == "team_flow"
        assert seen, "降级评估（分数 0 是占位值）不该顺手判成单模块小任务"

    def test_split_error_falls_back_to_single_module(self, fm, monkeypatch):
        from app.agents.module_builder import ModuleBuilder, SplitError

        def boom(self, spec_md, project_id=None, requirement=""):
            raise SplitError("spec 拆分失败（重试 4 次）: 网关瞬态，请用户介入")

        monkeypatch.setattr(ModuleBuilder, "split_spec", boom)
        # 评估→方案→双评审→spec 照旧，拆分之后的脚本按单模块（码/测各一次）
        scripts = team_scripts()[:5] + ["def core_fn():\n    return 1\n", "TEST"]
        pipeline = make_pipeline(
            ScriptedLLM(scripts), FakeExecutor(["SUCCESS"]), fm
        )
        result = pipeline.run(
            "开发用户系统",
            models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
            mode="safe",
            spec_confirm="确认",
        )
        assert result.kind == "team_flow"
        root = fm.get_project(result.project_id).root
        assert (root / "code" / "main" / "main.py").is_file()
        assert not (root / "interfaces.json").exists()
        assert "main" in result.deliverable_summary  # 汇总如实报单模块
