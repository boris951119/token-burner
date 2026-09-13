# -*- coding: utf-8 -*-
"""视觉转写通道测试（初赛裁决：参考截图会提供；管线保持纯文本）。"""

from __future__ import annotations

from pathlib import Path

from app.utils.vision import (
    _describe_one,
    find_image_refs,
    render_image_section,
)


def _tree_with_imgs(*refs: str) -> dict:
    desc = f"首页见 ![{refs[0]}]({refs[0]})" if refs else "纯文本需求"
    return {
        "id": "ROOT", "type": "FOLDER",
        "description": desc,
        "children": [
            {"id": "REQ-1", "type": "ATOMIC",
             "description": f"表单见 ![]({r})" if r else "",
             "children": []}
            for r in refs
        ],
    }


class TestFindImageRefs:
    def test_extracts_refs_in_order_dedup(self):
        tree = _tree_with_imgs("./reference/a.png", "./reference/b.png",
                               "./reference/a.png")
        refs = find_image_refs(tree)
        assert refs == ["./reference/a.png", "./reference/b.png"]

    def test_no_refs_empty(self):
        assert find_image_refs(_tree_with_imgs()) == []


class TestGuards:
    def test_describe_one_refuses_empty_payload(self):
        import pytest

        with pytest.raises(RuntimeError, match="empty image payload"):
            _describe_one("kimi-k3", "", "key", "https://x")

    def test_render_section(self):
        s = render_image_section({"./reference/a.png": "蓝色导航栏"})
        assert "参考截图描述" in s and "蓝色导航栏" in s

    def test_render_empty(self):
        assert render_image_section({}) == ""
