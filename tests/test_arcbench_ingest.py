"""ArcBench 需求树摄取：yaml 解析、渲染契约、夹具读取。"""

from pathlib import Path
from textwrap import dedent

import yaml

from app.arcbench_ingest import (
    load_fixture_hint,
    load_requirement_tree,
    render_requirement_text,
)

_TREE = dedent(
    """\
    id: ROOT
    name: Demo App
    type: FOLDER
    description: Root description.
    children:
      - id: REQ-1
        name: Home
        type: FOLDER
        description: Home page module.
        dependencies: []
        children:
          - id: REQ-1.1
            name: Enter
            type: ATOMIC
            description: Open and display home page.
            dependencies: []
            scenarios:
              - name: Enter
                steps:
                  - keyword: GIVEN
                    content: Browser available.
                  - keyword: WHEN
                    content: Open entry URL.
                  - keyword: THEN
                    content: Home page displayed.
      - id: REQ-2
        name: Notes
        type: FOLDER
        description: Notes module.
        dependencies:
          - REQ-1
        children:
          - id: REQ-2.1
            name: Create
            type: ATOMIC
            description: Create a note.
            dependencies:
              - REQ-1.1
            scenarios:
              - name: Create
                steps:
                  - keyword: THEN
                    content: Note created.
    """
)


def _write_tree(tmp_path: Path) -> Path:
    req_dir = tmp_path / "requirements"
    req_dir.mkdir(parents=True)
    (req_dir / "requirements.yaml").write_text(_TREE, encoding="utf-8")
    return req_dir


def test_load_requirement_tree_reads_yaml(tmp_path):
    req_dir = _write_tree(tmp_path)
    tree, path = load_requirement_tree(req_dir)
    assert tree["name"] == "Demo App"
    assert path.name == "requirements.yaml"


def test_load_requirement_tree_missing(tmp_path):
    try:
        load_requirement_tree(tmp_path)
    except FileNotFoundError:
        return
    raise AssertionError("应抛 FileNotFoundError")


def test_render_contains_modules_scenarios_and_contract(tmp_path):
    req_dir = _write_tree(tmp_path)
    tree, _ = load_requirement_tree(req_dir)
    text = render_requirement_text(tree)
    assert "## 模块：REQ-1 Home" in text
    assert "## 模块：REQ-2 Notes" in text
    assert "依赖：REQ-1" in text
    assert "### REQ-1.1 Enter（验收标准）" in text
    assert "WHEN: Open entry URL." in text
    assert "GET /api/health" in text
    assert "环境变量 PORT" in text
    assert "严禁任何形式的 HTTP 模拟" in text
    assert "create_app" in text
    assert "共 2 个功能模块、2 条原子验收需求。" in text


def test_fixture_hint_reads_helpers_ts(tmp_path):
    req_dir = _write_tree(tmp_path)
    tests_dir = req_dir.parent / "tests"
    tests_dir.mkdir()
    (tests_dir / "helpers.ts").write_text("export const FIXTURES = {}", encoding="utf-8")
    hint = load_fixture_hint(req_dir)
    assert "FIXTURES" in hint
    assert load_fixture_hint(tmp_path / "other" / "req") == ""


def test_fixture_tail_facts_survive_truncation(tmp_path):
    """12306 取证回归：8000 截断点后的逐字 UI 标签须以续块存活，
    ARIA role/机制代码串不得混入。"""
    req_dir = _write_tree(tmp_path)
    tests_dir = req_dir.parent / "tests"
    tests_dir.mkdir()
    tail = (
        'page.getByLabel("Passport number").fill(x);\n'
        'await expect(page.getByRole("combobox")).toBeVisible();\n'
        'const role = "button"; const seed = "arrival@hub.com";\n'
        'expect(text).toBe("Arrival Time");\n'
        'expect(zh).toBe("本周无排班");\n'
    )
    body = 'export const HEAD = "Login";\n' + ("// pad\n" * 1400) + tail
    (tests_dir / "helpers.ts").write_text(body, encoding="utf-8")
    hint = load_fixture_hint(req_dir)
    assert len(body) > 8000
    assert "【夹具截断尾部关键串" in hint
    cont = hint.split("【夹具截断尾部关键串", 1)[1]
    assert "Passport number" in cont and "Arrival Time" in cont
    assert "本周无排班" in cont  # 纯 CJK 标签无大小写/空格线索，须按字符区间保留
    assert "arrival@hub.com" in cont
    assert "combobox" not in cont and "button" not in cont
    assert "Login" in hint  # head 段原样保留


def test_fixture_short_file_unchanged(tmp_path):
    req_dir = _write_tree(tmp_path)
    tests_dir = req_dir.parent / "tests"
    tests_dir.mkdir()
    raw = 'export const S = "Short file";'
    (tests_dir / "helpers.ts").write_text(raw, encoding="utf-8")
    assert load_fixture_hint(req_dir) == raw


# ---- factory26 r4：夹具多布局探测 + 查询必须走种子的硬性契约 ----

def test_locate_fixture_three_layouts(tmp_path):
    """兄弟目录 / 嵌套 tests/ / 平铺三种布局都能命中。"""
    from app.arcbench_ingest import locate_fixture

    # ① 平台布局：requirements/ 与 tests/ 兄弟
    req_dir = _write_tree(tmp_path / "a")
    tests_dir = req_dir.parent / "tests"
    tests_dir.mkdir()
    (tests_dir / "helpers.ts").write_text("A", encoding="utf-8")
    assert locate_fixture(req_dir) == tests_dir / "helpers.ts"

    # ② 嵌套布局：requirements/tests/helpers.ts（r3 演练踩过的坑）
    req_dir2 = _write_tree(tmp_path / "b")
    nested = req_dir2 / "tests"
    nested.mkdir()
    (nested / "helpers.ts").write_text("B", encoding="utf-8")
    assert locate_fixture(req_dir2) == nested / "helpers.ts"

    # ③ 平铺：helpers.ts 与 requirements.yaml 同目录
    req_dir3 = _write_tree(tmp_path / "c")
    (req_dir3 / "helpers.ts").write_text("C", encoding="utf-8")
    assert locate_fixture(req_dir3) == req_dir3 / "helpers.ts"


def test_render_requires_db_backed_queries():
    """硬性契约 13：查询/列表必须查库种子，禁止硬编码降级列表。"""
    import yaml

    tree = yaml.safe_load(_TREE)
    text = render_requirement_text(tree)
    assert "严禁返回硬编码静态列表" in text
    assert "内置降级 mock" in text
    assert "判定集成失败" in text


def test_render_requires_single_anchored_database():
    """硬性契约 14：唯一锚定数据库，禁止 CWD 相对路径与多库并存
    （r7c-2 实弹取证：三库并存致种子/搜索读写分离，评测必挂）。"""
    import yaml

    tree = yaml.safe_load(_TREE)
    text = render_requirement_text(tree)
    assert "共用唯一数据库" in text
    assert "Path(__file__)" in text
    assert "严禁 CWD 相对路径" in text
    assert "多库并存判定集成失败" in text
