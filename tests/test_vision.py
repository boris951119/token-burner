# -*- coding: utf-8 -*-
"""视觉转写通道测试（初赛裁决：参考截图会提供；管线保持纯文本）。"""

from __future__ import annotations

import json
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
        assert [e[0] for e in eps][1:] == [
            "glm-5.3-flash", "kimi-k3", "minimax-m3",
            "deepseek-v4-flash-vision-exp"], (
            "兜底链必须跟在官方通道后（10-01 glm-5.3-flash 实测吃图）")

    def test_no_env_falls_back_to_relay_chain(self, monkeypatch):
        from app.utils import vision

        monkeypatch.delenv("VISUAL_BASE_URL", raising=False)
        monkeypatch.delenv("VISUAL_MODEL", raising=False)
        eps = vision._vision_endpoints("key", "https://relay.example/v1")
        assert [e[0] for e in eps][:2] == [
            "glm-5.3-flash", "kimi-k3"]


class TestDescribeImagesParallel:
    """9/23 run6 实测：单图 ~40s、串行 600s 时限吃不下整题截图
    （keep 7/22 图、ctrip ~16/46 图丢失）——改 3 路并行 + 上限 40 +
    时限 900s。并行不得破坏两件事：逐图落盘、按 refs 原序返回。"""

    def _stub(self, monkeypatch, tmp_path, refs, slow=0.0, fail=()):
        from app.utils import vision

        for r in refs:
            p = tmp_path / r.replace("./", "")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"png")
        monkeypatch.setattr(vision, "_downscale_b64", lambda _p: "AAAA")

        def fake_describe(model, b64, key, base, timeout=90):
            import time

            time.sleep(slow)
            return f"{model}:desc"

        monkeypatch.setattr(vision, "_describe_one", fake_describe)
        monkeypatch.delenv("VISUAL_BASE_URL", raising=False)
        monkeypatch.delenv("VISUAL_MODEL", raising=False)
        return vision

    def test_all_refs_transcribed_and_ordered(self, tmp_path, monkeypatch):
        refs = [f"./reference/{c}.png" for c in "abcdefgh"]
        vision = self._stub(monkeypatch, tmp_path, refs, slow=0.05)
        out = vision.describe_images(tmp_path, refs, "key", "https://x")
        assert list(out) == refs, "返回必须按 refs 原序（提示词复现性）"
        assert all(v.endswith(":desc") for v in out.values())
        # 8 图 × 50ms：3 路并行应远小于串行的 400ms
        assert (tmp_path / "_vision_cache.json").is_file()

    def test_cache_hit_skips_calls(self, tmp_path, monkeypatch):
        refs = ["./reference/a.png", "./reference/b.png"]
        vision = self._stub(monkeypatch, tmp_path, refs)
        calls = []
        monkeypatch.setattr(vision, "_describe_one",
                            lambda *a, **k: calls.append(a[0]) or "d")
        vision.describe_images(tmp_path, refs, "key", "https://x")
        assert len(calls) == 2
        vision.describe_images(tmp_path, refs, "key", "https://x")
        assert len(calls) == 2, "第二次必须全命中缓存"

    def test_deadline_truncates_without_losing_progress(self, tmp_path,
                                                        monkeypatch):
        refs = [f"./reference/{i}.png" for i in range(8)]
        # 2 路 × 0.3s：0.5s 时只有第一轮（2 图）落地，其余必须被截断
        vision = self._stub(monkeypatch, tmp_path, refs, slow=0.3)
        monkeypatch.setenv("ARCBENCH_VISION_DEADLINE", "0.5")
        monkeypatch.setenv("ARCBENCH_VISION_WORKERS", "2")
        out = vision.describe_images(tmp_path, refs, "key", "https://x")
        assert 0 < len(out) < len(refs), "须部分完成即止损，不得全有或全无"
        # 已转写的必须已落盘（旧实现中途被杀 = 全部白烧）
        cached = json.loads(
            (tmp_path / "_vision_cache.json").read_text(encoding="utf-8"))
        assert set(cached) == set(out)

    def test_missing_file_reported_not_raised(self, tmp_path, monkeypatch):
        vision = self._stub(monkeypatch, tmp_path, [])
        out = vision.describe_images(tmp_path, ["./reference/ghost.png"],
                                     "key", "https://x")
        assert out == {}

