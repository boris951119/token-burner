"""3.6.3 分级修订（方案 A+B）回归：fs 删除族降级可修复 + 提示词前置。

依据：bench_v1 round-5 取证（T2 glm-4.7 两模块死于 os.remove 直接冻结）
+ 用户批准的规格修订：
- 方案 B：fs 删除族（os.remove/unlink/rmdir/removedirs/renames、
  shutil.rmtree/move · 模块代码侧）→ 进修复循环换安全设计；
  hard 类（动态执行/系统命令/网络/子进程）维持执行器 BLOCKED 直接冻结。
- 方案 A：危险约束提示词注入 write_code/fix_code（与扫描黑名单同源）。
"""

from __future__ import annotations

from app.config import Settings
from app.agents.dev_loop import DevLoopEngine, ModuleStatus
from app.execution.local_executor import (
    LocalExecutor,
    danger_prompt_constraint,
    scan_dangerous,
    scan_dangerous_graded,
)
from app.tools.file_manager import FileManager
from app.utils.model_client import LLMResponse

FS_CODE = "import os\n\ndef clean(path):\n    os.remove(path)\n"
RMTREE_CODE = "import shutil\n\ndef nuke(path):\n    shutil.rmtree(path)\n"
EVAL_CODE = "def f(x):\n    return eval(x)\n"
SYSTEM_CODE = "import os\n\ndef sh(cmd):\n    return os.system(cmd)\n"


class TestGradedScan:
    def test_fs_deletion_code_side_is_soft(self):
        hard, soft = scan_dangerous_graded(FS_CODE)
        assert hard == []
        assert len(soft) == 1 and "os.remove" in soft[0]

    def test_rmtree_code_side_is_soft(self):
        hard, soft = scan_dangerous_graded(RMTREE_CODE)
        assert hard == [] and any("rmtree" in s for s in soft)

    def test_eval_and_system_are_hard(self):
        hard, soft = scan_dangerous_graded(EVAL_CODE)
        assert hard and "eval" in hard[0] and soft == []
        hard, soft = scan_dangerous_graded(SYSTEM_CODE)
        assert hard and "os.system" in hard[0] and soft == []

    def test_tests_side_fs_still_exempt(self):
        tests = "import shutil\n\ndef test_cleanup(tmp_path):\n    shutil.rmtree(tmp_path)\n"
        hard, soft = scan_dangerous_graded("def f():\n    return 1\n", tests=tests)
        assert hard == [] and soft == []

    def test_merged_scan_dangerous_backward_compatible(self):
        issues = scan_dangerous(FS_CODE)
        assert issues and "os.remove" in issues[0]

    def test_hard_plus_soft_both_reported(self):
        code = "import os\n\ndef f(p):\n    eval(p)\n    os.remove(p)\n"
        hard, soft = scan_dangerous_graded(code)
        assert any("eval" in h for h in hard)
        assert any("os.remove" in s for s in soft)


class TestExecutorBlocksHardOnly:
    def test_soft_fs_not_blocked_at_executor(self, tmp_path):
        # 仅 soft（os.remove）不再触发 BLOCKED；hard（eval）在场仍拦截，
        # 且拦截信息只含 hard 项（soft 由门禁层处置，不重复报）
        ex = LocalExecutor(project_code_dir=tmp_path)
        code = "import os\n\ndef f(p):\n    eval(p)\n    os.remove(p)\n"
        result = ex.run(code=code, tests="", timeout=10, module="m")
        assert result.status.value == "BLOCKED"
        assert "eval" in result.message
        assert "os.remove" not in result.message


class TestDevLoopSoftDangerFixLoop:
    def _engine(self, llm, fm, executor) -> DevLoopEngine:
        return DevLoopEngine(
            llm=llm,
            dev_model="dev-model",
            test_model="test-model",
            executor=executor,
            settings=Settings(logic_review_enabled=False),
            file_manager=fm,
        )

    def test_fs_deletion_enters_fix_loop_not_freeze(self, tmp_path):
        class FakeExecutor:
            def run(self, code, tests, timeout, expected_output="", module=""):
                from app.execution.executor import ExecutionResult, ExecutionStatus
                return ExecutionResult(status=ExecutionStatus.SUCCESS, message="")

        class ScriptedLLM:
            def __init__(self, scripts):
                self.scripts = list(scripts)
                self.calls = []

            def chat(self, model, messages, json_mode=False):
                self.calls.append({"model": model, "messages": messages})
                return LLMResponse(
                    model=model,
                    content=self.scripts.pop(0), input_tokens=1, output_tokens=1,
                )

        clean_code = (
            "import tempfile\n"
            "def clean():\n"
            "    with tempfile.TemporaryDirectory() as d:\n"
            "        return d\n"
        )
        tests = "from user import clean\n\ndef test_ok():\n    assert clean()\n"
        llm = ScriptedLLM([FS_CODE, tests, clean_code])
        fm = FileManager(projects_root=tmp_path / "p")
        engine = self._engine(llm, fm, FakeExecutor())
        pid = fm.create_project("demo").project_id
        result = engine.run_module("user", project_id=pid)
        assert result.status is ModuleStatus.SUCCESS
        assert result.fix_attempts == 1  # 软级危险 → 一轮修复收敛
        # 修复调用携带修复指导
        fix_user = llm.calls[2]["messages"][-1]["content"]
        assert "危险操作门禁" in fix_user or "tempfile" in fix_user


class TestDangerPromptInjection:
    def test_prompt_lists_forbidden_and_replacements(self):
        text = danger_prompt_constraint()
        for token in ("eval", "subprocess", "os.remove", "tempfile"):
            assert token in text

    def test_write_code_and_fix_code_system_carry_danger_prompt(self, tmp_path):
        class CapturingLLM:
            def __init__(self):
                self.calls = []

            def chat(self, model, messages, json_mode=False):
                self.calls.append(messages)
                return LLMResponse(
                    model=model, content="x = 1", input_tokens=1, output_tokens=1,
                )

        fm = FileManager(projects_root=tmp_path / "p")
        llm = CapturingLLM()
        engine = DevLoopEngine(
            llm=llm, dev_model="d", test_model="t",
            executor=None,
            settings=Settings(logic_review_enabled=False),
            file_manager=fm,
        )
        engine._write_code("user", "职责")
        assert "安全约束" in llm.calls[0][0]["content"]
