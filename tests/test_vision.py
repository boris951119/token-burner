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


class TestVisionEndpoints:
    """gen-4 取证：平台注入 VISUAL_BASE_URL/VISUAL_MODEL=gpt-5.5——
    官方视觉通道必须优先于中转站兜底链。"""

    def test_official_channel_first(self, monkeypatch):
        from app.utils import vision

        monkeypatch.setenv("VISUAL_BASE_URL", "https://api.key7qi.com/v1")
        monkeypatch.setenv("VISUAL_MODEL", "gpt-5.5")
        eps = vision._vision_endpoints("key", "https://relay.example/v1")
        assert eps[0][0] == "gpt-5.5"
        assert eps[0][1] == "https://api.key7qi.com/v1"
        assert [e[0] for e in eps][1:] == ["kimi-k3", "minimax-m3"], (
            "中转站兜底链必须跟在官方通道后")

    def test_no_env_falls_back_to_relay_chain(self, monkeypatch):
        from app.utils import vision

        monkeypatch.delenv("VISUAL_BASE_URL", raising=False)
        monkeypatch.delenv("VISUAL_MODEL", raising=False)
        eps = vision._vision_endpoints("key", "https://relay.example/v1")
        assert [e[0] for e in eps][:2] == ["kimi-k3", "minimax-m3"]
