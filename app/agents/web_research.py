"""M10-5 联网调研通道（可配置供应商，缺省关闭）。

职责边界（总则 D）：本模块只做确定性抓取与拼接——搜索请求、
结果解析、资料文本拼装全部是程序行为，零 LLM 参与；
结构化摘要仍由 Researcher.generate_brief（LLM 决策）完成。

降级链路（单一方向）：联网失败 → 返回空串 → 管线回退用户资料
注入模式（researcher 降级版原有链路），任务不阻塞。

不可信治理：抓取文本统一走 sanitize_untrusted（M7-6 同构），
包裹发生在 Researcher._one_pass（资料入口统一治理点）。
"""

from __future__ import annotations

import html as _html
import json
import re
import urllib.parse
import urllib.request

from app.config import Settings

_UA = "Mozilla/5.0 (token-burner research; +https://github.com/boris951119/token-burner)"

# DuckDuckGo HTML 版结果条目（免 key 通道；轻量正则解析，结构变化即回退）
_DDG_RESULT = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.S,
)
_DDG_SNIPPET = re.compile(
    r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.S,
)


def _strip_tags(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw)
    return _html.unescape(text).strip()


def _http_get(url: str, timeout: int) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _http_post_json(url: str, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"User-Agent": _UA, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def parse_ddg_results(page: str, limit: int) -> list[dict]:
    """解析 DuckDuckGo HTML 结果页 → [{title, url, snippet}]。"""
    links = _DDG_RESULT.findall(page)
    snippets = [_strip_tags(s) for s in _DDG_SNIPPET.findall(page)]
    out: list[dict] = []
    for i, (url, title) in enumerate(links[:limit]):
        out.append({
            "title": _strip_tags(title),
            "url": url,
            "snippet": snippets[i] if i < len(snippets) else "",
        })
    return out


def search_duckduckgo(query: str, settings: Settings) -> list[dict]:
    page = _http_get(
        "https://html.duckduckgo.com/html/?q="
        + urllib.parse.quote(query),
        settings.research_web_timeout,
    )
    return parse_ddg_results(page, settings.research_web_max_results)


def search_tavily(query: str, settings: Settings) -> list[dict]:
    import os

    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return []
    data = _http_post_json(
        "https://api.tavily.com/search",
        {"api_key": key, "query": query,
         "max_results": settings.research_web_max_results},
        settings.research_web_timeout,
    )
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""),
         "snippet": r.get("content", "")}
        for r in data.get("results", [])
    ]


_PROVIDERS = {"duckduckgo": search_duckduckgo, "tavily": search_tavily}


def render_material(results: list[dict]) -> str:
    """搜索结果 → 可注入的调研资料文本（确定性拼装）。"""
    blocks = []
    for r in results:
        blocks.append(
            f"### {r.get('title', '')}\n来源: {r.get('url', '')}\n"
            f"{r.get('snippet', '')}"
        )
    return "\n\n".join(blocks)


def fetch_web_material(
    query: str, settings: Settings, search_fn=None
) -> str:
    """联网搜索并拼装调研资料；任何失败返回空串（回退资料注入）。

    Args:
        query: 搜索词（陌生技术栈标注/需求关键词）。
        search_fn: 测试注入点；缺省按 settings.research_web_provider 分发。
    """
    if not settings.researcher_web_enabled:
        return ""
    provider = settings.research_web_provider
    fn = search_fn or _PROVIDERS.get(provider)
    if fn is None:
        return ""
    try:
        results = fn(query, settings)
        if not results:
            return ""
        return render_material(results)
    except Exception:  # noqa: BLE001  降级链路：联网失败回退资料注入
        return ""
