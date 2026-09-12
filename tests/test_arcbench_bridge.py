"""ArcBenchBridge：SDK 未安装时的 no-op 保证 + 事件映射（注入桩验证）。"""

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

    def store_requirement_tree(self, tree) -> None:
        self.calls.append(("store_requirement_tree", tree))

    def upsert_interface(self, **kwargs) -> None:
        self.calls.append(("upsert_interface", kwargs))

    def upsert_test(self, **kwargs) -> None:
        self.calls.append(("upsert_test", kwargs))

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

    def commit(self, message: str) -> None:
        self.commits.append(message)


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
