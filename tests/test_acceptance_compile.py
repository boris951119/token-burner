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
            assert got.click_controls == ref.click_controls, rid
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
    assert ck.home_visible is True, "首页提示应识别中文'首页'"
    # 「输入 “张三”」的张三 是评测自己敲进输入框的值，不承诺界面预先显示；
    # 它若真是种子数据，由 Seed data 通道负责可见性（本夹具即这一路）。
    assert "张三" not in ck.control_labels
    assert "张三" in ck.seed_entities


def test_cjk_seed_names_reach_seed_channel(tmp_path):
    ck = {c.req_id: c for c in compile_checklists(_write(tmp_path, REQ_YAML_CJK))}["REQ-1.1"]
    assert "示例博客" in ck.seed_entities


def test_cjk_sentence_like_quotes_are_not_control_labels(tmp_path):
    """中文无空格 → 12 词上限恒不生效；含句读的引号串是提示语不是控件，
    按"必须静态可见"判分即幻影失败。行为通道（THEN）不受此限。"""
    ck = {c.req_id: c for c in compile_checklists(_write(tmp_path, REQ_YAML_CJK))}["REQ-1.1"]
    assert "用户名不存在，请核对" not in ck.control_labels
    assert "欢迎回来" in ck.behavior_expectations


def test_typed_input_values_are_not_interface_copy(tmp_path):
    """WHEN 里输入类动词引出的引号串是评测自己敲进控件的值：按「必须预先
    出现在页面上」判红即假红，且模型最省事的满足方式恰是塞成 hidden 表单的
    placeholder（9/23 mini 彩排实测）。点击动词引出的那条不受影响——它是
    真控件，评测按 role+name 硬定位。"""
    def ck(when: str):
        yaml = ('id: ROOT\ntype: FOLDER\nchildren:\n'
                '  - id: REQ-1\n    name: Links\n    type: FOLDER\n'
                '    children:\n'
                '      - id: REQ-1.1\n        name: Create\n        type: ATOMIC\n'
                '        description: Home page of the app.\n        scenarios:\n'
                '          - name: s\n            steps:\n'
                '              - keyword: WHEN\n'
                f'                content: {when}\n'
                '              - keyword: THEN\n'
                '                content: The row "Conference slides" appears\n')
        return compile_checklists(_write(tmp_path, yaml))[0]

    n = ck('Click the "New link" button, fill the form with title '
           '"Conference slides" and URL "https://example.org/slides", '
           'then submit')
    assert n.control_labels == ["New link"]
    assert n.click_controls == ["New link"]
    # 值不承诺预先可见，但 THEN 里复述它仍是行为断言（通道没丢事实）
    assert "Conference slides" in n.behavior_expectations

    assert ck('Type "handbook" into the search box').control_labels == []
    # 动词在引号之后不算数：填值动作发生在点击之后，X 仍是控件
    assert ck('Click "Go" after typing the query').control_labels == ["Go"]
    # 引号紧跟字段类名词时它是**输入框的名字**（评测按 label/placeholder 定位
    # 的就是它），不是要打的值——这一条必须留在控件通道
    assert ck('Fill in the "Title" field and click "Save"').control_labels \
        == ["Title", "Save"]
    zh = ck('输入 “关键词” 后点击 “搜索”')
    assert zh.control_labels == ["搜索"] and zh.click_controls == ["搜索"]
    assert ck('填写 “书名” 字段').control_labels == ["书名"]


def test_cjk_and_ascii_quote_channels_are_parity(tmp_path):
    """同一份中文题面把 “” 换成 ASCII 引号，控件清单必须逐字相同。"""
    cjk = compile_checklists(_write(tmp_path, REQ_YAML_CJK))
    ascii_yaml = REQ_YAML_CJK.replace("“", '"').replace("”", '"')
    ref = compile_checklists(_write(tmp_path, ascii_yaml))
    assert [c.control_labels for c in cjk] == [c.control_labels for c in ref]
    assert [c.seed_entities for c in cjk] == [c.seed_entities for c in ref]


# ---- Markdown 反引号通道（9/23 取证）-----------------------------------
# 官方语料里有整份题面把界面文案写成 `Shelves` 式内联代码：三条引号通道
# 一条不认，34 个节点编译出 0 条事实——UX 契约与平台判分闸双双零输入。
# 反引号同时被用来标代码符号，所以只收「像界面文案」的串。

REQ_YAML_BT = """
id: ROOT
type: FOLDER
children:
  - id: REQ-1
    name: Shelves
    type: FOLDER
    children:
      - id: REQ-1.1
        name: Shelf List
        type: ATOMIC
        description: 'Seed data: shelf `Reading list` and book `Deep Work`.
          The home page lists every shelf.'
        scenarios:
          - name: open
            steps:
              - keyword: GIVEN
                content: 'the app is open on the home page'
              - keyword: WHEN
                content: 'click `Shelves` then `New Shelf`; ignore `created_at`
                  and `/api/books` and `JSON` and ```press "Deprecated save"```'
              - keyword: THEN
                content: 'the form shows `Save Shelf`'
"""


def _bt_ck(tmp_path):
    return {c.req_id: c for c in compile_checklists(_write(tmp_path, REQ_YAML_BT))}["REQ-1.1"]


def test_backtick_labels_reach_all_three_channels(tmp_path):
    ck = _bt_ck(tmp_path)
    assert "Shelves" in ck.control_labels and "New Shelf" in ck.control_labels
    assert "Save Shelf" in ck.behavior_expectations
    assert "Reading list" in ck.seed_entities and "Deep Work" in ck.seed_entities


def test_backtick_code_tokens_are_not_labels(tmp_path):
    """标识符/端点路径/技术缩写/代码围栏内的引号都不算界面文案：
    按可见文案判分即幻影失败，还会把修复环引向编造。"""
    ck = _bt_ck(tmp_path)
    for junk in ("created_at", "/api/books", "JSON", "Deprecated save"):
        assert junk not in ck.control_labels, junk
    assert "Deprecated save" not in ck.behavior_expectations


def test_ux_checklist_forbids_invisible_placement(tmp_path):
    """注入契约必须写清「隐藏位置不算实现」——keep#2 那份交付正是把英文
    文案塞进 display:none 的 div 里骗过文本在场检查的。"""
    from app.acceptance_compile import render_ux_checklist

    s = render_ux_checklist(compile_checklists(_write(tmp_path)))
    assert "display:none" in s and "注释" in s and "可见" in s


# ---- 路由/URL 整串不是界面文案（9/23 判分器幻影取证）-------------------
# GWT 首步惯用 WHEN the user opens "/"。引号通道照单全收时 "/" 变成一条
# 「必须出现在页面上」的控件文案——三组对照实测：一份服务端渲染、文案齐全
# 的**正确**应用因此稳定判红 1 条，而这条红修不好（浏览器把路由显示在地址
# 栏，DOM 里根本没有它）。修复环拿到它只会往页面上写无意义的斜杠。

REQ_YAML_ROUTE = """
id: ROOT
type: FOLDER
children:
  - id: REQ-1
    name: Home
    type: ATOMIC
    description: 'Seed data: "/" and the book "Dune". The home page lists them.'
    scenarios:
      - name: open
        steps:
          - keyword: WHEN
            content: 'the user opens "/" and clicks "Archived/Deleted"'
          - keyword: THEN
            content: 'the app routes to "/notes" or "#/settings"
              or "https://example.com/shelf"'
"""


def _route_ck(tmp_path):
    return {c.req_id: c for c in
            compile_checklists(_write(tmp_path, REQ_YAML_ROUTE))}["REQ-1"]


def test_route_tokens_are_not_facts_in_any_channel(tmp_path):
    ck = _route_ck(tmp_path)
    for route in ("/", "/notes", "#/settings", "https://example.com/shelf"):
        assert route not in ck.control_labels, route
        assert route not in ck.seed_entities, route
        assert route not in ck.behavior_expectations, route


def test_label_that_merely_contains_a_slash_survives(tmp_path):
    """剔除口径是「整串就是一个路由」，不是「带斜杠就剔」——
    Archived/Deleted 这类真实按钮文案不得被连带倒掉。"""
    ck = _route_ck(tmp_path)
    assert "Archived/Deleted" in ck.control_labels
    assert "Dune" in ck.seed_entities


def test_route_filter_boundaries():
    """判据是「整串就是一个路径」，不是「带斜杠就剔」：漏收让 UX 契约变薄，
    多收让判分器摊派修不好的幻影失败，两头都要钉住。"""
    from app.acceptance_compile import _clean_quote

    for keep in ("Archived/Deleted", "#1 Bestseller", "A / B", "Notes",
                 "/ and \\ are separators"):
        assert _clean_quote(keep) == keep, keep
    for drop in ("/", "/notes", "/#", "#/settings", "./x", "../x",
                 "https://example.com/s", "/a/b?c=1"):
        assert _clean_quote(drop) is None, drop


def test_ux_checklist_keeps_actions_gated(tmp_path):
    """9/23 快照取证：静态判分环把「控件须可见」讲成硬契约后，模型把
    每个节点的控件与动作后文案一次性摊在首页（一排同名按钮 + 无交互），
    本地全绿而评测按序操作依旧落空——清单必须把「触发时机」说清楚。"""
    from app.acceptance_compile import compile_checklists, render_ux_checklist

    s = render_ux_checklist(compile_checklists(_write(tmp_path)))
    assert "控件本身" in s, "控件与动作后文案的可见时机必须分开说"
    assert "触发" in s and "交互链" in s


def test_ux_checklist_demands_wired_click_targets(tmp_path):
    """9/23 判分红叶取证：可点通道按标签名认控件，于是交付首页把需求动作
    名词抄成一批无 <form>、无脚本、无处理器的 <button> 就骗过了本地全绿，
    评测却在这些按钮上点了 29 次超时。契约必须自己说清「点了要有反应」，
    否则修复环学会的第一课就是造诱饵页。"""
    from app.acceptance_compile import compile_checklists, render_ux_checklist

    s = render_ux_checklist(compile_checklists(_write(tmp_path)))
    assert "点了不会动的按钮与正文文字等价" in s
    line = next(ln for ln in s.splitlines() if "需求要求点击" in ln)
    assert "真有反应" in line and "<form>" in line


# ---- 可点击控件子集（9/23 取证：文案可见 ≠ 控件存在）--------------------
# 官方按 getByRole('button'/'link', {name}) 点控件，无文本兜底；判分器要把
# 「必须做成可点控件」的事实从「必须出现在页面上」里分出来，动词归属
# 只能逐条看引号前的最近动词——一步里常混着输入动词。

def test_click_verb_attributes_per_quote():
    from app.acceptance_compile import _click_quotes_in

    step = ('Click the "Take a note" form, enter a title in the "Title" '
            'field and content in the "Note content" field')
    assert _click_quotes_in(step) == ["Take a note"]
    assert _click_quotes_in('Hover a row, open options, choose "Delete Note"') \
        == ["Delete Note"]
    assert _click_quotes_in("按下「保存」按钮后出现提示") == ["保存"]
    # 没有点击动词 / 动词离引号太远（跨句）都不算
    assert _click_quotes_in('The "Title" field shows the note title') == []
    assert _click_quotes_in('Click somewhere then type "Search"') == []


def test_click_subset_of_controls_and_flows_to_checklist(tmp_path):
    from app.acceptance_compile import compile_checklists

    cls = {c.req_id: c for c in compile_checklists(_write(tmp_path))}
    for rid, ck in cls.items():
        assert set(ck.click_controls) <= set(ck.control_labels), rid
    hit = [c for c in cls.values() if c.click_controls]
    assert hit, "夹具里必须有一条点击事实，否则本测等于没测"


def test_backtick_written_ui_labels_reach_the_click_channel():
    """界面文案在题面里有引号与 Markdown 反引号两种写法（6 套题面实测
    点击事实 0 : 31 的分布）：只认引号的那一版，整条「必须做成可点控件」
    判分在反引号类任务上静默失效。opens/打开 也在点击动词表内——需求写
    "opens the `New Shelf` flow" 就是要求一个入口控件。"""
    from app.acceptance_compile import _click_quotes_in

    assert _click_quotes_in(
        "The user clicks `Login` in the top navigation bar.") == ["Login"]
    assert _click_quotes_in(
        "opens the `New Shelf` flow and clicks `Save Shelf`") \
        == ["New Shelf", "Save Shelf"]
    # 反引号里的端点与标识符不是界面文案，不得成为判分事实
    assert _click_quotes_in("clicks `/api/books` then `submit_form`") == []
