"""M15-4 修复轮上下文增强测试（v1.0 V2 批次）。

规格：修复轮提示词携带接口地图全文 + 已定稿模块对本模块 API 的
调用示例。v0.5 教训：修复 LLM 不知改动波及面（其他模块契约了什么、
哪些符号正被消费），改 A 破 B 往返循环。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.tools.file_manager import FileManager  # noqa: E402

INTERFACES = {
    "producer": {
        "exports": ["read_file", "write_file"],
        "public_api": [
            "read_file(path) -> str",
            "write_file(path, content) -> bool",
        ],
        "imports": [],
        "dependencies": [],
    },
    "consumer": {
        "exports": ["run"],
        "public_api": ["run(path) -> str"],
        "imports": ["read_file"],
        "dependencies": ["producer"],
    },
}

CONSUMER_CODE = '''\
"""消费方模块。"""
from producer import read_file


def run(path):
    data = read_file(path)
    return data.upper()
'''

BARE_IMPORT_CODE = '''\
import producer


def run(path):
    return producer.read_file(path)
'''

FUNC_CONTRACT = INTERFACES["producer"]
CLASS_IMPL = '''\
class FileManager:
    def __init__(self, root):
        self.root = root

    def read_file(self, path):
        return open(self.root / path).read()

    def write_file(self, path, content):
        return True
'''


def _engine(tmp_path):
    from app.agents.dev_loop import DevLoopEngine
    from app.execution.safe_executor import SafeExecutor

    fm = FileManager(projects_root=tmp_path / "projects")
    return DevLoopEngine(
        llm=None, executor=SafeExecutor(), settings=Settings(),
        file_manager=fm, dev_model="d", test_model="t",
    ), fm


def _project(fm, interfaces=None, files=None):
    handle = fm.create_project("修复上下文增强测试需求")
    if interfaces is not None:
        (handle.root / "interfaces.json").write_text(
            json.dumps(interfaces, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    for name, content in (files or {}).items():
        target = handle.root / "code" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return handle


class TestFixContext:
    def test_interface_map_included(self, tmp_path):
        """接口地图全文注入（全部模块契约）。"""
        engine, fm = _engine(tmp_path)
        handle = _project(fm, interfaces=INTERFACES)
        engine._active_project_id = handle.project_id

        ctx = engine._fix_context("producer")
        assert "接口地图" in ctx
        assert "### producer" in ctx
        assert "### consumer" in ctx
        assert "read_file(path) -> str" in ctx
        assert "dependencies: producer" in ctx

    def test_usage_examples_from_import(self, tmp_path):
        """from import 形式：import 行 + 符号使用行都进上下文。"""
        engine, fm = _engine(tmp_path)
        handle = _project(
            fm, interfaces=INTERFACES,
            files={"consumer.py": CONSUMER_CODE},
        )
        engine._active_project_id = handle.project_id

        ctx = engine._fix_context("producer")
        assert "调用示例" in ctx
        assert "from producer import read_file" in ctx
        assert "data = read_file(path)" in ctx

    def test_usage_examples_bare_import(self, tmp_path):
        """裸 import 形式（import producer）：模块名前缀用法被捕获。"""
        engine, fm = _engine(tmp_path)
        handle = _project(
            fm, interfaces=INTERFACES,
            files={"consumer.py": BARE_IMPORT_CODE},
        )
        engine._active_project_id = handle.project_id

        ctx = engine._fix_context("producer")
        assert "import producer" in ctx
        assert "producer.read_file(path)" in ctx

    def test_no_project_returns_empty(self, tmp_path):
        engine, _ = _engine(tmp_path)
        engine._active_project_id = None
        assert engine._fix_context("producer") == ""

    def test_no_dependents_no_usage_section(self, tmp_path):
        """无依赖方文件：只有接口地图，无调用示例段。"""
        engine, fm = _engine(tmp_path)
        handle = _project(fm, interfaces=INTERFACES)
        engine._active_project_id = handle.project_id

        ctx = engine._fix_context("producer")
        assert "接口地图" in ctx
        assert "调用示例" not in ctx

    def test_unrelated_import_ignored(self, tmp_path):
        """引用其他模块的文件不算本模块依赖方。"""
        engine, fm = _engine(tmp_path)
        other_code = "from elsewhere import thing\n\n\ndef run():\n    return thing()\n"
        handle = _project(
            fm, interfaces=INTERFACES, files={"consumer.py": other_code},
        )
        engine._active_project_id = handle.project_id

        assert "调用示例" not in engine._fix_context("producer")

    def test_usage_lines_truncated(self, tmp_path):
        """超限引用行截断（防提示词膨胀）。"""
        from app.agents.dev_loop import _USAGE_LINE_LIMIT

        engine, fm = _engine(tmp_path)
        lines = ["from producer import read_file", ""]
        for i in range(_USAGE_LINE_LIMIT + 10):
            lines.append(f"x{i} = read_file('f{i}')")
        handle = _project(
            fm, interfaces=INTERFACES, files={"consumer.py": "\n".join(lines)},
        )
        engine._active_project_id = handle.project_id

        ctx = engine._fix_context("producer")
        assert "已截断" in ctx

    def test_self_file_excluded(self, tmp_path):
        """本模块自身文件不算依赖方（resume/回归场景自查无意义）。"""
        engine, fm = _engine(tmp_path)
        handle = _project(
            fm, interfaces=INTERFACES, files={"producer.py": CONSUMER_CODE},
        )
        engine._active_project_id = handle.project_id

        assert "调用示例" not in engine._fix_context("producer")


class TestFixPromptIntegration:
    def test_fix_prompt_carries_context(self, tmp_path):
        """修复轮 user 提示词携带接口地图与调用示例（门禁失败重放）。"""
        from app.execution.safe_executor import SafeExecutor

        captured = {}

        class StubLLM:
            def chat(self, model, messages, json_mode=False):
                system = messages[0]["content"]

                class R:
                    pass

                if "开发副 LLM" in system:
                    captured.setdefault("user", []).append(messages[1]["content"])
                    R.content = CLASS_IMPL  # 持续类式 → 门禁反复失败进修复轮
                elif "测试副 LLM" in system:
                    R.content = "def test_x():\n    assert True\n"
                else:
                    raise AssertionError(f"未识别环节: {system[:40]!r}")
                return R()

        fm = FileManager(projects_root=tmp_path / "projects")
        from app.agents.dev_loop import DevLoopEngine

        engine = DevLoopEngine(
            llm=StubLLM(), executor=SafeExecutor(),
            settings=Settings(max_fix_rounds=1),
            file_manager=fm, dev_model="d", test_model="t",
        )
        handle = _project(
            fm, interfaces=INTERFACES,
            files={"consumer.py": CONSUMER_CODE},
        )
        contract = json.loads(json.dumps(FUNC_CONTRACT))
        engine.run_module(
            "producer", project_id=handle.project_id,
            responsibility="生产者", contract=contract,
        )
        # 首轮写码 + 1 轮修复，修复轮 user 提示词须含两段上下文
        assert len(captured["user"]) >= 2
        fix_prompt = captured["user"][1]
        assert "接口地图" in fix_prompt
        assert "from producer import read_file" in fix_prompt
