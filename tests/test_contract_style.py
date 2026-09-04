"""M15-3 契约风格可配置测试（v1.0 V2 批次）。

三态语义（workplan V2）：
- function（缺省）：M15-1 行为不变（顶层可调用导出门禁）；
- class：契约导出 = 顶层公开类（门禁对类统一抽取，指导措辞随风格）；
- auto：首轮实现后按实际代码顶层符号一次性反推回写契约
  （确定性零 LLM）+ 审计落盘 sessions/style_adaptation.jsonl。

场景锚点：v0.5 file_utils 事故——函数式契约 vs 类式实现 5 轮不收敛；
auto 档下同场景应零修复轮直过门禁（风格事实权归首轮代码）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.tools.file_manager import FileManager  # noqa: E402

# v0.5 事故最小复现（与 test_contract_guidance.py 同源场景）
FUNC_CONTRACT = {
    "exports": ["read_file", "write_file"],
    "public_api": [
        "read_file(path) -> str",
        "write_file(path, content) -> bool",
    ],
    "imports": [],
    "dependencies": [],
}

CLASS_IMPL = '''\
class FileManager:
    """v0.5 事故形态：契约 API 全收进类里。"""

    def __init__(self, root):
        self.root = root

    def read_file(self, path):
        return open(self.root / path).read()

    def write_file(self, path, content):
        return True
'''

FUNC_IMPL = """\
def read_file(path) -> str:
    return open(path).read()


def write_file(path, content) -> bool:
    return True
"""


# ---------------------------------------------------------------------------
# Settings 三态
# ---------------------------------------------------------------------------

class TestSettingsTriState:
    def test_default_is_function(self):
        assert Settings().contract_style == "function"

    @pytest.mark.parametrize("style", ["function", "class", "auto"])
    def test_all_three_valid(self, style):
        assert Settings(contract_style=style).contract_style == style

    def test_invalid_rejected(self):
        with pytest.raises(ValueError, match="contract_style"):
            Settings(contract_style="module")


# ---------------------------------------------------------------------------
# 确定性反推（infer_style / rewrite_contract）
# ---------------------------------------------------------------------------

class TestInferStyle:
    def test_class_impl_infers_class(self):
        from app.utils.contract_style import infer_style

        assert infer_style(CLASS_IMPL) == "class"

    def test_function_impl_infers_function(self):
        from app.utils.contract_style import infer_style

        assert infer_style(FUNC_IMPL) == "function"

    def test_private_class_still_function(self):
        from app.utils.contract_style import infer_style

        code = "class _Internal:\n    pass\n\n\ndef api():\n    return 1\n"
        assert infer_style(code) == "function"

    def test_syntax_error_defaults_function(self):
        from app.utils.contract_style import infer_style

        assert infer_style("def broken(:\n") == "function"


class TestRewriteContract:
    def test_class_impl_rewrites_to_class_symbols(self):
        from app.utils.contract_style import rewrite_contract

        rewritten = rewrite_contract(CLASS_IMPL, FUNC_CONTRACT)
        assert rewritten is not None
        assert rewritten["exports"] == ["FileManager"]
        assert rewritten["public_api"] == ["FileManager(root)"]
        # imports/dependencies 不动（拆分拓扑仍由程序校验）
        assert rewritten["imports"] == []
        assert rewritten["dependencies"] == []

    def test_aligned_contract_returns_none(self):
        from app.utils.contract_style import rewrite_contract

        assert rewrite_contract(FUNC_IMPL, FUNC_CONTRACT) is None

    def test_no_public_defs_returns_none(self):
        from app.utils.contract_style import rewrite_contract

        assert rewrite_contract("def _private():\n    pass\n", FUNC_CONTRACT) is None

    def test_original_contract_untouched(self):
        """回写返回副本，原契约 dict 不被就地修改（就地更新归引擎负责）。"""
        from app.utils.contract_style import rewrite_contract

        rewrite_contract(CLASS_IMPL, FUNC_CONTRACT)
        assert FUNC_CONTRACT["exports"] == ["read_file", "write_file"]


# ---------------------------------------------------------------------------
# 门禁指导随风格（check_implementation style 参数）
# ---------------------------------------------------------------------------

class TestStyleAwareGuidance:
    def test_class_style_missing_guidance_says_class(self):
        from app.utils.interface_check import check_implementation

        # class 风格契约（类导出）vs 函数实现 → 指导补类而非 def
        contract = {
            "exports": ["FileManager"],
            "public_api": ["FileManager(root)"],
            "imports": [], "dependencies": [],
        }
        issues = check_implementation(
            "file_utils", FUNC_IMPL, contract, style="class")
        miss = next(i for i in issues if i.kind == "missing")
        assert "class FileManager" in miss.guidance
        assert "公开方法" in miss.guidance

    def test_auto_style_guidance_is_neutral(self):
        from app.utils.interface_check import check_implementation

        issues = check_implementation(
            "file_utils", CLASS_IMPL, FUNC_CONTRACT, style="auto")
        miss = next(i for i in issues if i.kind == "missing")
        assert "函数或类" in miss.guidance

    def test_class_contract_passes_gate_against_class_impl(self):
        """class 风格契约 + 类实现 → 零 issue（门禁对类统一抽取天然支持）。"""
        from app.utils.interface_check import check_implementation

        contract = {
            "exports": ["FileManager"],
            "public_api": ["FileManager(root)"],
            "imports": [], "dependencies": [],
        }
        assert check_implementation(
            "file_utils", CLASS_IMPL, contract, style="class") == []


# ---------------------------------------------------------------------------
# DevLoop 集成：auto 回写 + 审计落盘 + 一次性
# ---------------------------------------------------------------------------

class _StubLLM:
    """按 system 提示词分支的桩：写码返回类式实现，写测试返回空测试。

    逻辑审查（M14-7 缺省开）返回 pass，避免干扰风格测试焦点。
    """

    def __init__(self, code: str):
        self.code = code

    def chat(self, model, messages, json_mode=False):
        system = messages[0]["content"]

        class R:
            pass

        if "代码审查员" in system:
            R.content = '{"verdict": "pass", "issues": [], "warnings": []}'
        elif "开发副 LLM" in system:
            R.content = self.code
        elif "测试副 LLM" in system:
            R.content = "def test_placeholder():\n    assert True\n"
        else:
            raise AssertionError(f"未识别的调用环节: {system[:40]!r}")
        return R()


def _engine(tmp_path, llm, settings=None):
    from app.agents.dev_loop import DevLoopEngine
    from app.execution.safe_executor import SafeExecutor

    fm = FileManager(projects_root=tmp_path / "projects")
    return DevLoopEngine(
        llm=llm, executor=SafeExecutor(),
        settings=settings or Settings(),
        file_manager=fm, dev_model="d", test_model="t",
    ), fm


class TestAutoAdaptIntegration:
    def _project(self, fm):
        handle = fm.create_project("风格自适应测试需求")
        # interfaces.json 预置函数式契约（模拟拆分阶段产物）
        (handle.root / "interfaces.json").write_text(
            json.dumps({"file_utils": FUNC_CONTRACT}, ensure_ascii=False),
            encoding="utf-8",
        )
        return handle

    def test_v05_incident_replay_converges_without_fix_rounds(self, tmp_path):
        """v0.5 事故重放：auto 档下函数契约 + 类实现 → 零修复轮直过门禁。"""
        engine, fm = _engine(
            tmp_path, _StubLLM(CLASS_IMPL),
            settings=Settings(contract_style="auto"),
        )
        handle = self._project(fm)
        contract = json.loads(
            (handle.root / "interfaces.json").read_text(encoding="utf-8")
        )["file_utils"]

        result = engine.run_module(
            "file_utils", project_id=handle.project_id,
            responsibility="文件工具", contract=contract,
        )
        # safe 模式：门禁全过后 SKIPPED → 等待用户反馈（而非冻结）
        assert "AWAITING_FEEDBACK" in result.status.value
        assert result.fix_attempts == 0, "auto 档不应消耗修复轮"

    def test_contract_rewritten_and_audited(self, tmp_path):
        engine, fm = _engine(
            tmp_path, _StubLLM(CLASS_IMPL),
            settings=Settings(contract_style="auto"),
        )
        handle = self._project(fm)
        contract = json.loads(
            (handle.root / "interfaces.json").read_text(encoding="utf-8")
        )["file_utils"]

        engine.run_module(
            "file_utils", project_id=handle.project_id,
            responsibility="文件工具", contract=contract,
        )
        # 契约已回写为类符号（就地更新，pipeline interfaces 同引用同步）
        assert contract["exports"] == ["FileManager"]
        assert contract["public_api"] == ["FileManager(root)"]
        # interfaces.json（单一事实源）同步
        on_disk = json.loads(
            (handle.root / "interfaces.json").read_text(encoding="utf-8")
        )
        assert on_disk["file_utils"]["exports"] == ["FileManager"]
        # 审计落盘：sessions/style_adaptation.jsonl
        audit = handle.root / "sessions" / "style_adaptation.jsonl"
        assert audit.exists()
        records = [json.loads(l) for l in
                   audit.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(records) == 1
        rec = records[0]
        assert rec["module"] == "file_utils"
        assert rec["inferred_style"] == "class"
        assert rec["original"]["exports"] == ["read_file", "write_file"]
        assert rec["rewritten"]["exports"] == ["FileManager"]

    def test_function_style_lock_keeps_v05_behavior(self, tmp_path):
        """function 锁定（缺省）：类实现仍被门禁拦截（自适应完全关闭）。"""
        engine, fm = _engine(
            tmp_path, _StubLLM(CLASS_IMPL),
            settings=Settings(contract_style="function", max_fix_rounds=1),
        )
        handle = self._project(fm)
        contract = json.loads(
            (handle.root / "interfaces.json").read_text(encoding="utf-8")
        )["file_utils"]

        result = engine.run_module(
            "file_utils", project_id=handle.project_id,
            responsibility="文件工具", contract=contract,
        )
        assert result.status.value == "FROZEN"
        assert "接口门禁失败" in result.message
        # 契约未被回写，无审计记录
        assert contract["exports"] == ["read_file", "write_file"]
        assert not (handle.root / "sessions" / "style_adaptation.jsonl").exists()

    def test_adapt_once_per_module_in_engine(self, tmp_path):
        """引擎内一次性：_style_adapted 命中后不再回写。"""
        engine, fm = _engine(
            tmp_path, _StubLLM(CLASS_IMPL),
            settings=Settings(contract_style="auto", max_fix_rounds=1),
        )
        handle = self._project(fm)
        contract = json.loads(
            (handle.root / "interfaces.json").read_text(encoding="utf-8")
        )["file_utils"]
        engine._style_adapted.add("file_utils")  # 模拟本引擎已回写过

        engine.run_module(
            "file_utils", project_id=handle.project_id,
            responsibility="文件工具", contract=contract,
        )
        assert contract["exports"] == ["read_file", "write_file"]
        assert not (handle.root / "sessions" / "style_adaptation.jsonl").exists()

    def test_resume_replay_idempotent_no_duplicate_audit(self, tmp_path):
        """resume 重放：新引擎 + 陈旧快照契约 → 重新对齐但审计不重复记。"""
        _, fm = _engine(
            tmp_path, _StubLLM(CLASS_IMPL),
            settings=Settings(contract_style="auto"),
        )
        handle = self._project(fm)
        contract = json.loads(
            (handle.root / "interfaces.json").read_text(encoding="utf-8")
        )["file_utils"]

        # 第一次运行（首轮回写 + 审计）
        engine1, _ = _engine(
            tmp_path, _StubLLM(CLASS_IMPL),
            settings=Settings(contract_style="auto"),
        )
        engine1.run_module(
            "file_utils", project_id=handle.project_id,
            responsibility="文件工具", contract=contract,
        )
        # resume：新引擎拿到 pipeline_state 的陈旧契约（恢复为原始函数式）
        stale = json.loads(json.dumps(FUNC_CONTRACT))
        engine2, _ = _engine(
            tmp_path, _StubLLM(CLASS_IMPL),
            settings=Settings(contract_style="auto"),
        )
        engine2.run_module(
            "file_utils", project_id=handle.project_id,
            responsibility="文件工具", contract=stale,
        )
        assert stale["exports"] == ["FileManager"]  # 重新对齐（幂等重放）
        audit = handle.root / "sessions" / "style_adaptation.jsonl"
        records = [json.loads(l) for l in
                   audit.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(records) == 1, "同模块同回写不应重复审计"


# ---------------------------------------------------------------------------
# ModuleBuilder 集成：接口生成提示词随风格
# ---------------------------------------------------------------------------

class TestBuilderStylePrompt:
    def _builder(self, tmp_path, settings):
        from app.agents.module_builder import ModuleBuilder

        return ModuleBuilder(
            llm=None, main_model="m", settings=settings,
            file_manager=FileManager(projects_root=tmp_path / "projects"),
        )

    def _plans(self):
        from app.agents.module_builder import ModulePlan

        return [ModulePlan(name="file_utils", responsibility="文件工具",
                           dependencies=[], priority=1)]

    def test_interface_system_carries_style_segment(self, tmp_path):
        """接口生成 system 提示词 = 基础模板 + 风格约束段。"""
        captured = {}

        class LLMLike:
            def chat(self, model, messages, json_mode=False):
                captured["system"] = messages[0]["content"]

                class R:
                    pass

                R.content = json.dumps({
                    "imports": [], "exports": ["x"],
                    "public_api": ["x()"], "dependencies": [],
                })
                return R()

        builder = self._builder(
            tmp_path, Settings(contract_style="class"))
        builder.llm = LLMLike()
        builder.generate_interfaces(self._plans(), project_id=None)
        assert "顶层的公开类" in captured["system"]

    def test_interface_prompt_base_template_present(self, tmp_path):
        """基础模板（JSON 结构约束）仍在，风格段是追加不是替换。"""
        captured = {}

        class LLMLike:
            def chat(self, model, messages, json_mode=False):
                captured["system"] = messages[0]["content"]

                class R:
                    pass

                R.content = json.dumps({
                    "imports": [], "exports": ["x"],
                    "public_api": ["x()"], "dependencies": [],
                })
                return R()

        builder = self._builder(
            tmp_path, Settings())  # function 缺省
        builder.llm = LLMLike()
        builder.generate_interfaces(self._plans(), project_id=None)
        assert "架构师" in captured["system"]
        assert "不要封装成类" in captured["system"]
