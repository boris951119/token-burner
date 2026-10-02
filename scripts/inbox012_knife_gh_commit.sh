#!/usr/bin/env bash
# INBOX-012 刀G + 刀H：pytest → 两独立 commit（不 push）
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif [[ -x .venv/bin/python ]]; then
  PY=.venv/bin/python
else
  PY=python3
fi

echo "== targeted pytest =="
"$PY" -m pytest tests/test_v53_ui_route_landing.py \
  tests/test_v53_ownership_bp.py tests/test_abcd_coverage.py -q --tb=short

echo "== full pytest =="
set +e
FULL="$("$PY" -m pytest -q --tb=line 2>&1 | tee /tmp/inbox012-full-pytest.log)"
RC=$?
set -e
echo "$FULL" | tail -5
if [[ $RC -ne 0 ]]; then
  echo "full pytest failed (exit $RC); abort commit" >&2
  exit "$RC"
fi
SUMMARY="$(echo "$FULL" | tail -1)"

echo "== patch outbox G receipt (pytest green) =="
export SUMMARY
"$PY" - <<'PY'
from pathlib import Path
import os
summary = os.environ.get("SUMMARY", "")
outbox = Path("docs/agent-outbox.md")
text = outbox.read_text(encoding="utf-8")
marker = "### 测试 / 纪律\n- 回归：`tests/test_v53_ui_route_landing.py`（刀G）"
if marker in text:
    start = text.index("## INBOX-012 施工回执·刀G")
    # replace the 测试/纪律 section inside G receipt only
    g_end = text.find("\n---\n", start)
    if g_end < 0:
        g_end = len(text)
    head, mid, tail = text[:start], text[start:g_end], text[g_end:]
    import re
    mid2 = re.sub(
        r"### 测试 / 纪律\n[\s\S]*?(?=\Z)",
        "### 测试 / 纪律\n"
        f"- `tests/test_v53_ui_route_landing.py`（刀G）+ ownership/coverage 套件绿；"
        f"全量 pytest：{summary}\n"
        "- **本提交**（`fix(v53): knife G reroute UI-flow REQs off core/data/seed modules`）；"
        "独立判读见本页专节。\n"
        "- 未 push；未动 `.env`；未上平台。\n",
        mid,
        count=1,
    )
    outbox.write_text(head + mid2 + tail, encoding="utf-8")
    print("outbox G receipt updated")
else:
    print("outbox G receipt already updated or text drifted; continue")
PY

echo "== commit 1 (刀G) =="
git status
git diff --stat
git log -3 --oneline
git add app/utils/atomic_coverage.py docs/agent-outbox.md
git commit -m "$(cat <<'EOF'
fix(v53): knife G reroute UI-flow REQs off core/data/seed modules

EOF
)"
SHA_G="$(git rev-parse HEAD)"
echo "commit G: $SHA_G"

echo "== stage 刀H outbox + inbox (commit 2 docs) =="
export SHA_G
"$PY" - <<'PY'
import os
from pathlib import Path

sha_g = os.environ["SHA_G"]
outbox = Path("docs/agent-outbox.md")
text = outbox.read_text(encoding="utf-8")
row = (
    "| 09-28 02:06 | **INBOX-012 刀H 完工** | 见下方「INBOX-012 施工回执·刀H」；"
    "manifest landing 写码门禁（本提交） |\n"
)
needle = "| 09-28 02:05 | **INBOX-012 刀G 完工**"
if row.strip() not in text and needle in text:
    parts = text.split(needle, 1)
    if len(parts) == 2:
        rest = parts[1]
        nl = rest.find("\n")
        if nl >= 0:
            text = parts[0] + needle + rest[: nl + 1] + row + rest[nl + 1 :]

if "INBOX-012 施工回执·刀H" not in text:
    text = text.rstrip() + f"""

---

## INBOX-012 施工回执·刀H（待 ZCode 复审）

| 刀 | commit | 要点 |
|---|---|---|
| 刀G | `{sha_g[:7]}` | UI 流程 REQ 重路由 off core/data/seed |
| 刀H | （本提交） | `manifest_landing` 锚点 ≥4 且命中 <50% → dev_loop 硬红 |

### 刀H：契约锚点文案落地门禁
- `app/utils/manifest_landing.py`：`extract_manifest_anchors` + `check_manifest_landing`（清单行顿号枚举 + 引号控件）。
- `dev_loop`：link/arity/collision 通过后挂文案落地门禁；缺失逐条进 `failure_report`；resume 从 modules/*.md 回读职责。
- 验收：`tests/test_v53_ui_route_landing.py` 刀H（幻觉 chrome → 红；六件套在场 → 绿；锚点 <4 跳过）。

### 测试 / 纪律
- 刀G+刀H 相关套件 + 全量 pytest 绿。
- **本提交**（`fix(v53): knife H manifest landing gate for contract anchor copy`）。
- 未 push；未动 `.env`；未上平台。
"""
outbox.write_text(text, encoding="utf-8")

inbox = Path("docs/agent-inbox.md")
it = inbox.read_text(encoding="utf-8")
it = it.replace(
    "## INBOX-012（open，2026-09-28 00:3x，ZCode→Cursor）— github 尸检同步分析 + 刀G/刀H 施工",
    "## INBOX-012（done 2026-09-28 02:0x，Cursor 刀G+刀H 落地，待 ZCode 复审）",
    1,
)
inbox.write_text(it, encoding="utf-8")
print("docs updated for commit 2")
PY

echo "== commit 2 (刀H) =="
git status
git diff --stat
git log -3 --oneline
git add app/utils/manifest_landing.py app/agents/dev_loop.py \
  tests/test_v53_ui_route_landing.py docs/agent-outbox.md docs/agent-inbox.md \
  scripts/inbox012_knife_gh_commit.sh
git commit -m "$(cat <<'EOF'
fix(v53): knife H manifest landing gate for contract anchor copy

EOF
)"
SHA_H="$(git rev-parse HEAD)"
echo "commit H: $SHA_H"
git status
echo "DONE G=$SHA_G H=$SHA_H summary=$SUMMARY (no push)"
