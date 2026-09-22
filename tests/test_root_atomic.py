# 根级 ATOMIC（REQ-0 入口验收）回归：官方题面 so/prestashop/ctrip 实证
# 旧渲染只走 FOLDER 分支，根级需求在全文/摘要/节点切分/UX 清单四通道全体失踪。
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.arcbench_ingest import (  # noqa: E402
    render_requirement_text, render_folder_summary,
)
from app.acceptance_compile import (  # noqa: E402
    compile_checklists_from_text, render_ux_checklist,
)
from app.utils.selftest_gate import _split_atomic_nodes  # noqa: E402

TREE_WITH_ROOT = {
    "id": "ROOT", "type": "FOLDER", "name": "Demo", "description": "演示应用。",
    "children": [
        {
            "id": "REQ-0", "type": "ATOMIC", "name": "Open Homepage",
            "description": "Opening the root URL loads the homepage shell.",
            "scenarios": [{
                "name": "root url",
                "steps": [
                    {"keyword": "WHEN", "content": 'the user opens "/"'},
                    {"keyword": "THEN", "content": 'the text "Sign in" is visible'},
                ],
            }],
        },
        {
            "id": "notes", "type": "FOLDER", "name": "Notes",
            "description": "笔记模块。", "dependencies": [],
            "children": [{
                "id": "REQ-1.1", "type": "ATOMIC", "name": "Create Note",
                "description": "Create a note.",
                "scenarios": [{
                    "name": "create",
                    "steps": [
                        {"keyword": "WHEN", "content": 'click "Create"'},
                        {"keyword": "THEN", "content": 'see "Note saved"'},
                    ],
                }],
            }],
        },
    ],
}

TREE_NO_ROOT_ATOMIC = {**TREE_WITH_ROOT,
                       "children": [TREE_WITH_ROOT["children"][1]]}


class TestRootAtomicRender:
    def test_full_text_contains_root_node(self):
        text = render_requirement_text(TREE_WITH_ROOT)
        assert "### REQ-0 Open Homepage（验收标准）" in text
        assert "全局入口验收" in text
        # 根级段必须先于任何「## 模块」段（UX 清单 module=ROOT 依赖此顺序）
        assert text.index("### REQ-0") < text.index("## 模块：")

    def test_atomic_total_counts_root(self):
        text = render_requirement_text(TREE_WITH_ROOT)
        assert "共 1 个功能模块、2 条原子验收需求" in text

    def test_no_root_section_when_absent(self):
        text = render_requirement_text(TREE_NO_ROOT_ATOMIC)
        assert "全局入口验收" not in text
        assert "### REQ-0" not in text

    def test_summary_lists_root_node(self):
        brief = render_folder_summary(TREE_WITH_ROOT)
        assert "REQ-0 Open Homepage" in brief
        assert "全局入口验收" in brief


class TestRootAtomicDownstream:
    def setup_method(self):
        self.text = render_requirement_text(TREE_WITH_ROOT)

    def test_checklist_text_channel_captures_root(self):
        cls = compile_checklists_from_text(self.text)
        by_id = {c.req_id: c for c in cls}
        assert "REQ-0" in by_id
        assert by_id["REQ-0"].module_id == "ROOT"
        assert "Sign in" in by_id["REQ-0"].behavior_expectations

    def test_splitter_captures_root_node(self):
        nodes, global_ctx = _split_atomic_nodes(self.text)
        ids = [nid for nid, _ in nodes]
        assert "REQ-0" in ids and "REQ-1.1" in ids
        root_text = dict(nodes)["REQ-0"]
        assert "Sign in" in root_text
        # 根级节点不得携带上一个（或空的）模块上下文串段
        assert "## 模块：" not in root_text

    def test_ux_checklist_includes_root_line(self):
        cls = compile_checklists_from_text(self.text)
        rendered = render_ux_checklist(cls)
        assert "REQ-0 Open Homepage" in rendered

    def test_batched_flow_no_fallback_when_only_root_missing_before(self):
        # 全文含结构 → 切分非空 → ensure_selftests 不再走整段单批回落
        nodes, _ = _split_atomic_nodes(self.text)
        assert len(nodes) == 2
