"""ArcBenchBridge：SDK 未安装时的 no-op 保证 + 事件映射（注入桩验证）。"""

import sys
import types

from app.arcbench_bridge import ArcBenchBridge


class _FakeEvents:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def _rec(self, name):
        def fn(*args) -> None:
            self.calls.append((name, args))

        return fn

    def __getattr__(self, name):
        return self._rec(name)


class _FakeTraceability:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def init_db(self, *, reset: bool = False) -> None:
        self.calls.append(("init_db", {}))

    def store_requirement_tree(self, tree) -> None:
        self.calls.append(("store_requirement_tree", tree))

    def upsert_interface(self, **kwargs) -> None:
        self.calls.append(("upsert_interface", kwargs))

    def upsert_test(self, **kwargs) -> None:
        self.calls.append(("upsert_test", kwargs))

    def upsert_node_contract(self, req_id, content) -> None:
        self.calls.append(("upsert_node_contract", (req_id, content)))

    def upsert_scenario(self, **kwargs) -> None:
        self.calls.append(("upsert_scenario", kwargs))

    def list_interfaces(self, *, req_id=None):
        return [{"interface_id": f"{req_id}::sym_a"},
                {"interface_id": f"{req_id}::sym_b"}]

    def set_interface_implemented(self, interface_id, implemented) -> None:
        self.calls.append(
            ("set_interface_implemented", (interface_id, implemented))
        )


class _FakeGit:
    def __init__(self) -> None:
        self.commits: list[str] = []
        self.gitignore_writes = 0

    def commit(self, message: str) -> None:
        self.commits.append(message)

    def ensure_arc_gitignore(self) -> None:
        self.gitignore_writes += 1


class _FakeRuntime:
    def __init__(self) -> None:
        self.events = _FakeEvents()
        self.traceability = _FakeTraceability()
        self.git = _FakeGit()


def _names(fake: _FakeEvents) -> list[str]:
    return [name for name, _ in fake.calls]


def test_success_module_maps_to_implementation_and_test_passed():
    rt = _FakeRuntime()
    bridge = ArcBenchBridge(runtime=rt)
    bridge.handle(
        "module_done",
        {"module": "cli", "status": "SUCCESS", "fix_attempts": 0, "message": "ok"},
    )
    assert ("mark_implementation_done", ("cli", "ok")) in rt.events.calls
    assert ("mark_test_passed", ("cli", "ok")) in rt.events.calls
    assert rt.git.commits == ["module:cli SUCCESS"]


def test_frozen_module_maps_to_test_failed():
    rt = _FakeRuntime()
    bridge = ArcBenchBridge(runtime=rt)
    bridge.handle(
        "module_done",
        {"module": "auth", "status": "FROZEN", "fix_attempts": 3, "message": ""},
    )
    assert ("mark_test_failed", ("auth", None)) in rt.events.calls
    assert "mark_test_passed" not in _names(rt.events)


def test_node_map_rewrites_module_ids():
    rt = _FakeRuntime()
    bridge = ArcBenchBridge(node_map={"cli": "REQ-3"}, runtime=rt)
    bridge.handle(
        "module_done",
        {"module": "cli", "status": "SUCCESS", "fix_attempts": 0, "message": "ok"},
    )
    assert ("mark_test_passed", ("REQ-3", "ok")) in rt.events.calls


def test_unknown_and_lifecycle_events_flow_through():
    rt = _FakeRuntime()
    bridge = ArcBenchBridge(runtime=rt)
    bridge.handle("stage", {"stage": "模块开发"})
    bridge.handle("tokens", {"tokens": 42, "model": "x"})
    bridge.run_started("go")
    bridge.run_completed("done")
    bridge.run_failed("bad")
    assert _names(rt.events) == [
        "mark_run_started",
        "mark_run_completed",
        "mark_run_failed",
    ]


def test_terminal_state_restamps_gitignore():
    """交付用 copy2 把 code/.gitignore 盖到输出根，官方管理块（.env 不进
    提交 / .arc/traceability 必进提交）就没了——终态必须重申一次。"""
    rt = _FakeRuntime()
    bridge = ArcBenchBridge(runtime=rt)
    bridge.run_started("go")
    assert rt.git.gitignore_writes == 0     # 注入桩不走装配
    bridge.run_completed("done")
    bridge.run_failed("bad")
    assert rt.git.gitignore_writes == 2     # 两个终态各钉一次


def test_handle_swallows_internal_errors():
    class _BoomRuntime:
        @property
        def events(self):
            raise RuntimeError("boom")

    bridge = ArcBenchBridge(runtime=_BoomRuntime())
    bridge.handle("module_done", {"module": "x", "status": "SUCCESS"})
    bridge.run_started("x")  # 不上抛即可


# ---- factory26 增强：契约登记 / tests 登记 / FOLDER 模糊映射 ----

_TREE = {
    "name": "demo",
    "children": [
        {"type": "FOLDER", "id": "F1", "name": "Authentication", "children": []},
        {"type": "FOLDER", "id": "F2", "name": "Train Search", "children": []},
        {"type": "FOLDER", "id": "F3", "name": "Booking", "children": []},
    ],
}


def _tree_bridge(rt=None) -> ArcBenchBridge:
    bridge = ArcBenchBridge(runtime=rt or _FakeRuntime())
    bridge.store_tree(_TREE)
    return bridge


class TestMatchFolder:
    def test_exact_match(self):
        bridge = _tree_bridge()
        assert bridge._node("Booking") == "F3"

    def test_containment_match(self):
        bridge = _tree_bridge()
        assert bridge._node("train_search") == "F2"

    def test_prefix_match(self):
        bridge = _tree_bridge()
        assert bridge._node("auth") == "F1"

    def test_no_match_falls_back_to_module_name(self):
        bridge = _tree_bridge()
        assert bridge._node("app_shell") == "app_shell"

    def test_explicit_node_map_wins(self):
        bridge = ArcBenchBridge(
            node_map={"auth": "REQ-99"}, runtime=_FakeRuntime()
        )
        bridge.store_tree(_TREE)
        assert bridge._node("auth") == "REQ-99"


class TestInterfacesReady:
    def test_upserts_interface_per_export_and_marks_design_done(self):
        rt = _FakeRuntime()
        bridge = _tree_bridge(rt)
        bridge.handle(
            "interfaces_ready",
            {"interfaces": {
                "auth": {"exports": ["login(user, pwd)"], "public_api": []},
                "booking": {"exports": ["book(train)"], "public_api": []},
            }},
        )
        upserts = [c for c in rt.traceability.calls if c[0] == "upsert_interface"]
        assert upserts[0][1]["interface_id"] == "auth::login"
        assert upserts[0][1]["req_ids"] == ["F1"]
        assert upserts[0][1]["implemented"] is False
        design_done = [c for c in rt.events.calls
                       if c[0] == "mark_design_done"]
        assert {c[1][0] for c in design_done} == {"F1", "F3"}

    def test_node_contract_registered_verbatim(self):
        """契约原文进 node_contracts：官方节点契约面板由此才有数据，
        而 avg_feature_implementation_rate 的口径就是 traceability 登记。"""
        rt = _FakeRuntime()
        bridge = _tree_bridge(rt)
        bridge.handle("interfaces_ready", {"interfaces": {
            "auth": {"exports": ["login(u, p)"], "public_api": ["login(u, p)"],
                     "dependencies": ["db"]}}})
        contracts = [c for c in rt.traceability.calls
                     if c[0] == "upsert_node_contract"]
        assert contracts[0][1] == ("F1", {
            "module": "auth", "exports": ["login(u, p)"],
            "public_api": ["login(u, p)"], "dependencies": ["db"]})

    def test_one_module_boom_does_not_erase_the_rest(self):
        """旧写法整段一个 try：第一个模块抛错＝后面所有模块的登记一起没了。"""
        class _PartialTrace(_FakeTraceability):
            def upsert_interface(self, **kwargs):
                if kwargs["interface_id"].startswith("auth::"):
                    raise RuntimeError("auth 登记炸了")
                super().upsert_interface(**kwargs)

        rt = _FakeRuntime()
        rt.traceability = _PartialTrace()
        bridge = _tree_bridge(rt)
        bridge.handle("interfaces_ready", {"interfaces": {
            "auth": {"exports": ["login(u, p)"], "public_api": []},
            "booking": {"exports": ["book(t)"], "public_api": []}}})
        done = {c[1][0] for c in rt.events.calls
                if c[0] == "mark_design_done"}
        assert done == {"F3"}  # auth 那格没走到设计完成，booking 照登
        assert [c[1]["interface_id"] for c in rt.traceability.calls
                if c[0] == "upsert_interface"] == ["booking::book"]


class TestModuleTestRegistration:
    def test_success_registers_passing_test_and_implements_interfaces(self):
        rt = _FakeRuntime()
        bridge = _tree_bridge(rt)
        bridge.handle(
            "module_done",
            {"module": "auth", "status": "SUCCESS", "fix_attempts": 0},
        )
        tests = [c for c in rt.traceability.calls if c[0] == "upsert_test"]
        assert tests[0][1]["test_id"] == "test_auth"
        assert tests[0][1]["req_id"] == "F1"
        assert tests[0][1]["passed"] is True
        impl = [c for c in rt.traceability.calls
                if c[0] == "set_interface_implemented"]
        assert len(impl) == 2
        assert all(c[1][1] is True for c in impl)

    def test_frozen_registers_failing_test(self):
        rt = _FakeRuntime()
        bridge = _tree_bridge(rt)
        bridge.handle(
            "module_done",
            {"module": "booking", "status": "FROZEN", "fix_attempts": 3},
        )
        tests = [c for c in rt.traceability.calls if c[0] == "upsert_test"]
        assert tests[0][1]["passed"] is False
        assert [c for c in rt.traceability.calls
                if c[0] == "set_interface_implemented"] == []


class TestScenarioBackfill:
    """官方题面的 scenario 从不带 id，而 SDK 拿 id 当主键 → 表恒空。"""

    TREE = {
        "id": "ROOT", "type": "FOLDER", "children": [
            {"id": "REQ-1", "type": "FOLDER", "name": "Link Directory",
             "children": [
                 {"id": "REQ-1.1", "type": "ATOMIC", "name": "Enter Website",
                  "scenarios": [
                      {"name": "Enter Website", "steps": [
                          {"keyword": "WHEN", "content": "Open the entry URL"},
                      ]},
                      {"name": "Enter Website", "steps": []},
                      {"id": "S-OFFICIAL", "name": "题面自带主键", "steps": []},
                  ]},
             ]},
        ],
    }

    def _scenarios(self, rt):
        return [c[1] for c in rt.traceability.calls
                if c[0] == "upsert_scenario"]

    def test_idless_scenarios_get_derived_keys(self):
        rt = _FakeRuntime()
        ArcBenchBridge(runtime=rt).store_tree(self.TREE)
        registered = self._scenarios(rt)
        assert [s["scenario_id"] for s in registered] == [
            "REQ-1.1::enterwebsite", "REQ-1.1::enterwebsite#2",
        ]
        assert registered[0]["req_id"] == "REQ-1.1"
        assert registered[0]["steps"] == [
            {"keyword": "WHEN", "content": "Open the entry URL"}]

    def test_official_scenario_ids_left_alone(self):
        rt = _FakeRuntime()
        ArcBenchBridge(runtime=rt).store_tree(self.TREE)
        assert all("S-OFFICIAL" not in s["scenario_id"]
                   for s in self._scenarios(rt))


class TestBootstrapWithoutGit:
    """生产惰性装配：官方容器无 git 二进制时的 resilience。

    runA/runB 彩排取证（9/23）：旧实现把 self._runtime 赋值排在
    ensure_repo 之后，而 ensure_repo 要 subprocess 调 git ——
    FileNotFoundError 一抛，单例永远立不起来，每次 _rt() 都重跑
    from_env+init_db（runner-events.jsonl 只剩 7 条
    traceability_store_initialized、零条业务事件），traceability 七张表
    交付时全空 {}，平台的 feature_implementation_rate（靠接口/测试登记
    激活）直接挂零。
    """

    class _Git:
        def __init__(self, git_available: bool):
            self.git_available = git_available
            self.gitignore_writes = 0
            self.commit_attempts = 0

        def ensure_arc_gitignore(self):
            self.gitignore_writes += 1

        def ensure_repo(self, *, create_initial_commit: bool = True) -> None:
            if not self.git_available:
                raise FileNotFoundError(2, "No such file or directory: 'git'")

        def commit(self, message: str) -> None:
            self.commit_attempts += 1
            if not self.git_available:
                raise FileNotFoundError(2, "No such file or directory: 'git'")

    class _Runtime:
        def __init__(self, git_available: bool = False):
            self.events = _FakeEvents()
            self.traceability = _FakeTraceability()
            self.git = TestBootstrapWithoutGit._Git(git_available)

    def _install_fake_sdk(self, monkeypatch, runtime, calls: list):
        class _AgentRuntime:
            @staticmethod
            def from_env():
                calls.append("from_env")
                return runtime

        monkeypatch.setitem(
            sys.modules, "arcbench_agent_runtime",
            types.SimpleNamespace(AgentRuntime=_AgentRuntime))

    def test_gitless_container_still_reports_and_bootstraps_once(self, monkeypatch):
        rt = self._Runtime(git_available=False)
        calls: list = []
        self._install_fake_sdk(monkeypatch, rt, calls)
        bridge = ArcBenchBridge()  # 不注入：走真惰性 import 分支
        bridge.run_started("go")
        bridge.handle("module_done", {"module": "auth", "status": "SUCCESS",
                                      "fix_attempts": 0, "message": "ok"})
        bridge.run_completed("done")
        assert _names(rt.events) == [
            "mark_run_started", "mark_implementation_done",
            "mark_test_passed", "mark_run_completed",
        ]
        assert [c[0] for c in rt.traceability.calls] == [
            "init_db", "upsert_test", "set_interface_implemented",
            "set_interface_implemented",
        ]
        assert calls == ["from_env"]  # 旧行为：三个调用点各重装配一次
        assert bridge._git_ready is False

    def test_gitignore_written_even_without_git(self, monkeypatch):
        """ensure_arc_gitignore 不调 git，且它才是「.env 不提交／
        .arc/traceability 必须提交」的那份清单——旧顺序挂在 ensure_repo
        同一个失败域后面，无 git 时从未落地。"""
        rt = self._Runtime(git_available=False)
        self._install_fake_sdk(monkeypatch, rt, [])
        ArcBenchBridge().run_started("go")
        assert rt.git.gitignore_writes == 1

    def test_failed_git_repo_skips_per_module_commit(self, monkeypatch):
        rt = self._Runtime(git_available=False)
        self._install_fake_sdk(monkeypatch, rt, [])
        bridge = ArcBenchBridge()
        for module in ("auth", "booking"):
            bridge.handle("module_done", {"module": module,
                                          "status": "SUCCESS",
                                          "fix_attempts": 0})
        assert rt.git.commit_attempts == 0
        assert len(_names(rt.events)) == 4  # 事件照报，只是没有提交历史

    def test_git_available_keeps_commit_history(self, monkeypatch):
        rt = self._Runtime(git_available=True)
        self._install_fake_sdk(monkeypatch, rt, [])
        bridge = ArcBenchBridge()
        bridge.handle("module_done", {"module": "auth", "status": "SUCCESS",
                                      "fix_attempts": 0})
        assert bridge._git_ready is True
        assert rt.git.commit_attempts == 1

    def test_from_env_blowup_degrades_to_noop(self, monkeypatch):
        class _AgentRuntime:
            @staticmethod
            def from_env():
                raise RuntimeError("workspace 不存在")

        monkeypatch.setitem(sys.modules, "arcbench_agent_runtime",
                            types.SimpleNamespace(AgentRuntime=_AgentRuntime))
        bridge = ArcBenchBridge()
        bridge.run_started("go")  # 不上抛即可
        bridge.handle("module_done", {"module": "x", "status": "SUCCESS"})
        assert bridge._runtime is None


def test_pipeline_emits_interfaces_ready(tmp_path):
    """拆分+契约完成后管线发出 interfaces_ready（桥接层数据源）。"""
    from app.tools.file_manager import FileManager
    from tests.test_feedback_loop import (
        _RUN_KWARGS, ScriptedFeedback, _team_pipeline,
    )
    from tests.test_pipeline import team_scripts

    received = []
    fm = FileManager(projects_root=tmp_path / "p")
    pipeline = _team_pipeline(fm, team_scripts(), ["SKIPPED"] * 3)
    pipeline._on_event = lambda kind, data: received.append((kind, dict(data)))
    feedback = ScriptedFeedback(["运行成功，输出符合预期"])
    result = pipeline.run(feedback_fn=feedback, **_RUN_KWARGS)
    assert result.kind == "team_flow"
    events = [d for k, d in received if k == "interfaces_ready"]
    assert events, "拆分后应发出 interfaces_ready 事件"
    payload = events[0]["interfaces"]
    assert set(payload) == {"user", "data", "auth"}
    assert all(
        {"exports", "public_api", "dependencies"} <= set(c)
        for c in payload.values()
    )
