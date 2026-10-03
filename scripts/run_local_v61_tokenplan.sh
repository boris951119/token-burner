#!/bin/bash
# 本地 github-stage-1：token-plan + deepseek-v4-flash-0731
# 用法：OPENAI_API_KEY=... ./scripts/run_local_v61_tokenplan.sh
set -euo pipefail
cd /Users/liuboyu/Developer/token-burner

OUT=/tmp/prod_test/stage1_v61
TASK=/Users/liuboyu/Developer/sheet-grader/requirements/hackathon--github-stage-1
LOG="$OUT/run_v61_flash.log"
CFG_BAK="$OUT/config.json.bak_before_v61"

: "${OPENAI_API_KEY:?set OPENAI_API_KEY}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1}"
export OPENAI_API_BASE="$OPENAI_BASE_URL"
export MODEL="${MODEL:-openai/deepseek-v4-flash-0731}"
export VISUAL_MODEL="${VISUAL_MODEL:-$MODEL}"
export VISUAL_BASE_URL="$OPENAI_BASE_URL"
export PYTHONUNBUFFERED=1

mkdir -p "$OUT"
echo "[probe] key_suffix=${OPENAI_API_KEY: -6} model=$MODEL base=$OPENAI_BASE_URL"

PROBE=$(curl -sS -o /tmp/v61_probe.json -w '%{http_code}' \
  --connect-timeout 30 --max-time 90 \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-flash-0731","messages":[{"role":"user","content":"ping reply ok"}],"max_tokens":16}' \
  "$OPENAI_BASE_URL/chat/completions" || true)
echo "[probe] HTTP=$PROBE"
if [ "$PROBE" != "200" ]; then
  echo "[probe] FAIL $(head -c 200 /tmp/v61_probe.json)"
  exit 2
fi

cp -f config.json "$CFG_BAK"
.venv/bin/python - <<'PY'
import json
from pathlib import Path
p = Path("config.json")
cfg = json.loads(p.read_text())
cfg["models"] = ["openai/deepseek-v4-flash-0731"]
cfg["workflow_mode"] = "single"
p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
print("[config]", cfg["models"], cfg["workflow_mode"])
PY

echo "[launch] OUT=$OUT LOG=$LOG"
nohup env \
  OPENAI_API_KEY="$OPENAI_API_KEY" \
  OPENAI_BASE_URL="$OPENAI_BASE_URL" \
  OPENAI_API_BASE="$OPENAI_API_BASE" \
  MODEL="$MODEL" \
  VISUAL_MODEL="$VISUAL_MODEL" \
  VISUAL_BASE_URL="$VISUAL_BASE_URL" \
  PYTHONUNBUFFERED=1 \
  .venv/bin/python main.py "$TASK" -o "$OUT" --mode auto \
  >"$LOG" 2>&1 &
PID=$!
echo "$PID" >"$OUT/run.pid"
echo "[launch] PID=$PID"
sleep 5
if ! kill -0 "$PID" 2>/dev/null; then
  echo "[launch] died early:"
  tail -60 "$LOG"
  exit 3
fi
head -40 "$LOG" || true
echo "STARTED_OK pid=$PID log=$LOG"
