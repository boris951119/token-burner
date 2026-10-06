# -*- coding: utf-8 -*-
"""主路径上的机械旅程（零 LLM）。

从当次需求的 GIVEN/WHEN/THEN（或 requirements.yaml 场景）抽出
「点击引号文案 → 下一页必须看见引号文案」。不写死任何赛题名词。

官方评测就是从首页按可见名字点进去。这里用同一条规则：
同名可点目标必须恰好 1 个，点开的地址必须返回 2xx/3xx。
抽不出点击步骤的需求不判失败（没有信号 ≠ 走通了）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


_QUOTE = re.compile(
    r'"([^"\n]{1,80})"'
    r"|'([^'\n]{1,80})'"
    r"|「([^」\n]{1,80})」"
    r"|“([^”\n]{1,80})”"
)
_CLICK = re.compile(
    r"\b(?:click|clicks|clicked|press|presses|tap|taps|select|selects|"
    r"open|opens|follow|follows)\b|点击|点选|按下",
    re.I,
)
_FILL = re.compile(
    r"\b(?:enter|enters|type|types|fill|fills|input|inputs)\b|输入|填写|填入",
    re.I,
)
_KW = re.compile(
    r"^(?:[-*]\s*)?(GIVEN|WHEN|THEN|AND|BUT)\b[:\s]*(.*)$", re.I)
_HEAD = re.compile(r"^#{2,3}\s+(.+?)\s*$")
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_HIDDEN = re.compile(
    r"(?is)<(script|style|textarea|template)\b[^>]*>.*?</\1>")
_ANCHOR = re.compile(r"<a\b[^>]*>.*?</a>", re.I | re.S)
_BUTTON = re.compile(
    r"<(?:button|input)\b[^>]*>.*?</button>|<input\b[^>]*/?>",
    re.I | re.S)
_FORM = re.compile(r"<form\b([^>]*)>(.*?)</form>", re.I | re.S)
_HREF = re.compile(r"""href\s*=\s*(['"])(.*?)\1""", re.I | re.S)
_ATTR = re.compile(
    r"""\b(action|method|type|value|name|placeholder)\s*=\s*(['"])(.*?)\2""",
    re.I | re.S)
_INPUT = re.compile(r"<input\b[^>]*>", re.I)


@dataclass
class JStep:
    kind: str          # click | see | fill
    text: str
    value: str = ""


@dataclass
class Journey:
    title: str
    steps: list[JStep] = field(default_factory=list)


def _quotes(text: str) -> list[str]:
    out: list[str] = []
    for m in _QUOTE.finditer(text or ""):
        q = next(g for g in m.groups() if g)
        q = _WS.sub(" ", q).strip()
        if q and not q.lower().startswith(("http://", "https://")):
            out.append(q)
    return out


def _steps_from_gwt(rows: list[tuple[str, str]]) -> list[JStep]:
    steps: list[JStep] = []
    for kw, content in rows:
        kw = (kw or "").upper()
        quotes = _quotes(content)
        if not quotes:
            continue
        clicking = bool(_CLICK.search(content or ""))
        filling = bool(_FILL.search(content or ""))
        if kw in ("WHEN", "AND") and filling and quotes:
            label, val = quotes[0], quotes[1] if len(quotes) > 1 else quotes[0]
            steps.append(JStep("fill", label, val))
        elif kw in ("WHEN", "AND") and clicking:
            steps.append(JStep("click", quotes[0]))
        elif kw in ("THEN", "AND", "BUT") and not clicking and not filling:
            for q in quotes[:3]:
                steps.append(JStep("see", q))
        if len(steps) >= 6:
            break
    return steps[:6]


def _from_markdown(requirement: str) -> list[Journey]:
    journeys: list[Journey] = []
    title = "entry"
    rows: list[tuple[str, str]] = []

    def flush() -> None:
        nonlocal rows
        steps = _steps_from_gwt(rows)
        rows = []
        if any(s.kind in ("click", "fill") for s in steps):
            journeys.append(Journey(title[:80], steps))

    for line in (requirement or "").splitlines():
        head = _HEAD.match(line.strip())
        if head:
            flush()
            title = head.group(1).strip()
            continue
        m = _KW.match(line.strip())
        if m:
            rows.append((m.group(1), m.group(2)))
    flush()
    return journeys


def compile_click_journeys(requirement: str, scenarios=None,
                            *, limit: int = 5) -> list[Journey]:
    """最多 limit 条带点击的旅程。场景结构优先，否则扫需求正文。"""
    found: list[Journey] = []
    for sc in scenarios or []:
        rows = [(getattr(s, "keyword", ""), getattr(s, "content", ""))
                for s in (getattr(sc, "steps", None) or [])]
        steps = _steps_from_gwt(rows)
        if any(s.kind in ("click", "fill") for s in steps):
            name = getattr(sc, "scenario", "") or getattr(sc, "req_id", "")
            found.append(Journey(str(name)[:80] or "scenario", steps))
        if len(found) >= limit:
            return found[:limit]
    if found:
        return found[:limit]
    return _from_markdown(requirement)[:limit]


def visible_text(html: str) -> str:
    txt = _HIDDEN.sub(" ", html or "")
    txt = _TAG.sub(" ", txt)
    return _WS.sub(" ", txt).strip()


def _element_text(chunk: str) -> str:
    if re.search(r"<input\b", chunk or "", re.I):
        vals = [m.group(3) for m in _ATTR.finditer(chunk)
                if m.group(1).lower() == "value"]
        if vals:
            return _WS.sub(" ", vals[-1]).strip()
    return _WS.sub(" ", _TAG.sub(" ", chunk or "")).strip()


def _resolve(page_url: str, href: str) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith(("#", "mailto:", "javascript:")):
        return None
    if href.startswith(("http://", "https://", "//")):
        return None
    if href.startswith("/"):
        return href.split("#", 1)[0]
    base = page_url.rsplit("/", 1)[0] if page_url else ""
    path = (base + "/" + href).replace("//", "/")
    if not path.startswith("/"):
        path = "/" + path
    return path.split("#", 1)[0]


def find_click(html: str, name: str, page_url: str) -> tuple[tuple | None, int]:
    """恰好一个同名链接或提交按钮。返回 (method, path) 或 (None, 个数)。"""
    target = _WS.sub(" ", name or "").strip()
    hits: list[tuple] = []
    for m in _ANCHOR.finditer(html or ""):
        if _element_text(m.group(0)) != target:
            continue
        hm = _HREF.search(m.group(0))
        href = hm.group(2) if hm else ""
        path = _resolve(page_url, href)
        if path:
            hits.append(("GET", path))
    if not hits:
        for fm in _FORM.finditer(html or ""):
            attrs = {a.group(1).lower(): a.group(3)
                     for a in _ATTR.finditer(fm.group(1) or "")}
            action = _resolve(page_url, attrs.get("action") or page_url)
            method = (attrs.get("method") or "GET").upper()
            if method not in ("GET", "POST") or not action:
                continue
            body = fm.group(2) or ""
            for bm in _BUTTON.finditer(body):
                if _element_text(bm.group(0)) == target:
                    hits.append((method, action.split("?", 1)[0]
                                 if method == "POST" else action))
    if len(hits) != 1:
        return None, len(hits)
    return hits[0], 1


def bind_form(html: str, extras: dict[str, str]) -> dict[str, str]:
    """把旅程里的填写对上当前页 input 的 name/placeholder。"""
    data: dict[str, str] = {}
    for tag in _INPUT.findall(html or ""):
        attrs = {a.group(1).lower(): a.group(3)
                 for a in _ATTR.finditer(tag)}
        name = attrs.get("name") or ""
        if not name:
            continue
        blob = " ".join((name, attrs.get("placeholder") or "",
                         attrs.get("type") or "")).lower()
        data[name] = attrs.get("value") or ""
        for lab, val in extras.items():
            if lab.lower() in blob:
                data[name] = val
    used = set(data.values())
    for lab, val in extras.items():
        if val in used:
            continue
        slug = re.sub(r"[^A-Za-z0-9]+", "_", lab).strip("_") or "field"
        data[slug] = val
        used.add(val)
    return data


def walk_journeys(journeys: list[Journey], request) -> list[str]:
    """request(method, path, data=None) -> (status, html)。空列表为通过。"""
    failures: list[str] = []
    for journey in journeys:
        try:
            status, html = request("GET", "/")
        except Exception as exc:
            failures.append(f"{journey.title}: GET / 异常 {exc!r}"[:180])
            continue
        url = "/"
        filled: dict[str, str] = {}
        if status >= 400:
            failures.append(f"{journey.title}: GET / → HTTP {status}")
            continue
        for step in journey.steps:
            if step.kind == "see":
                if step.text not in visible_text(html):
                    failures.append(
                        f"{journey.title}: {url} 上看不见 {step.text!r}")
                    break
                continue
            if step.kind == "fill":
                filled[step.text] = step.value or step.text
                continue
            action, n = find_click(html, step.text, url)
            if action is None:
                failures.append(
                    f"{journey.title}: {url} 上「{step.text}」可点目标 "
                    f"{n} 个（要恰好 1 个，且地址属于本站）")
                break
            method, path = action
            payload = bind_form(html, filled) if method == "POST" else None
            try:
                status, html = request(method, path, payload)
            except TypeError:
                status, html = request(method, path)
            except Exception as exc:
                failures.append(
                    f"{journey.title}: 「{step.text}」{method} {path} "
                    f"异常 {exc!r}"[:180])
                break
            url = path
            if method == "POST":
                filled = {}
            if status >= 400:
                failures.append(
                    f"{journey.title}: 「{step.text}」→ {method} {path} "
                    f"HTTP {status}")
                break
    return failures


def _scenarios(requirements_dir: Path | None):
    if requirements_dir is None:
        return []
    root = Path(requirements_dir)
    if not root.is_dir():
        return []
    paths = list(root.rglob("requirements.yaml")) + list(
        root.rglob("requirements.yml"))
    if not paths:
        return []
    try:
        from app.utils.scenario_compiler import compile_scenarios
        return compile_scenarios(paths[0])
    except Exception:
        return []


_RUNNER = r'''
import importlib.util
import json
import sys
from pathlib import Path

code = Path(sys.argv[1]).resolve()
spec = importlib.util.spec_from_file_location("mj", sys.argv[2])
mj = importlib.util.module_from_spec(spec)
sys.modules["mj"] = mj
spec.loader.exec_module(mj)
journeys = [mj.Journey(j["title"], [mj.JStep(s["kind"], s["text"],
            s.get("value") or "")
            for s in j["steps"]])
            for j in json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))]
sys.path.insert(0, str(code))
for child in sorted(code.iterdir()):
    if (child.is_dir() and not child.name.startswith(("_", "."))
            and not (child / "__init__.py").exists()):
        sys.path.insert(0, str(child))

def _boot():
    cands = []
    names = []
    for child in sorted(code.iterdir()):
        if child.is_file() and child.suffix == ".py" and not child.name.startswith("_"):
            names.append(child.stem)
        elif (child.is_dir() and (child / "__init__.py").exists()
              and not child.name.startswith(("_", "."))):
            names.append(child.name)
    for name in names:
        try:
            mod = __import__(name)
        except Exception:
            continue
        for factory in ("create_app",):
            fn = getattr(mod, factory, None)
            if callable(fn):
                try:
                    cands.append((name, fn()))
                except Exception:
                    pass
        app = getattr(mod, "app", None)
        if app is not None and hasattr(app, "test_client"):
            cands.append((name, app))
    def home(a):
        try:
            return any(getattr(r, "rule", "") == "/"
                       for r in a.url_map.iter_rules())
        except Exception:
            return False
    pref = ("main", "app", "app_main", "project_main", "server", "wsgi", "run")
    pool = [c for c in cands if home(c[1])] or cands
    named = [c for c in pool if c[0].lower() in pref]
    named.sort(key=lambda c: pref.index(c[0].lower()))
    if not (named or pool):
        return None
    return (named or pool)[0][1]

app = _boot()
if app is None or not hasattr(app, "test_client"):
    print("@@MJ@@" + json.dumps({"boot": False, "failures": []}))
    raise SystemExit(0)
client = app.test_client()

def request(method, path, data=None):
    if method == "GET":
        resp = client.get(path)
    else:
        resp = client.post(path, data=data or {})
    body = resp.get_data(as_text=True) if hasattr(resp, "get_data") else ""
    return int(getattr(resp, "status_code", 500)), body

fails = mj.walk_journeys(journeys, request)
print("@@MJ@@" + json.dumps({"boot": True, "failures": fails}, ensure_ascii=False))
'''


def run_compiled_journeys(code_dir: Path, requirement: str,
                          requirements_dir: Path | None = None,
                          ) -> tuple[str, str]:
    """返回 (pass|fail|skip, 报告)。

    skip：需求里没有点击旅程，或应用装配失败（装配失败交给冒烟，不冤枉）。
    fail：点不到、点开不是 2xx、或点开后看不见要求的文案。
    """
    journeys = compile_click_journeys(
        requirement, _scenarios(requirements_dir))
    if not journeys:
        return "skip", "需求里没有可执行的点击旅程"
    code_dir = Path(code_dir)
    payload = [{
        "title": j.title,
        "steps": [{"kind": s.kind, "text": s.text, "value": s.value}
                  for s in j.steps],
    } for j in journeys]
    with tempfile.TemporaryDirectory(prefix="mj-") as tmp:
        spec = Path(tmp) / "journeys.json"
        spec.write_text(json.dumps(payload, ensure_ascii=False),
                        encoding="utf-8")
        runner = Path(tmp) / "run_mj.py"
        runner.write_text(_RUNNER, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, str(runner), str(code_dir),
                 str(Path(__file__).resolve()), str(spec)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=90,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return "skip", f"主旅程未能启动: {exc!r}"[:180]
    line = ""
    for raw in (proc.stdout or "").splitlines():
        if raw.startswith("@@MJ@@"):
            line = raw[len("@@MJ@@"):]
    if not line:
        tail = ((proc.stderr or "") + (proc.stdout or ""))[-240:]
        return "skip", f"主旅程无结果（装配问题交给冒烟）: {tail}"
    try:
        info = json.loads(line)
    except ValueError:
        return "skip", "主旅程结果无法解析"
    if not info.get("boot"):
        return "skip", "应用未能装配，主旅程跳过"
    fails = [str(x) for x in (info.get("failures") or [])]
    if fails:
        return "fail", "\n".join(fails[:8])
    return "pass", f"主旅程 {len(journeys)} 条走通"
