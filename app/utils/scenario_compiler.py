# -*- coding: utf-8 -*-
"""场景编译器：requirements.yaml → 结构化场景条目（v8 地基）。

产出的场景条目是三件事的共同数据源：
1. 测试工程模块生成 Playwright 严格断言（spec 期）
2. traceability 的场景/测试登记（激活 feature_implementation_rate）
3. 模块提示词的场景切片注入（协同契约层）

纯机械解析，零 LLM。requirements.yaml 结构（官方两题实测）：
ROOT(FOLDER) → REQ-N(FOLDER) → REQ-N.M(ATOMIC, scenarios=[{name, steps:
[{keyword: GIVEN|WHEN|THEN, content}]}], dependencies=[...])
注意：并非所有题的 yaml 都带种子声明（Keep 带、BookStack 不带）——
种子契约是可选段，缺省时测试需自建数据。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Step:
    keyword: str   # GIVEN | WHEN | THEN
    content: str


@dataclass
class Scenario:
    req_id: str
    req_name: str
    module: str            # 所属一级模块（REQ-N 的 name）
    module_id: str
    scenario: str          # 场景名
    steps: list[Step] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["steps"] = [asdict(s) for s in self.steps]
        return d


def compile_scenarios(yaml_path: Path) -> list[Scenario]:
    """解析 requirements.yaml → 扁平场景条目清单（保持文档顺序）。"""
    import yaml

    data = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    out: list[Scenario] = []

    def walk(node: dict, module_id: str, module: str) -> None:
        for child in node.get("children") or []:
            cid = str(child.get("id") or "")
            cname = str(child.get("name") or "")
            if child.get("type") == "FOLDER":
                walk(child, cid or module_id, cname or module)
                continue
            for sc in child.get("scenarios") or []:
                steps = [
                    Step(str(s.get("keyword") or "").upper(),
                         str(s.get("content") or ""))
                    for s in (sc.get("steps") or [])
                ]
                out.append(Scenario(
                    req_id=cid, req_name=cname,
                    module_id=module_id, module=module,
                    scenario=str(sc.get("name") or cname),
                    steps=steps,
                    dependencies=[str(x) for x in child.get("dependencies") or []],
                ))

    walk(data, str(data.get("id") or "ROOT"), str(data.get("name") or "ROOT"))
    return out


def has_seed_declarations(yaml_path: Path) -> bool:
    """该题需求是否带种子数据声明（Keep=是，BookStack=否）。
    决定 v8 种子通道模式：机械播种 vs 测试自建数据。"""
    text = Path(yaml_path).read_text(encoding="utf-8", errors="replace")
    return "seed data" in text.lower()


def to_json(scenarios: list[Scenario]) -> str:
    return json.dumps([s.to_dict() for s in scenarios],
                      ensure_ascii=False, indent=1)
