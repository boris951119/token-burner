#!/usr/bin/env bash
# v56：位置级断言五刀（INBOX-014 更优方案 1-5）
# 用法（仓库根）： bash scripts/v56_commit_five.sh
# 纪律：相关套件 → 全量 pytest≥1972 → 按文件边界独立 commit + outbox 回执
# 不 push / 不动 .env / 不上平台 / 不用 --no-verify
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"
export PYTHONUNBUFFERED=1

stamp() { date '+%m-%d %H:%M'; }
TS="$(stamp)"

echo "===== git preflight ====="
git status -sb
git log -5 --oneline

echo "===== targeted pytest ====="
$PY -m pytest \
  tests/test_acceptance_compile.py \
  tests/test_v53_ui_route_landing.py \
  tests/test_v53_ownership_bp.py \
  tests/test_interface_check.py \
  tests/test_repo_fixer_baseline.py \
  tests/test_v45_knives.py \
  -q --tb=short | tee /tmp/v56-targeted.txt

echo "===== full pytest ====="
$PY -m pytest -q --tb=line | tee /tmp/v56-full.txt
FULL_LINE=$(tail -n 1 /tmp/v56-full.txt)
echo "FULL_SUMMARY: $FULL_LINE"
PASSED=$(echo "$FULL_LINE" | python3 -c "import sys,re;m=re.search(r'(\d+) passed',sys.stdin.read());print(m.group(1) if m else 0)")
if [[ -z "${PASSED}" ]] || [[ "${PASSED}" -lt 1972 ]]; then
  echo "FAIL: expected ≥1972 passed, got: ${FULL_LINE}"
  exit 1
fi

echo "===== Commit A: v56-1+2 acceptance_compile（同文件）====="
git add app/acceptance_compile.py tests/test_acceptance_compile.py
git commit -m "$(cat <<'EOF'
v56-1/2: 自测同构 + 编译期 surface 标签（位置级断言）

EOF
)"
HA=$(git rev-parse --short HEAD)

echo "===== Commit B: v56-3+4 HTML 闸 + 刀H 降噪 ====="
git add \
  app/utils/manifest_landing.py \
  app/arcbench_smoke.py \
  app/pipeline.py \
  tests/test_v53_ui_route_landing.py
git commit -m "$(cat <<'EOF'
v56-3/4: 首页路由 HTML 闸 + 刀H 锚点降噪与黑名单

EOF
)"
HB=$(git rev-parse --short HEAD)

echo "===== Commit C: v56-5 _bp 工厂门禁 ====="
git add \
  app/utils/blueprint_convention.py \
  app/utils/interface_check.py \
  tests/test_v53_ownership_bp.py \
  tests/test_interface_check.py
git commit -m "$(cat <<'EOF'
v56-5: _bp 门禁认顶层 Blueprint 或可调用工厂

EOF
)"
HC=$(git rev-parse --short HEAD)

echo "===== outbox 回执 ====="
export TS HA HB HC PASSED FULL_LINE
python3 - <<'PY'
import os
from pathlib import Path
p = Path("docs/agent-outbox.md")
text = p.read_text(encoding="utf-8")
ts, ha, hb, hc = os.environ["TS"], os.environ["HA"], os.environ["HB"], os.environ["HC"]
passed = os.environ["PASSED"]
rows = f"""| {ts} | **v56-1 自测同构** | behavior 进 spec；home 只 GET /；editor 先点种子；废除 visibleOnReachable。commit=`{ha}`（与 v56-2 同文件） |
| {ts} | **v56-2 surface 标签** | fact_surfaces + 首页卡片须含/编辑页须含。commit=`{ha}` |
| {ts} | **v56-3 运行时 HTML 闸** | check_home_route_html + sidecar；冒烟 GET / 主闸；外科补字段指令。commit=`{hb}` |
| {ts} | **v56-4 刀H 降噪** | 锚点改刀C 逐字清单；placeholder/boolish/CJK OCR 黑名单；源码 grep 辅闸。commit=`{hb}` |
| {ts} | **v56-5 _bp 工厂** | convention+interface 认 Blueprint 别名 / def _bp() 工厂。commit=`{hc}` |
"""
anchor = "| 09-28 18:5x | **INBOX-014"
if "v56-1 自测同构" not in text and anchor in text:
    lines = text.splitlines(keepends=True)
    out, inserted = [], False
    for ln in lines:
        out.append(ln)
        if (not inserted) and ln.startswith(anchor):
            out.append(rows)
            inserted = True
    text = "".join(out)
summary = f"""

---

## v56 五刀施工回执（{ts}，INBOX-014 更优方案 1–5）

### v56-1 自测同构（最高 ROI）
- `render_checklist_spec` 纳入 `behavior_expectations`（含 desc 模板前缀如 Last updated）。
- surface=home / `home_visible`：只断言 `GET /`（`visibleOnHome` / `visibleControlOnHome`）。
- surface=editor：`visibleAfterSeedClick`（先点种子链接再断言）。
- **废除** `visibleOnReachable` 一跳任意页假绿。

### v56-2 编译期 surface 标签
- `_facts` 抽引号时按同一句内最近页短语打 `fact_surfaces`（home|editor|dialog|unknown）；双句双标签。
- `render_ux_checklist` 写成「首页卡片须含 / 编辑页须含 / 对话框须含」。

### v56-3 运行时路由 HTML 闸
- `manifest_landing.check_home_route_html`：home 锚点必须出现在 GET / 响应体（可选要求落在 `<article>`）。
- pipeline 注入后写 `.home_surface_anchors.json`；冒烟模板读取并硬红。
- 缺时指令：「在 index 卡片模板补字段」（禁止整文件重写风暴）。
- 源码 grep（`check_manifest_landing`）降级为辅闸。

### v56-4 刀H 降噪
- 锚点源改为刀C【验收节点逐字清单】，禁止整表 UI 硬契约 89 条灌入。
- 接入 compiler 同款黑名单：`the requested workflow` / boolish / 截图 OCR 中文。
- 保留既有 RepoFixer 基线不劣化护栏。

### v56-5 `_bp` 小刀
- `blueprint_convention`：顶层 `Blueprint(...)` **或** `def _bp(): return …` 工厂 → 绿。
- `interface_check`：契约 `_bp` 可由 Blueprint 别名 + 工厂满足；`webui_bp` 不再 extra 冻死。

### 验证 / 纪律
- 全量 pytest：**{passed} passed**（门槛 ≥1972）。
- commits：`{ha}`（1+2）/ `{hb}`（3+4）/ `{hc}`（5）+ 本回执。
- 未 push；未动 `.env`；未上平台；未 `--no-verify`。
"""
if "## v56 五刀施工回执" not in text:
    text = text.rstrip() + summary + "\n"
p.write_text(text, encoding="utf-8")
print("outbox updated")
PY

git add docs/agent-outbox.md scripts/v56_commit_five.sh
git commit -m "$(cat <<'EOF'
docs: v56 五刀 outbox 回执 + 验证脚本

EOF
)"

echo "===== done ====="
git log --oneline -8
git status -sb
echo "TARGETED: $(tail -n 1 /tmp/v56-targeted.txt)"
echo "FULL: $FULL_LINE"
echo "HA=$HA HB=$HB HC=$HC"
