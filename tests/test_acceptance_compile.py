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


class TestTextChannel:
    """拆分期只有 ingest 渲染文本没有 YAML——文本通道与 YAML 通道同口径。"""

    def _text(self):
        import yaml
        from app.arcbench_ingest import render_requirement_text
        return render_requirement_text(yaml.safe_load(REQ_YAML))

    def test_parity_with_yaml_channel(self, tmp_path):
        from app.acceptance_compile import compile_checklists_from_text
        yaml_side = {c.req_id: c for c in compile_checklists(_write(tmp_path))}
        text_side = {c.req_id: c for c in
                     compile_checklists_from_text(self._text())}
        assert set(text_side) == set(yaml_side)
        for rid, ref in yaml_side.items():
            got = text_side[rid]
            assert got.seed_entities == ref.seed_entities, rid
            assert got.control_labels == ref.control_labels, rid
            assert got.behavior_expectations == ref.behavior_expectations, rid
            assert got.home_visible == ref.home_visible, rid
            assert got.module_id == ref.module_id, rid

    def test_plain_text_no_structure_empty(self):
        from app.acceptance_compile import compile_checklists_from_text
        assert compile_checklists_from_text("纯文本讨论稿，无节点段。") == []


def test_render_ux_checklist_channel_attribution(tmp_path):
    from app.acceptance_compile import compile_checklists, render_ux_checklist
    s = render_ux_checklist(compile_checklists(_write(tmp_path)))
    assert "验收节点逐字清单" in s
    line = next(ln for ln in s.splitlines() if "REQ-1.1" in ln)
    assert '"New note"' in line and "控件须可见" in line
    assert '"Alpha one"' in line and "种子可见" in line
    assert '"Title"' in line and "动作后须出现" in line
    # 无事实节点不出行，控制 token
    assert "REQ-9.1" in s  # 登录节点有控件与可见种子


# ---- 中文题面引号通道（9/23 取证）-------------------------------------
# 官方题面里有整份中文需求（界面文案一律用 “” 标注）。只认 ASCII 引号时
# 该题编译出 2 条控件事实：写码段的 UX 契约近乎空、平台侧唯一判分闸零信号
# ——恰是"UI 文案必须逐字可见"最要吃准的题面。requirement_anchors 早已按
# “”‘’ 取值，此处补同一口径。夹具用通用词，不含任何题面专名。

REQ_YAML_CJK = """
id: ROOT
type: FOLDER
children:
  - id: REQ-1
    name: 账号
    type: FOLDER
    children:
      - id: REQ-1.1
        name: 登录
        type: ATOMIC
        description: >
          Seed data: 用户 “张三” 与站点 “示例博客”。
          首页显示登录入口。
        scenarios:
          - name: 登录
            steps:
              - keyword: GIVEN
                content: 打开应用首页
              - keyword: WHEN
                content: 点击 “登录” 按钮并输入 “张三”，系统提示 “用户名不存在，请核对”
              - keyword: THEN
                content: 页面出现 “欢迎回来” 提示
"""


def test_cjk_quoted_labels_reach_controls(tmp_path):
    ck = {c.req_id: c for c in compile_checklists(_write(tmp_path, REQ_YAML_CJK))}["REQ-1.1"]
    assert "登录" in ck.control_labels
    assert "张三" in ck.control_labels
    assert ck.home_visible is True, "首页提示应识别中文'首页'"


def test_cjk_seed_names_reach_seed_channel(tmp_path):
    ck = {c.req_id: c for c in compile_checklists(_write(tmp_path, REQ_YAML_CJK))}["REQ-1.1"]
    assert "示例博客" in ck.seed_entities


def test_cjk_sentence_like_quotes_are_not_control_labels(tmp_path):
    """中文无空格 → 12 词上限恒不生效；含句读的引号串是提示语不是控件，
    按"必须静态可见"判分即幻影失败。行为通道（THEN）不受此限。"""
    ck = {c.req_id: c for c in compile_checklists(_write(tmp_path, REQ_YAML_CJK))}["REQ-1.1"]
    assert "用户名不存在，请核对" not in ck.control_labels
    assert "欢迎回来" in ck.behavior_expectations


def test_cjk_and_ascii_quote_channels_are_parity(tmp_path):
    """同一份中文题面把 “” 换成 ASCII 引号，控件清单必须逐字相同。"""
    cjk = compile_checklists(_write(tmp_path, REQ_YAML_CJK))
    ascii_yaml = REQ_YAML_CJK.replace("“", '"').replace("”", '"')
    ref = compile_checklists(_write(tmp_path, ascii_yaml))
    assert [c.control_labels for c in cjk] == [c.control_labels for c in ref]
    assert [c.seed_entities for c in cjk] == [c.seed_entities for c in ref]
