#!/usr/bin/env bash
# v54 四刀：相关套件 → 全量 pytest → 独立 commit（含 outbox 回执）
# 在仓库根： bash scripts/v54_commit_four.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
export PYTHONUNBUFFERED=1

stamp() { date '+%m-%d %H:%M'; }

append_outbox_row() {
  local entry="$1" summary="$2"
  local ts row
  ts="$(stamp)"
  row="| ${ts} | ${entry} | ${summary} |"
  python3 - "$row" <<'PY'
import sys
from pathlib import Path
row = sys.argv[1] + "\n"
p = Path("docs/agent-outbox.md")
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
j = 0
last_table = None
for i, ln in enumerate(lines):
    if ln.startswith("|") and not ln.startswith("|---") and "日期时间" not in ln and "回执摘要" not in ln:
        last_table = i
if last_table is not None:
    lines.insert(last_table + 1, row)
else:
    lines.append(row)
p.write_text("".join(lines), encoding="utf-8")
print("outbox:", row.strip())
PY
}

append_summary() {
  local h1="$1" h2="$2" h3="$3" h4="$4"
  cat >> docs/agent-outbox.md <<EOF

---

## v54 四刀施工回执（$(stamp)，批次#78）

| 刀 | commit | 要点 |
|---|---|---|
| 修1 P1-3 | \`${h1}\` | factory_pool 子进程试装，父进程零 import 生成码 |
| 修2 P1-2 | \`${h2}\` | json_mode 降级仅 response_format 400；超时禁降级；梯 //2 |
| 修3 P1-5 | \`${h3}\` | RepoFixer stop_check；probe-fast join 超时置旗停写 |
| 修4 P2-8 | \`${h4}\` | _compose_from_blueprints 全收顶层 Blueprint |

未 push；未动密钥；未上平台。
EOF
}

echo "===== 修1 P1-3 ====="
$PY -m pytest tests/test_v53_arity_factory.py tests/test_v46_overnight.py -q --tb=short
$PY -m pytest -q --tb=line
append_outbox_row "v54 修1·P1-3" "factory_pool 子进程化；超时/infra fail-closed；相关+全量绿（本提交）"
git add app/utils/factory_pool.py tests/test_v53_arity_factory.py tests/test_v46_overnight.py docs/agent-outbox.md
git commit -m "$(cat <<'EOF'
v54 P1-3: isolate author factory probe in subprocess

Prevent generated packages named app/config from ejecting agent modules via sys.modules.
EOF
)"
H1=$(git rev-parse --short HEAD)

echo "===== 修2 P1-2 ====="
$PY -m pytest tests/test_model_client.py -q --tb=short
$PY -m pytest -q --tb=line
append_outbox_row "v54 修2·P1-2" "json_mode 降级仅 400+response_format；超时/连接禁降级；梯减半；相关+全量绿（本提交）"
git add app/utils/model_client.py tests/test_model_client.py docs/agent-outbox.md
git commit -m "$(cat <<'EOF'
v54 P1-2: gate json_mode fallback to response_format 400 only

Timeouts/connection errors no longer re-run the full retry ladder; degrade uses half retries.
EOF
)"
H2=$(git rev-parse --short HEAD)

echo "===== 修3 P1-5 ====="
$PY -m pytest tests/test_repo_fixer.py tests/test_v46_overnight.py -q --tb=short
$PY -m pytest -q --tb=line
append_outbox_row "v54 修3·P1-5" "RepoFixer stop_check + probe-fast join 超时置旗；相关+全量绿（本提交）"
git add app/agents/repo_fixer.py app/arcbench_smoke.py tests/test_repo_fixer.py docs/agent-outbox.md
git commit -m "$(cat <<'EOF'
v54 P1-5: stop RepoFixer writes on probe-fast join timeout

Share a stop flag via closure so timed-out repair threads cannot tear files during export.
EOF
)"
H3=$(git rev-parse --short HEAD)

echo "===== 修4 P2-8 ====="
$PY -m pytest tests/test_platform_export.py -q --tb=short
$PY -m pytest -q --tb=line
append_outbox_row "v54 修4·P2-8" "组合兜底全收顶层 Blueprint；双蓝图两套路由进应用；相关+全量绿（本提交）"
git add app/platform_export.py tests/test_platform_export.py docs/agent-outbox.md
git commit -m "$(cat <<'EOF'
v54 P2-8: register all top-level Blueprints in compose fallback

Align with mechanical_assembly: collect every Blueprint per module, skip name conflicts.
EOF
)"
H4=$(git rev-parse --short HEAD)

append_summary "$H1" "$H2" "$H3" "$H4"
git add docs/agent-outbox.md
git commit -m "$(cat <<'EOF'
v54: outbox summary receipt for four P1/P2 fixes
EOF
)"

echo "DONE"
git log --oneline -6
git status -sb
