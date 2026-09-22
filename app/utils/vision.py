# -*- coding: utf-8 -*-
"""视觉转写通道（初赛裁决：题目同编译器新生成 + 参考截图会提供）。

需求树描述里内嵌 `![...](./reference/xxx.png)` 参考截图，而管线主力
模型（glm-5.3 等）实测拒图（HTTP 400）。本模块用中转站上实测可用的
视觉模型（kimi-k3 最佳，minimax-m3 备胎）把截图转写成结构化文字
描述，注入需求文本——管线其余部分保持纯文本，无需多模态改造。

取舍：
- 视觉模型链固定在模块内（中转站模型名单稳定），环境变量
  ARCBENCH_VISION_MODEL 可覆盖；不进 config.json（避免全局校验面扩大）。
- 描述缓存写 req_dir/_vision_cache.json——断点续跑/重复演练不重复计费。
- 任何失败都降级为"无描述"（宁缺毋滥，绝不因视觉通道挂掉主流程）。
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
from pathlib import Path

import httpx

# 实测 roster（2026-09-13，1x1 + 真实 UI 图双探测）：
# kimi-k3 完整描述布局/文案/按钮；minimax-m3 可用（带思考前缀）；
# deepseek flash/pro 大图报"截断"；glm-5.3 与 qwen 全家 HTTP 400。
VISION_MODELS = ("openai/kimi-k3", "openai/minimax-m3")

# 需求描述里的内嵌图片引用（Markdown 图语法）
_IMG_REF_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

_MAX_IMAGES = 24          # 单任务截图描述上限（成本护栏）
_MAX_EDGE = 1024          # 长边压到 1024px（token 护栏）


def find_image_refs(tree: dict) -> list[str]:
    """遍历需求树，收集描述里引用的图片相对路径（去重、保序）。"""
    refs: list[str] = []

    def _walk(node: dict) -> None:
        desc = node.get("description") or ""
        for m in _IMG_REF_RE.finditer(desc):
            ref = m.group(1).strip()
            if ref and ref not in refs:
                refs.append(ref)
        for child in node.get("children") or []:
            _walk(child)

    _walk(tree)
    return refs


def _downscale_b64(path: Path) -> str | None:
    """读图并压到长边 _MAX_EDGE，返回 base64；失败返回 None。"""
    try:
        from PIL import Image

        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            scale = _MAX_EDGE / max(w, h)
            if scale < 1:
                im = im.resize((int(w * scale), int(h * scale)))
            buf = io.BytesIO()
            im.save(buf, "PNG")
            return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _describe_one(model: str, b64: str, key: str, base: str,
                  timeout: int = 180) -> str:
    """单图描述调用（OpenAI 兼容 chat completions 图片消息）。"""
    if not b64:
        # 防线：无效图绝不上发——视觉模型对垃圾输入会幻觉出
        # 以假乱真的"描述"（实测 kimi 对 base64=None 编出整段 UI）
        raise RuntimeError("empty image payload")
    payload = {
        "model": model.removeprefix("openai/"),
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": (
                "这是 Web 应用需求里的参考截图。请用中文结构化描述："
                "1) 整体布局分区；2) 导航/页头文案与链接；3) 表单控件、"
                "按钮文案与位置；4) 列表/卡片等数据元素与示例文字；"
                "5) 配色。只描述可见事实，禁止推测需求。")},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
        "max_tokens": 900,
    }
    r = httpx.post(f"{base}/chat/completions", json=payload,
                   headers={"Authorization": f"Bearer {key}"},
                   timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
    txt = (r.json().get("choices") or [{}])[0].get("message", {}).get("content")
    if not txt:
        raise RuntimeError("empty content")
    return str(txt).strip()


def _vision_endpoints(key: str, base: str) -> list[tuple[str, str, str]]:
    """视觉端点有序链：(model, base, key)。

    官方通道优先（gen-4 容器日志取证：平台注入 VISUAL_BASE_URL/
    VISUAL_MODEL=gpt-5.5 @ api.key7qi.com）——平台给的视觉端点
    用同一把注入 key；中转站 kimi-k3/minimax-m3 作兜底。
    """
    endpoints: list[tuple[str, str, str]] = []
    vbase = os.environ.get("VISUAL_BASE_URL", "").strip()
    vmodel = os.environ.get("VISUAL_MODEL", "").strip()
    if vbase and vmodel:
        endpoints.append((vmodel, vbase, key))
    for m in VISION_MODELS:
        model = m.removeprefix("openai/")
        if all(model != e[0] for e in endpoints):
            endpoints.append((model, base, key))
    return endpoints


def describe_images(req_dir: Path, refs: list[str],
                    key: str, base: str) -> dict[str, str]:
    """转写需求目录下引用的截图，返回 {相对路径: 描述}（带缓存）。"""
    req_dir = Path(req_dir)
    cache_path = req_dir / "_vision_cache.json"
    cache: dict[str, str] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    endpoints = _vision_endpoints(key, base)
    todo = [r for r in refs if r not in cache][: _MAX_IMAGES]
    # run5 尸检（Linux 容器）：20 图串行转写在旧实现里全程零打印、
    # 缓存只在末尾一次性落盘——中途被杀则数十次视觉调用全部白烧，
    # 且平台侧日志看不到任何进展。改为逐图落盘 + 逐图打印 + 总时限。
    import time as _time
    deadline = _time.monotonic() + float(
        os.environ.get("ARCBENCH_VISION_DEADLINE", "600"))
    for idx, ref in enumerate(todo, 1):
        if _time.monotonic() > deadline:
            print(f"[vision] 达总时限，{len(todo) - idx + 1} 图未转写"
                  "（已转写部分照常注入）", flush=True)
            break
        img = (req_dir / ref)
        if not img.is_file():          # 引用路径形如 ./reference/x.png
            img = req_dir / ref.lstrip("./")
        if not img.is_file():
            continue
        b64 = _downscale_b64(img)
        if b64 is None:
            continue
        for model, ebase, ekey in endpoints:
            try:
                cache[ref] = _describe_one(model, b64, ekey, ebase,
                                           timeout=90)
                break
            except Exception:
                continue               # 逐备胎，全败则该图无描述
        try:
            cache_path.write_text(
                json.dumps(cache, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except Exception:
            pass
        print(f"[vision] {idx}/{len(todo)} {ref} "
              f"{'ok' if ref in cache else 'FAIL'}", flush=True)
    try:
        cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=1),
            encoding="utf-8")
    except Exception:
        pass
    return {k: v for k, v in cache.items() if k in refs}


def render_image_section(descriptions: dict[str, str]) -> str:
    """描述字典 → 注入需求文本的 markdown 段落。"""
    if not descriptions:
        return ""
    lines = ["", "## 参考截图描述（视觉模型转写，UI 必须与此吻合）"]
    for ref, desc in descriptions.items():
        lines.append(f"### 截图 {ref}")
        lines.append(desc)
    return "\n".join(lines) + "\n"


def enrich_requirement(requirement: str, req_dir: Path, tree: dict,
                       key: str, base: str) -> str:
    """主入口：有图引用 → 转写并注入需求文本；无图/失败 → 原样返回。"""
    if os.environ.get("ARCBENCH_VISION", "on").lower() in ("off", "0", "false"):
        return requirement
    try:
        refs = find_image_refs(tree)
        if not refs:
            return requirement
        descriptions = describe_images(req_dir, refs, key, base)
        section = render_image_section(descriptions)
        if section:
            return requirement + section
    except Exception:
        return requirement
    return requirement
