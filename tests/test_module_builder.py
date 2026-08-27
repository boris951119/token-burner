"""ModuleBuilder 单元测试（TDD 先行，LLM 全部 mock）。

依据：规格文档 v0.3.1
- 3.5 节：主 LLM 按 spec 输出模块拆分（模块名、职责、依赖、优先级）；
- 12.1 节：interfaces.json 每模块三字段——imports/exports（数据与函数）、
  public_api（对外接口）、dependencies（跨模块依赖）；
- 12.2 节：拆分后须通过依赖闭合校验（每个依赖都有对应模块承接）；
- 12.3 节：模块化落盘——modules/<module>.md、code/<module>/、tests/<module>/；
- 15.3：拆分 JSON 解析失败 → 重试（≤max_parse_retries）→ 仍失败交用户介入。
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.agents.module_builder import ModuleBuilder, ModulePlan, SplitError
from app.tools.file_manager import FileManager
from app.utils.model_client import LLMResponse


@pytest.fixture
def fm(tmp_path) -> FileManager:
    return FileManager(projects_root=tmp_path / "projects")


def split_json(modules: list[dict] | None = None) -> str:
    modules = modules or [
        {"name": "user", "responsibility": "用户管理", "dependencies": [], "priority": 1},
        {"name": "data", "responsibility": "数据存储", "dependencies": [], "priority": 1},
        {
            "name": "auth",
            "responsibility": "认证授权",
            "dependencies": ["user", "data"],
            "priority": 2,
        },
    ]
    return json.dumps({"modules": modules}, ensure_ascii=False)


class ScriptedLLM:
    def __init__(self, scripts: list[str]):
        self.scripts = list(scripts)
        self.calls: list[dict] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append({"model": model, "json_mode": json_mode})
        content = self.scripts.pop(0) if self.scripts else split_json()
        return LLMResponse(model=model, content=content, input_tokens=10, output_tokens=5)


def make_builder(llm, fm) -> ModuleBuilder:
    return ModuleBuilder(
        llm=llm,
        main_model="gpt-4o",
        settings=Settings(),
        file_manager=fm,
    )


class TestSplitFlow:
    def test_split_returns_module_plans(self, fm):
        builder = make_builder(ScriptedLLM([split_json()]), fm)
        plans = builder.split_spec("# spec\n用户管理需求")
        assert len(plans) == 3
        assert all(isinstance(p, ModulePlan) for p in plans)
        assert plans[0].name == "user"
        assert plans[2].dependencies == ["user", "data"]

    def test_json_mode_requested(self, fm):
        llm = ScriptedLLM([split_json()])
        make_builder(llm, fm).split_spec("spec")
        assert llm.calls[0]["json_mode"] is True

    def test_modules_persisted(self, fm):
        # 12.3：modules/<module>.md 落盘
        project_id = fm.create_project("demo").project_id
        llm = ScriptedLLM([split_json()])
        builder = make_builder(llm, fm)
        builder.split_spec("spec", project_id=project_id)
        handle = fm.get_project(project_id)
        assert handle is not None
        assert (handle.root / "modules" / "user.md").is_file()
        assert (handle.root / "modules" / "auth.md").is_file()

    def test_module_markdown_contains_spec_fields(self, fm):
        project_id = fm.create_project("demo").project_id
        llm = ScriptedLLM([split_json()])
        make_builder(llm, fm).split_spec("spec", project_id=project_id)
        handle = fm.get_project(project_id)
        assert handle is not None
        content = (handle.root / "modules" / "auth.md").read_text(encoding="utf-8")
        assert "认证授权" in content
        assert "user" in content  # 依赖列出


class TestSplitValidation:
    def test_dependency_closure_checked(self, fm):
        # 12.2：依赖闭合——依赖了不存在的模块 → 拆分无效
        broken = json.dumps(
            {
                "modules": [
                    {"name": "auth", "responsibility": "认证", "dependencies": ["ghost"], "priority": 1}
                ]
            },
            ensure_ascii=False,
        )
        builder = make_builder(ScriptedLLM([broken, broken, broken, broken]), fm)
        with pytest.raises(SplitError, match="闭合"):
            builder.split_spec("spec")

    def test_invalid_module_name_rejected(self, fm):
        # 确定性校验：模块名不合法（白名单正则）
        bad = json.dumps(
            {
                "modules": [
                    {"name": "bad name!", "responsibility": "x", "dependencies": [], "priority": 1}
                ]
            },
            ensure_ascii=False,
        )
        builder = make_builder(ScriptedLLM([bad, bad, bad, bad]), fm)
        with pytest.raises(SplitError):
            builder.split_spec("spec")

    def test_empty_split_rejected(self, fm):
        empty = json.dumps({"modules": []}, ensure_ascii=False)
        builder = make_builder(ScriptedLLM([empty, empty, empty, empty]), fm)
        with pytest.raises(SplitError, match="至少"):
            builder.split_spec("spec")

    def test_missing_required_field_rejected(self, fm):
        # 三字段齐备：name/responsibility/dependencies/priority
        missing = json.dumps(
            {"modules": [{"name": "a", "responsibility": "x"}]}, ensure_ascii=False
        )
        builder = make_builder(ScriptedLLM([missing, missing, missing, missing]), fm)
        with pytest.raises(SplitError):
            builder.split_spec("spec")


class TestSplitRetry:
    def test_unparseable_retries_then_raises(self, fm):
        # 15.3：重试 max_parse_retries 次后仍失败 → 交用户介入（抛错而非静默）
        builder = make_builder(ScriptedLLM(["坏", "坏", "坏", "坏"]), fm)
        with pytest.raises(SplitError, match="解析"):
            builder.split_spec("spec")

    def test_retry_succeeds_on_second_attempt(self, fm):
        llm = ScriptedLLM(["前置说明" + split_json()])
        builder = make_builder(llm, fm)
        plans = builder.split_spec("spec")
        assert len(plans) == 3


def iface_json(deps: list[str]) -> str:
    return json.dumps(
        {
            "imports": deps,
            "exports": [f"{d}_api" for d in deps] or ["core_api"],
            "public_api": [f"{d}_fn" for d in deps] or ["core_fn"],
            "dependencies": deps,
        },
        ensure_ascii=False,
    )


class DepAwareLLM:
    """按当前请求模块的拆分依赖返回一致接口的桩。"""

    def __init__(self, split: str):
        self.split = split
        self.calls: list[dict] = []

    def chat(self, model, messages, json_mode=False):
        self.calls.append({"model": model, "json_mode": json_mode})
        user_content = messages[-1]["content"]
        if "spec.md 内容" in user_content:
            return LLMResponse(model=model, content=self.split, input_tokens=10, output_tokens=5)
        # 接口请求：解析「拆分阶段声明的依赖：...」行
        import re
        m = re.search(r"拆分阶段声明的依赖：(.+)", user_content)
        deps: list[str] = []
        if m and m.group(1).strip() != "无":
            deps = [d.strip() for d in m.group(1).split(",") if d.strip()]
        return LLMResponse(
            model=model, content=iface_json(deps), input_tokens=10, output_tokens=5
        )


class TestInterfaces:
    def test_interface_generated_per_module(self, fm):
        # 12.1：主 LLM 为每个模块生成三字段接口契约
        project_id = fm.create_project("demo").project_id
        llm = DepAwareLLM(split_json())
        builder = ModuleBuilder(
            llm=llm, main_model="gpt-4o", settings=Settings(), file_manager=fm
        )
        plans = builder.split_spec("spec", project_id=project_id)
        interfaces = builder.generate_interfaces(plans, project_id=project_id)
        assert set(interfaces.keys()) == {"user", "data", "auth"}
        assert interfaces["auth"]["dependencies"] == ["user", "data"]
        assert interfaces["user"]["public_api"] == ["core_fn"]

    def test_interfaces_merged_into_single_file(self, fm):
        # 12.1：各模块接口合并写入 interfaces.json（单一事实源）
        project_id = fm.create_project("demo").project_id
        llm = DepAwareLLM(split_json())
        builder = ModuleBuilder(
            llm=llm, main_model="gpt-4o", settings=Settings(), file_manager=fm
        )
        plans = builder.split_spec("spec", project_id=project_id)
        builder.generate_interfaces(plans, project_id=project_id)
        handle = fm.get_project(project_id)
        assert handle is not None
        merged = json.loads(
            (handle.root / "interfaces.json").read_text(encoding="utf-8")
        )
        assert set(merged.keys()) == {"user", "data", "auth"}
        assert set(merged["auth"].keys()) == {
            "imports",
            "exports",
            "public_api",
            "dependencies",
        }

    def test_dependency_consistency_between_split_and_interface(self, fm):
        # 12.2：接口依赖与拆分依赖须一致（确定性校验）
        project_id = fm.create_project("demo").project_id
        iface = json.dumps(
            {
                "imports": [],
                "exports": [],
                "public_api": [],
                "dependencies": ["ghost_module"],  # 拆分中不存在
            },
            ensure_ascii=False,
        )
        llm = ScriptedLLM([split_json()] + [iface] * 3)
        builder = make_builder(llm, fm)
        plans = builder.split_spec("spec", project_id=project_id)
        with pytest.raises(SplitError, match="一致"):
            builder.generate_interfaces(plans, project_id=project_id)

    def test_build_order_respects_dependencies(self, fm):
        # 3.5：优先级 + 依赖拓扑 → 构建顺序（user/data 先于 auth）
        llm = ScriptedLLM([split_json()])
        builder = make_builder(llm, fm)
        plans = builder.split_spec("spec")
        order = builder.build_order(plans)
        assert order.index("user") < order.index("auth")
        assert order.index("data") < order.index("auth")
        assert len(order) == 3
