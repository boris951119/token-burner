# -*- coding: utf-8 -*-
"""验收清单编译器 + 编译判分器解析层的回归测试（零 LLM，全内联夹具）。"""
import json
from pathlib import Path

from app.acceptance_compile import (
    NodeChecklist,
    compile_checklists,
    render_checklist_spec,
    to_json,
)

REQ_YAML = """
id: ROOT
type: FOLDER
children:
  - id: REQ-1
    name: Notes
    type: FOLDER
    children:
      - id: REQ-1.1
        name: Note Listing
        type: ATOMIC
        description: >
          Seed data: pinned note "Alpha one" and regular note "Beta two".
          The home page lists every note. ![diagram](img/list.png)
        scenarios:
          - name: list
            steps:
              - keyword: GIVEN
                content: 'The app is open on the home page'
              - keyword: WHEN
                content: 'press the "New note" button'
              - keyword: THEN
                content: 'a dialog with "Title" field opens; owner "Test User" '
      - id: REQ-1.2
        name: Deep Edit
        type: ATOMIC
        description: 'Seed data: note "Gamma three" exists.'
        scenarios:
          - name: edit
            steps:
              - keyword: GIVEN
                content: 'the note card is open'
              - keyword: WHEN
                content: 'type into "Body"'
              - keyword: THEN
                content: 'the text "Gamma three" is replaced by "Saved ok"'
  - id: REQ-9
    name: Account
    type: FOLDER
    children:
      - id: REQ-9.1
        name: Login
        type: ATOMIC
        description: 'Seed data: user "Demo Person" with email demo@example.com and password Secret123!'
        scenarios:
          - name: login
            steps:
              - keyword: GIVEN
                content: 'the entry url is opened'
              - keyword: WHEN
                content: 'fill "Email address" and "Password"'
              - keyword: THEN
                content: 'home page shows "Demo Person"'
"""


def _write(tmp_path: Path, text: str = REQ_YAML) -> Path:
    p = tmp_path / "requirements.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_node_counts_and_bucketing(tmp_path):
    cls = compile_checklists(_write(tmp_path))
    by_id = {c.req_id: c for c in cls}
    assert set(by_id) == {"REQ-1.1", "REQ-1.2", "REQ-9.1"}
    n11 = by_id["REQ-1.1"]
    assert n11.seed_entities == ["Alpha one", "Beta two"]
    assert "New note" in n11.control_labels
    assert "Title" in n11.behavior_expectations
    assert "list.png" not in json.dumps(n11.to_dict())   # 图片残渣剔除
    assert n11.language in ("latin", "unknown")   # 非 CJK 主导（样本 <200 字符时 unknown）


def test_credential_seeds_excluded(tmp_path):
    n91 = {c.req_id: c for c in compile_checklists(_write(tmp_path))}["REQ-9.1"]
    assert n91.seed_entities == ["Demo Person"]          # 邮箱/密码是输入值不可见
    assert n91.home_visible                              # entry url 提示也算入口


def test_home_visible_classification(tmp_path):
    by_id = {c.req_id: c for c in compile_checklists(_write(tmp_path))}
    assert by_id["REQ-1.1"].home_visible
    assert not by_id["REQ-1.2"].home_visible             # 无首页/入口提示 → 不判分


def test_behavior_dedup_against_seed_and_control(tmp_path):
    by_id = {c.req_id: c for c in compile_checklists(_write(tmp_path))}
    n11 = by_id["REQ-1.1"]
    # THEN 复述的种子名不重复进行为断言（1.2 的 Gamma three 属 seed 通道）
    assert "Alpha one" not in n11.behavior_expectations


def test_yaml_self_healing_indent_damage(tmp_path):
    damaged = REQ_YAML.replace(
        '        description: >\n', '        description: >\n            \n')
    damaged = damaged.replace(
        '          Seed data: pinned note "Alpha one" and regular note "Beta two".\n'
        '          The home page lists every note. ![diagram](img/list.png)\n',
        '                Seed data: pinned note "Alpha one" and regular note "Beta two".\n'
        '                The home page lists every note. ![diagram](img/list.png)\n')
    cls = compile_checklists(_write(tmp_path, damaged))
    assert len(cls) == 3


def test_yaml_garbage_degrades_empty(tmp_path):
    assert compile_checklists(_write(tmp_path, "\t: :[bogus\n")) == []


def test_render_spec_home_nodes_only_and_syntax(tmp_path):
    cls = compile_checklists(_write(tmp_path))
    spec = render_checklist_spec(cls)
    assert "async ({ page }) =>" in spec
    assert "REQ-1.2" not in spec                        # 非入口节点不编译
    assert "Secret123!" not in spec
    assert spec.count("test('REQ-") >= 5
    assert "Gamma three" not in spec


def test_render_spec_escapes_cjk_and_quotes():
    ck = NodeChecklist(req_id="REQ-1.1", req_name="n", module_id="REQ-1",
                       language="zh", home_visible=True,
                       seed_entities=['他说"引号"与中文'], control_labels=[])
    spec = render_checklist_spec([ck])
    assert "他说" in spec                               # ensure_ascii=False 原样
    token = spec.split("getByText(", 1)[1].split(", {", 1)[0]
    assert json.loads(token) == '他说"引号"与中文'   # 转义后可被 JSON 原样还原


def test_to_json_roundtrip(tmp_path):
    cls = compile_checklists(_write(tmp_path))
    data = json.loads(to_json(cls))
    assert [d["req_id"] for d in data] == [c.req_id for c in cls]
