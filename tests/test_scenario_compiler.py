# -*- coding: utf-8 -*-
"""场景编译器：requirements.yaml → 结构化场景条目。"""
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from app.utils.scenario_compiler import (
    compile_scenarios,
    has_seed_declarations,
)

YAML_WITH_SEED = """\
id: ROOT
name: Demo App
type: FOLDER
children:
  - id: REQ-1
    name: Home
    type: FOLDER
    children:
      - id: REQ-1.1
        name: Open Home
        type: ATOMIC
        dependencies: []
        scenarios:
          - name: Open Home
            steps:
              - {keyword: GIVEN, content: system accessible}
              - {keyword: WHEN, content: open URL}
              - {keyword: THEN, content: home displayed}
  - id: REQ-2
    name: Notes
    type: FOLDER
    children:
      - id: REQ-2.1
        name: Note Listing
        type: ATOMIC
        dependencies: [REQ-1.1]
        description: "Seed data: pinned note \\"Sprint goals\\"."
        scenarios:
          - name: Note Listing
            steps:
              - {keyword: THEN, content: notes listed}
"""


def _write(tmp_path, text):
    p = tmp_path / "requirements.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_compile_flat_scenarios_in_order(tmp_path):
    req = _write(tmp_path, YAML_WITH_SEED)
    out = compile_scenarios(req)
    assert [s.req_id for s in out] == ["REQ-1.1", "REQ-2.1"]
    assert out[0].module == "Home"
    assert out[1].module == "Notes"
    assert [st.keyword for st in out[0].steps] == ["GIVEN", "WHEN", "THEN"]
    assert out[1].dependencies == ["REQ-1.1"]


def test_seed_declaration_detection(tmp_path):
    assert has_seed_declarations(_write(tmp_path, YAML_WITH_SEED)) is True
    plain = YAML_WITH_SEED.replace("Seed data: ", "Nothing: ")
    assert has_seed_declarations(_write(tmp_path, plain)) is False


def test_official_keep_yaml_parses():
    """官方真题冒烟：真实 requirements.yaml 可解析（题面结构回归）。"""
    official = Path(
        r"F:\token-burner\.tmp\arcbench-official"
        r"\arc-bench\webapp\keep\requirements\requirements.yaml")
    if not official.is_file():
        pytest.skip("官方仓库未克隆")
    out = compile_scenarios(official)
    assert len(out) >= 30, "Keep 32 题场景应全部编译"
    ids = {s.req_id for s in out}
    assert "REQ-1.1" in ids and "REQ-2.8.3" in ids
