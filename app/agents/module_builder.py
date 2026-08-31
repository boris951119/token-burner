"""spec → 模块拆分与接口生成（规格文档 3.5 节、12 章、第二阶段收尾任务）。

编排职责（决策 / 校验分离，总则 D 节）：
- 主 LLM 决策：模块拆分（名称/职责/依赖/优先级）、各模块接口三字段；
- 程序确定性校验：模块名白名单、四字段齐备、依赖闭合（12.2）、
  拆分依赖与接口依赖一致性、构建顺序拓扑排序；
- 程序落盘（12.3）：modules/<module>.md、interfaces.json（单一事实源）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.config import Settings
from app.tools.file_manager import FileManager
from app.tools.prompt_templates import (
    INTERFACE_SYSTEM,
    INTERFACE_USER,
    SPLIT_SYSTEM,
    SPLIT_USER,
)
from app.utils.parse import parse_json

_MODULE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,30}$")

# 保留名：与项目系统目录冲突的模块名（真实运行回归：LLM 为「附单元测试」
# 拆出名为 tests 的模块，与 tests/ 收集目录相撞导致导入混乱）
_RESERVED_MODULE_NAMES = frozenset({
    "code", "tests", "test", "modules", "changelog", "sessions",
    "logs", "_shared", "conftest", "spec", "docs",
})

_REQUIRED_FIELDS = ("name", "responsibility", "dependencies", "priority")

_INTERFACE_FIELDS = ("imports", "exports", "public_api", "dependencies")


class SplitError(ValueError):
    """spec 拆分失败（校验不过 / 解析失败需用户介入）。"""


def should_modularize(
    difficulty_score: int, estimated_files: int, settings: Settings
) -> bool:
    """12.2 模块化启用条件（程序确定性阈值判定）。

    难度 ≥ modular_difficulty_threshold（默认 5）或
    预估文件数 ≥ modular_file_count_threshold（默认 6）→ 启用拆分；
    否则单份 spec 直出（难度/文件数由大模型评估，阈值判定归程序）。
    """
    return (
        difficulty_score >= settings.modular_difficulty_threshold
        or estimated_files >= settings.modular_file_count_threshold
    )


@dataclass
class ModulePlan:
    """单个模块的拆分结果（3.5 节）。"""

    name: str
    responsibility: str
    dependencies: list[str]
    priority: int


class ModuleBuilder:
    """spec 拆分编排：拆分 → 校验 → 落盘 → 接口生成 → 合并。"""

    def __init__(self, llm, main_model: str, settings: Settings, file_manager: FileManager):
        self.llm = llm
        self.main_model = main_model
        self.settings = settings
        self.file_manager = file_manager

    # ------------------------------------------------------------------

    def split_spec(self, spec_md: str, project_id: str | None = None) -> list[ModulePlan]:
        """主 LLM 拆分 spec 为模块列表（含重试与确定性校验）。"""
        attempts = 1 + self.settings.max_parse_retries
        last_error = "未知错误"
        for _ in range(attempts):
            response = self.llm.chat(
                self.main_model,
                [
                    {"role": "system", "content": SPLIT_SYSTEM},
                    {"role": "user", "content": SPLIT_USER.format(spec=spec_md)},
                ],
                json_mode=True,
            )
            value, _detail = parse_json(response.content, location="module_split")
            if value is None or not isinstance(value, dict):
                last_error = "拆分输出解析失败"
                continue
            raw_modules = value.get("modules")
            if not isinstance(raw_modules, list) or not raw_modules:
                last_error = "拆分结果至少包含一个模块"
                continue
            plans: list[ModulePlan] = []
            for raw in raw_modules:
                if not isinstance(raw, dict) or any(
                    f not in raw for f in _REQUIRED_FIELDS
                ):
                    last_error = f"模块缺少必要字段 {_REQUIRED_FIELDS}"
                    plans = []
                    break
                name = raw["name"]
                if not isinstance(name, str) or not _MODULE_NAME.match(name):
                    last_error = f"模块名不合法: {name!r}"
                    plans = []
                    break
                if name in _RESERVED_MODULE_NAMES:
                    last_error = (
                        f"模块名 {name!r} 与系统目录冲突（保留名），"
                        "请以功能命名并另拆测试模块或并入各模块职责"
                    )
                    plans = []
                    break
                deps = raw["dependencies"]
                if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
                    last_error = f"模块 {name} 的 dependencies 须为字符串列表"
                    plans = []
                    break
                priority = raw["priority"]
                if not isinstance(priority, int) or isinstance(priority, bool):
                    last_error = f"模块 {name} 的 priority 须为整数"
                    plans = []
                    break
                plans.append(
                    ModulePlan(
                        name=name,
                        responsibility=str(raw["responsibility"]),
                        dependencies=list(deps),
                        priority=priority,
                    )
                )
            if not plans:
                continue
            # 名称唯一 + 依赖闭合（12.2）
            names = {p.name for p in plans}
            if len(names) != len(plans):
                last_error = "模块名重复"
                continue
            for plan in plans:
                for dep in plan.dependencies:
                    if dep not in names:
                        last_error = (
                            f"依赖闭合校验失败：模块 {plan.name} 依赖不存在的模块 {dep}"
                        )
                        plans = []
                        break
                if not plans:
                    break
            if plans:
                if project_id:
                    self._persist_module_plans(project_id, plans)
                return plans
            last_error = last_error or "校验失败"
        raise SplitError(f"spec 拆分失败（重试 {attempts} 次）: {last_error}，请用户介入调整 spec")

    def generate_interfaces(
        self, plans: list[ModulePlan], project_id: str | None = None
    ) -> dict[str, dict]:
        """主 LLM 为每个模块生成三字段接口契约并合并（12.1）。"""
        spec_deps = {p.name: set(p.dependencies) for p in plans}
        interfaces: dict[str, dict] = {}
        for plan in plans:
            response = self.llm.chat(
                self.main_model,
                [
                    {"role": "system", "content": INTERFACE_SYSTEM},
                    {
                        "role": "user",
                        "content": INTERFACE_USER.format(
                            name=plan.name,
                            responsibility=plan.responsibility,
                            dependencies=", ".join(plan.dependencies) or "无",
                        ),
                    },
                ],
                json_mode=True,
            )
            value, _detail = parse_json(
                response.content, location=f"interface_{plan.name}"
            )
            if not isinstance(value, dict) or any(
                f not in value for f in _INTERFACE_FIELDS
            ):
                raise SplitError(
                    f"模块 {plan.name} 接口契约缺少必要字段 {_INTERFACE_FIELDS}"
                )
            # 12.2：接口依赖须与拆分依赖一致（确定性校验）
            iface_deps = set(value["dependencies"])
            if iface_deps != spec_deps[plan.name]:
                raise SplitError(
                    f"模块 {plan.name} 的接口依赖 {sorted(iface_deps)} "
                    f"与拆分依赖 {sorted(spec_deps[plan.name])} 不一致"
                )
            interfaces[plan.name] = {f: value[f] for f in _INTERFACE_FIELDS}

        if project_id:
            handle = self.file_manager.get_project(project_id)
            if handle is not None:
                (handle.root / "interfaces.json").write_text(
                    json.dumps(interfaces, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        return interfaces

    def build_order(self, plans: list[ModulePlan]) -> list[str]:
        """构建顺序：优先级升序 + 依赖拓扑（3.5 依赖顺序执行）。"""
        by_name = {p.name: p for p in plans}
        ordered: list[str] = []
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in visiting:
                raise SplitError(f"模块依赖存在环: {name}")
            visiting.add(name)
            for dep in sorted(by_name[name].dependencies):
                visit(dep)
            visiting.discard(name)
            visited.add(name)
            ordered.append(name)

        for plan in sorted(plans, key=lambda p: (p.priority, p.name)):
            visit(plan.name)
        return ordered

    # ------------------------------------------------------------------

    def single_module_plan(
        self, spec_md: str, project_id: str | None = None
    ) -> ModulePlan:
        """12.2 非模块化路径：单份 spec 直出为单一模块（跳过拆分与接口契约）。

        模块名固定 main（确定性程序决策，无 LLM 调用）；spec 全文作为
        职责传入开发循环，modules/main.md 落盘以维持目录结构一致。
        """
        plan = ModulePlan(
            name="main",
            responsibility=spec_md,
            dependencies=[],
            priority=1,
        )
        if project_id:
            self._persist_module_plans(project_id, [plan])
            # 单模块无接口契约：移除项目脚手架预生成的空 interfaces.json
            handle = self.file_manager.get_project(project_id)
            if handle is not None:
                iface_path = handle.root / "interfaces.json"
                if iface_path.exists():
                    iface_path.unlink()
        return plan

    def _persist_module_plans(self, project_id: str, plans: list[ModulePlan]) -> None:
        handle = self.file_manager.get_project(project_id)
        if handle is None:
            return
        for plan in plans:
            content = (
                f"# 模块 {plan.name}\n\n"
                f"## 职责\n{plan.responsibility}\n\n"
                f"## 依赖\n"
                + ("\n".join(f"- {d}" for d in plan.dependencies) or "无")
                + f"\n\n## 优先级\n{plan.priority}\n"
            )
            (handle.root / "modules" / f"{plan.name}.md").write_text(
                content, encoding="utf-8"
            )
