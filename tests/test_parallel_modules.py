"""v1.2 S0 测试:无依赖模块并行开发(层间拓扑、同层并发)。

paid_pilot/full 基准的加速前置:同一依赖层的模块并发开发,
层间仍按拓扑序。module_parallelism 缺省 1 = 串行(行为与 v1.0 一致)。
"""

from __future__ import annotations

import json
import re
import threading
import time

import pytest

from app.config import Settings
from app.pipeline import Pipeline
from tests.test_pipeline import FakeExecutor, assessment_json, team_scripts


class RoutingLLM:
    """按提示词内容路由的并行安全桩。

    前 9 次调用为团队流固定序列(评估/讨论/评审×2/收敛/拆分/契约×3),
    按序返回;此后进入模块开发(并发,顺序不定),按 system(开发/测试)
    与 user(模块名)路由返回。code 调用可注入延迟(测并发时序)。
    """

    def __init__(self, code_sleep: float = 0.0):
        self.calls = []           # (system_head, user_content, json_mode)
        self.lock = threading.Lock()
        self.code_sleep = code_sleep
        positive = json.dumps(
            {"scores": {"feasibility": 9, "security": 9, "maintainability": 9},
             "strengths": ["完善"], "weaknesses": [], "risks": []},
            ensure_ascii=False)
        split = json.dumps(
            {"modules": [
                {"name": "user", "responsibility": "用户管理",
                 "dependencies": [], "priority": 1},
                {"name": "data", "responsibility": "数据存储",
                 "dependencies": [], "priority": 1},
                {"name": "auth", "responsibility": "认证",
                 "dependencies": ["user", "data"], "priority": 2},
            ]}, ensure_ascii=False)
        iface = lambda deps: json.dumps(
            {"imports": [], "exports": ["core_fn"],
             "public_api": ["core_fn"], "dependencies": deps},
            ensure_ascii=False)
        self.team = [assessment_json("编程", 7), "初始方案",
                     positive, positive, "最终 spec", split,
                     iface([]), iface([]), iface(["user", "data"])]
        self.code = {
            "user": "def core_fn():\n    return 1\n",
            "data": "def core_fn():\n    return 2\n",
            "auth": ("from user import core_fn as u\n"
                     "from data import core_fn as d\n"
                     "def core_fn():\n    return u() + d()\n"),
        }
        self.tests = {
            "user": "from user import core_fn\n\ndef test_u():\n    assert core_fn() == 1\n",
            "data": "from data import core_fn\n\ndef test_d():\n    assert core_fn() == 2\n",
            "auth": ("from auth import core_fn\n\ndef test_a():\n"
                     "    assert core_fn() == 3\n"),
        }

    def chat(self, model, messages, json_mode=False):
        system = messages[0]["content"]
        user = messages[-1]["content"]
        with self.lock:
            self.calls.append((system[:20], user[:40], json_mode))
        n = len(self.calls)
        # 1) 模块开发(并发段):system 角色限定开发/测试工程师
        # (契约生成的 prompt 同样含「模块名」,system 是架构师——须排除)
        if "模块名：" in user and ("开发工程师" in system or "测试工程师" in system):
            module = re.search(r"模块名：(\w+)", user).group(1)
            content = (self.tests if "测试工程师" in system else self.code)[module]
            if "测试工程师" not in system and self.code_sleep:
                time.sleep(self.code_sleep)
            return self._resp(content)
        # 2) 逻辑审查(auto 模式默认不调用;safe 模式返回 pass)
        if json_mode and ("审查" in system or "逻辑" in system):
            return self._resp('{"verdict": "pass"}')
        # 3) 团队流固定序列(评估/方案/评审/收敛/拆分/契约×3,串行段)
        return self._resp(self.team[n - 1] if n <= len(self.team) else self.team[-1])

    def _resp(self, content):
        R = type("R", (), {})
        r = R()
        r.content = content
        r.usage = {"prompt_tokens": 1, "completion_tokens": 1}
        r.choices = [{"finish_reason": "stop"}]
        return r


def _routing_pipeline(llm, fm, executor, parallelism):
    settings = Settings(
        module_parallelism=parallelism,
        logic_review_enabled=False,
    )
    return Pipeline(llm=llm, executor=executor, settings=settings, file_manager=fm)


RUN_KW = dict(
    requirement="开发用户系统",
    models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
    mode="auto", auto_mode_confirmed=True, spec_confirm="确认",
)


class TestDependencyLayers:
    def test_independent_same_layer(self):
        layers = Pipeline._dependency_layers(
            ["a", "b"], {"a": {"dependencies": []}, "b": {"dependencies": []}})
        assert layers == [["a", "b"]]

    def test_chain_splits_layers(self):
        layers = Pipeline._dependency_layers(
            ["a", "b", "c"],
            {"a": {"dependencies": []},
             "b": {"dependencies": ["a"]},
             "c": {"dependencies": ["b"]}})
        assert layers == [["a"], ["b"], ["c"]]

    def test_mixed_layers(self):
        layers = Pipeline._dependency_layers(
            ["a", "b", "c"],
            {"a": {"dependencies": []},
             "b": {"dependencies": ["a"]},
             "c": {"dependencies": []}})
        assert layers == [["a", "c"], ["b"]]

    def test_build_order_three_modules(self):
        """team_scripts 的 2+1 依赖结构:user/data 同层,auth 独层。"""
        layers = Pipeline._dependency_layers(
            ["data", "user", "auth"],
            {"data": {"dependencies": []},
             "user": {"dependencies": []},
             "auth": {"dependencies": ["data", "user"]}})
        assert layers == [["data", "user"], ["auth"]]


class TestParallelExecution:
    def test_parallel_modules_overlap_and_succeed(self, tmp_path):
        """同层两模块并发:执行区间重叠,三模块全 SUCCESS 且零冻结。"""
        import threading

        from app.tools.file_manager import FileManager

        spans, lock = {}, threading.Lock()
        base = RoutingLLM(code_sleep=0.6)  # 写码调用持锁 0.6s,重叠即可观测
        orig_chat = base.chat

        def timed_chat(model, messages, json_mode=False):
            if ("模块名：" in messages[-1]["content"]
                    and "开发工程师" in messages[0]["content"]):
                m = re.search(r"模块名：(\w+)", messages[-1]["content"]).group(1)
                s0 = time.time()
                r = orig_chat(model, messages, json_mode=json_mode)
                with lock:
                    spans[m] = (s0, time.time())
                return r
            return orig_chat(model, messages, json_mode=json_mode)

        base.chat = timed_chat
        fm = FileManager(projects_root=tmp_path / "p")
        pipeline = _routing_pipeline(base, fm, FakeExecutor(["SUCCESS"] * 9), 2)
        result = pipeline.run(**RUN_KW)
        assert result.kind == "team_flow"
        assert result.frozen_modules == [], "并行层内模块应全部通过"
        for m in ("user", "data", "auth"):
            assert (fm.get_project(result.project_id).root / "code" / m / f"{m}.py").is_file()
        # 同层 user/data 的写码区间必须重叠(并发直接证据)
        assert "user" in spans and "data" in spans, f"span 缺失: {spans}"
        overlap = min(spans["user"][1], spans["data"][1]) - max(spans["user"][0], spans["data"][0])
        assert overlap > 0, f"同层模块未并发: {spans}"

    def test_serial_default_when_parallelism_one(self, tmp_path):
        """缺省 module_parallelism=1 → 串行(行为与 v1.0 一致),功能等价。"""
        from app.tools.file_manager import FileManager

        llm = RoutingLLM()
        fm = FileManager(projects_root=tmp_path / "p")
        pipeline = _routing_pipeline(llm, fm, FakeExecutor(["SUCCESS"] * 9), 1)
        result = pipeline.run(**RUN_KW)
        assert result.kind == "team_flow"
        assert result.frozen_modules == [] and result.project_id

    def test_module_done_order_respects_layers(self, tmp_path):
        """auth 的完成事件必须晚于 user/data(依赖层语义)。"""
        from app.tools.file_manager import FileManager

        llm = RoutingLLM()
        fm = FileManager(projects_root=tmp_path / "p")
        pipeline = _routing_pipeline(llm, fm, FakeExecutor(["SUCCESS"] * 9), 2)
        seen = []
        pipeline._on_event = lambda k, d: (
            seen.append(d.get("module")) if k == "module_done" else None)
        pipeline.run(**RUN_KW)
        assert seen.index("auth") > seen.index("user")
        assert seen.index("auth") > seen.index("data")
