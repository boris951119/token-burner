# -*- coding: utf-8 -*-
"""验收清单编译器：requirements.yaml → 逐节点可断言事实清单（零 LLM）。

交付前自评分环的地基：官方评测按需求文本的逐字文案/种子实体/入口控件
做精确断言（lite 双题 helpers 实证），这些事实全部可以从 YAML 机械
抽取——不需要 LLM"理解"，也不需要等官方评分才发现问题。

产出的 NodeChecklist 供三个消费方使用：
1. render_checklist_spec()：编译成 Playwright 静态断言 spec（首页可见
   类事实），本地判分逐 REQ 红绿；
2. 修复环：behavior_expectations（动作后断言）作为定向修复指令输入；
3. 生成期注入：种子/文案事实与 D 线契约模块（seed_contract /
   requirement_anchors）共享同一份抽取结果。

判定口径（通用规则，不含任何题目词汇）：
- 节点 GIVEN/WHEN 文案含 "home page"（或中文"首页"）→ 该节点事实
  在入口页静态可见，可编译成断言；否则标记导航后置，只入清单不判分
  （静态断言不可见实体=误红，会把修复环引向编造）。
- 引号串三通道：Seed data: 子句→种子实体；WHEN 引号→可操作控件；
  THEN 引号→期望文案。图片路径/文件名残渣一律剔除。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

_QUOTED_D = re.compile(r'"([^"\n]{1,80})"')
_QUOTED_S = re.compile(r"'([^'\n]{1,80})'")
_MD_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_SEED_LINE = re.compile(r"seed\s*data\s*:", re.I)
_FILE_RESIDUE = re.compile(
    r"\.(png|jpe?g|gif|svg|webp|ts|js|py|md|json|ya?ml|css|html)$", re.I)
_HOME_HINT = re.compile(r"home\s*page|homepage|首页", re.I)
# 凭据类种子（邮箱/密码/token）是登录输入值，不承诺页面可见——通用判据。
_CREDENTIAL_HINT = re.compile(r"@|password|passwd|token|secret", re.I)
_ENTRY_HINT = re.compile(
    r"entry\s*url|open\s+the\s+(application|app)|打开(应用|网站)", re.I)


@dataclass
class NodeChecklist:
    """一个 ATOMIC 节点的全部可断言事实。"""
    req_id: str
    req_name: str
    module_id: str
    language: str                      # en | zh | mixed（需求文字系别）
    home_visible: bool                 # 事实是否可在入口页静态断言
    seed_entities: list[str] = field(default_factory=list)
    control_labels: list[str] = field(default_factory=list)
    # 动作后期望文案（WHEN 操作产生的 snackbar/跳转等），静态判分不覆盖，
    # 供修复环做定向指令：
    behavior_expectations: list[str] = field(default_factory=list)
    scenarios: list[dict] = field(default_factory=list)   # 原 GWT steps

    def to_dict(self) -> dict:
        return asdict(self)


def _clean_quote(s: str) -> str | None:
    s = s.strip()
    if not s or _FILE_RESIDUE.search(s):
        return None
    if _SEED_LINE.search(s) or len(s.split()) > 12:
        return None                     # 描述残渣/整句，不是 UI 文案
    return s


def _quotes_in(text: str, *, skip_seed_clause: bool = False) -> list[str]:
    """抽一段文本里的引号文案（双/单引号），剔图片与文件名。"""
    if not text:
        return []
    body = _MD_IMG.sub("", text)
    out: list[str] = []
    for m in _QUOTED_D.finditer(body):
        q = _clean_quote(m.group(1))
        if q:
            out.append(q)
    # 单引号通道：仅在无跳过需求时补（WHEN/THEN 主体），seed 通道自行去重
    if not skip_seed_clause:
        for m in _QUOTED_S.finditer(body):
            q = _clean_quote(m.group(1))
            if q and q not in out:
                out.append(q)
    return out


def _seed_entities_of(description: str) -> list[str]:
    """description 内 Seed data: 子句之后的引号名（与 seed_contract 同法）。"""
    out: list[str] = []
    for m in _SEED_LINE.finditer(description or ""):
        rest = description[m.end():]
        cut = rest.find("\n")
        if cut >= 0:
            rest = rest[:cut]
        for q in _QUOTED_D.finditer(_MD_IMG.sub("", rest)):
            n = _clean_quote(q.group(1))
            if n and n not in out:
                out.append(n)
    return out


def load_yaml_robust(path: Path) -> dict:
    """官方题面 YAML 是外部输入，实测存在多缩进硬伤（9/22 webapp 副本：
    description 比同级 type 多 4 空格、steps content 比同组多 4 空格 →
    ScannerError）。策略：让 PyYAML 报错定位坏行，逐行把该行缩进回退到
    同块兄弟基准（前一行是 '- ' 序列项则 +2，否则取前一行缩进），循环
    直至解析成功或无可进展（上限 400 次）。永不猜改正常行。"""
    import yaml

    text = path.read_text(encoding="utf-8")
    seen: set[tuple[int, int]] = set()
    for _ in range(400):
        try:
            data = yaml.safe_load(text)
            return data if isinstance(data, dict) else {}
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            if mark is None:
                return {}
            lines = text.split("\n")
            i = int(mark.line)
            if i >= len(lines):
                return {}
            cur = lines[i]
            cur_ind = len(cur) - len(cur.lstrip())
            j = i - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            if j < 0:
                return {}
            prev = lines[j]
            prev_ind = len(prev) - len(prev.lstrip())
            if cur_ind <= prev_ind:
                return {}          # 损伤不在缩进层级，交空降级
            new_ind = (prev_ind + 2 if prev.lstrip().startswith("-")
                       else prev_ind)
            if (i, cur_ind) in seen or cur_ind == new_ind:
                return {}          # 无进展，防死循环
            seen.add((i, cur_ind))
            lines[i] = " " * new_ind + cur.lstrip()
            text = "\n".join(lines)
    return {}


def compile_checklists(yaml_path: Path) -> list[NodeChecklist]:
    """requirements.yaml → 逐 ATOMIC 节点验收清单（文档序）。"""
    data = load_yaml_robust(Path(yaml_path))
    if not data:
        return []
    return _walk_tree(data)


def _walk_tree(root: dict) -> list[NodeChecklist]:
    out: list[NodeChecklist] = []

    def walk(node: dict, module_id: str) -> None:
        for child in node.get("children") or []:
            cid = str(child.get("id") or "")
            if child.get("type") == "FOLDER":
                walk(child, cid or module_id)
                continue
            out.append(_build_node(child, module_id))
            walk(child, module_id)   # ATOMIC 下挂子节点的题目形态也兼容

    walk(root, str(root.get("id") or "ROOT"))
    return out


def _build_node(child: dict, module_id: str) -> NodeChecklist:
    from app.utils.ui_language import requirement_language

    desc = str(child.get("description") or "")
    name = str(child.get("name") or "")
    scenarios = child.get("scenarios") or []
    steps_text_all = [desc, name]
    home_visible = bool(_HOME_HINT.search(desc) or _ENTRY_HINT.search(desc))
    behavior: list[str] = []
    controls: list[str] = []
    for sc in scenarios:
        for s in sc.get("steps") or []:
            kw = str(s.get("keyword") or "").upper()
            content = str(s.get("content") or "")
            steps_text_all.append(content)
            if kw in ("GIVEN", "WHEN"):
                if _HOME_HINT.search(content) or _ENTRY_HINT.search(content):
                    home_visible = True
                if kw == "WHEN":
                    for q in _quotes_in(content):
                        if q not in controls:
                            controls.append(q)
            elif kw == "THEN":
                for q in _quotes_in(content):
                    if q not in behavior:
                        behavior.append(q)
    seeds = [s for s in _seed_entities_of(desc) if not _CREDENTIAL_HINT.search(s)]
    # THEN 里复述的种子名不算行为断言（它们由 seed 通道静态覆盖）
    behavior = [b for b in behavior if b not in seeds and b not in controls]
    full_text = "\n".join(steps_text_all)
    return NodeChecklist(
        req_id=str(child.get("id") or ""),
        req_name=name,
        module_id=module_id,
        language=requirement_language(full_text),
        home_visible=home_visible,
        seed_entities=seeds,
        control_labels=controls,
        behavior_expectations=behavior,
        scenarios=[dict(s) for s in scenarios],
    )


# ---------------------------------------------------------------- 渲染器

def _ts_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


_SPEC_HELPERS = """\
import { test, expect } from '@playwright/test';

// token-burner 编译期验收清单（acceptance_compile 生成，零 LLM）。
// CHK-SEED：需求逐字种子实体须在入口一跳可达页面出现；
// CHK-CTRL：WHEN 引用的控件文案须在入口一跳可达页面出现。

type LocatorFactory = (p: import('@playwright/test').Page) => any;

async function visibleOnReachable(page: import('@playwright/test').Page,
                                  make: LocatorFactory): Promise<boolean> {
  try { await page.goto('/', { timeout: 8000 }); } catch { return false; }
  if (await make(page).first().isVisible().catch(() => false)) return true;
  let hrefs: string[] = [];
  try {
    hrefs = await page.evaluate(() => Array.from(
      document.querySelectorAll('a[href]')).map(a => a.getAttribute('href') || ''));
  } catch { return false; }
  const tried = new Set<string>();
  for (const raw of hrefs) {
    if (!raw || raw.startsWith('http') || raw.startsWith('//') ||
        raw.startsWith('mailto') ||
        raw.startsWith('#') || raw.startsWith('javascript')) continue;
    const path = (raw.startsWith('/') ? raw : '/' + raw)
      .split('?')[0].split('#')[0];
    if (path === '/' || tried.has(path)) continue;
    tried.add(path);
    if (tried.size > 16) break;
    try { await page.goto(path, { timeout: 5000 }); } catch { continue; }
    if (await make(page).first().isVisible().catch(() => false)) return true;
  }
  return false;
}
"""


def render_checklist_spec(checklists: list[NodeChecklist]) -> str:
    """home_visible 节点 → 自包含 Playwright 静态断言 spec（无 helpers 依赖）。

    每个断言独立成 test（标题带 REQ id），逐条红绿可直接喂节点级修复。
    判定范围：入口页 + 从入口页 <a href> 一跳可达的同站页面（上限 16），
    命中任意一页即通过——种子/控件常挂在列表页或表单页而非首页。
    """
    blocks: list[str] = []
    for ck in checklists:
        if not ck.home_visible:
            continue
        for ent in ck.seed_entities:
            blocks.append(
                f"  test('{ck.req_id} CHK-SEED: {_ts_str(ent)}', async "
                "({ page }) => {\n"
                f"    const found = await visibleOnReachable(page, "
                f"p => p.getByText({_ts_str(ent)}, {{ exact: true }}));\n"
                f"    expect(found, {_ts_str('入口一跳内未见: ' + ent)}"
                ").toBe(true);\n"
                "  });")
        for lab in ck.control_labels:
            blocks.append(
                f"  test('{ck.req_id} CHK-CTRL: {_ts_str(lab)}', async "
                "({ page }) => {\n"
                "    const found = await visibleOnReachable(page, p =>\n"
                "      p.getByText(" + _ts_str(lab) + ", { exact: true })\n"
                "        .or(p.getByPlaceholder(" + _ts_str(lab) + "))\n"
                "        .or(p.getByLabel(" + _ts_str(lab) + "))\n"
                "        .or(p.getByRole('button', { name: " + _ts_str(lab)
                + ", exact: true })));\n"
                f"    expect(found, {_ts_str('入口一跳内未见控件: ' + lab)}"
                ").toBe(true);\n"
                "  });")
    body = "\n".join(blocks)
    return (
        _SPEC_HELPERS
        + "\ntest.describe('compiled acceptance checklist', () => {\n"
        + body + "\n});\n"
    )


def to_json(checklists: list[NodeChecklist]) -> str:
    return json.dumps([c.to_dict() for c in checklists],
                      ensure_ascii=False, indent=1)
