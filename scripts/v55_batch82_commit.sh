#!/usr/bin/env bash
# v55 批次#82：施工1 RepoFixer 基线护栏 + 刀I coverage_gap
# 用法（仓库根）： bash scripts/v55_batch82_commit.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"
export PYTHONUNBUFFERED=1

stamp() { date '+%m-%d %H:%M'; }

echo "===== git preflight ====="
git status -sb
git log -5 --oneline
git diff --stat HEAD

echo "===== targeted pytest ====="
$PY -m pytest \
  tests/test_repo_fixer_baseline.py \
  tests/test_coverage_gap.py \
  tests/test_repo_fixer.py \
  tests/test_syntax_freeze.py \
  -q --tb=short | tee /tmp/v55-batch82-targeted.txt

echo "===== full pytest ====="
$PY -m pytest -q --tb=line | tee /tmp/v55-batch82-full.txt
FULL_LINE=$(tail -n 1 /tmp/v55-batch82-full.txt)
echo "FULL_SUMMARY: $FULL_LINE"
PASSED=$(echo "$FULL_LINE" | python3 -c "import sys,re;m=re.search(r'(\d+) passed',sys.stdin.read());print(m.group(1) if m else 0)")
if [[ -z "${PASSED}" ]] || [[ "${PASSED}" -lt 1966 ]]; then
  echo "FAIL: expected ≥1966 passed, got: ${FULL_LINE}"
  exit 1
fi

echo "===== Commit 1: RepoFixer baseline ====="
# outbox 此时应仅含施工1表行（刀I 行由下方在 commit2 前追加）
git add \
  app/agents/repo_fixer.py \
  tests/test_repo_fixer_baseline.py \
  docs/agent-outbox.md
git commit -m "$(cat <<'EOF'
v55: RepoFixer 重写基线不劣化护栏（批次#82 施工1）

EOF
)"
H1=$(git rev-parse HEAD)
H1s=$(git rev-parse --short HEAD)
echo "COMMIT1=$H1 ($H1s)"

echo "===== append outbox 刀I + summary ====="
TS="$(stamp)"
export TS H1s
python3 - <<'PY'
import os
from pathlib import Path
p = Path("docs/agent-outbox.md")
text = p.read_text(encoding="utf-8")
ts = os.environ["TS"]
h1s = os.environ["H1s"]
row = (
    f"| {ts} | **INBOX-013 刀I 完工** | "
    f"`coverage_gap.enforce_node_states_gap`：清单全节点 vs SDK "
    f"node_states 差集红；日志点名 + 刀C 注入 + requirements 补登记；"
    f"挂 pipeline 交付前 + Phase 0。见下方专节。 |\n"
)
anchor = "**v55 批次#82 施工1**"
if anchor in text and "INBOX-013 刀I 完工" not in text:
    lines = text.splitlines(keepends=True)
    out, inserted = [], False
    for ln in lines:
        out.append(ln)
        if (not inserted) and anchor in ln and ln.startswith("|"):
            out.append(row)
            inserted = True
    text = "".join(out)
summary = f"""

---

## v55 批次#82 施工回执（{ts}，施工1 + INBOX-013 刀I）

### 施工1：RepoFixer 重写基线不劣化
- `RepoFixer(baseline_test_cmd=…)`：整文件重写前后跑基线命令，解析 `N passed`；新版 passed < 基线 → 回滚磁盘内容，并把「基线 X 过 / 新版 Y 过，请换思路或最小化修改」写入下一轮修复指令。
- **关键**：劣化回滚后盘上基线复绿 ≠ 修复成功——`degraded` 旗禁止把回滚后的绿误判为 `ok=True`。
- 回归：`tests/test_repo_fixer_baseline.py`（劣化回滚 / 改进接受 / 下一轮注记）。
- **接线说明**：`probe-fast` / `auto_repair` 显式传入 `baseline_test_cmd=gate|smoke_gate` 落在 `app/arcbench_smoke.py`，与施工2（刀I）同文件一并提交。

### 刀I（INBOX-013）：node_states 覆盖缺口闸
- `app/utils/coverage_gap.py`：`audit_node_states_gap` + `enforce_node_states_gap`——`compile_checklists` 全节点 id vs SDK `list_node_states` 键集；缺口 >0 → `[coverage-gap] 缺 N 个…` + `inject_contracts_by_ownership`（复用刀C）+ `upsert_requirement` 补登记；本地无 SDK 时 `skip_if_no_sdk` 不误伤。
- 挂点：`pipeline` 交付段之前；`arcbench_smoke` Phase 0（缺口 id 并入 `prefer_ids` / 修复注记）。
- 验收：`tests/test_coverage_gap.py`——3 节点题面只报 2 → missing 精确 `REQ-2-1-1`，日志/注入/登记齐。

### 纪律
- 两独立 commit：施工1=`{h1s}`；刀I=本提交。
- 未 push；未动 `.env`；未 `--no-verify` / amend。
"""
if "## v55 批次#82 施工回执" not in text:
    text = text.rstrip() + summary + "\n"
p.write_text(text, encoding="utf-8")
print("outbox knife-I receipt appended")
PY

echo "===== Commit 2: coverage_gap 刀I ====="
git add \
  app/utils/coverage_gap.py \
  tests/test_coverage_gap.py \
  app/pipeline.py \
  app/arcbench_smoke.py \
  docs/agent-inbox.md \
  docs/agent-outbox.md
git commit -m "$(cat <<'EOF'
v55: 刀I node_states 覆盖缺口闸（INBOX-013）

EOF
)"
H2=$(git rev-parse HEAD)
H2s=$(git rev-parse --short HEAD)
echo "COMMIT2=$H2 ($H2s)"

echo "===== done ====="
git log --oneline -4
git status -sb
echo "TARGETED: $(tail -n 1 /tmp/v55-batch82-targeted.txt)"
echo "FULL: $FULL_LINE"
echo "SHA1=$H1"
echo "SHA2=$H2"
