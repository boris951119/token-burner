#!/usr/bin/env bash
# 平台形态全真演练（提交包解包 / 零 config.json / 单模型下发 / 无 node / Linux）
#
# 为什么单独要一支：本地彩排历来吃 config.json（三模型 multi=True）且在
# Mac 上跑（有 node）；官方 runner 的形态是「注入 MODEL 单模型 +
# CWD≠提交目录导致 config.json 读不到 + python:3.11-slim 无 node」。
# 三者叠加会走到 _apply_runner_model 的中转站补全分支与自测闸的
# node-free 分支——这两条路本地从未端到端跑过。
#
# 暂存的是**提交包解包结果**（不是工作树）：演练对象必须与交给平台的东西
# 逐字节一致，否则「本地过了」不构成任何证据（首版用 rsync 暂存，
# 连 release/ 的 82MB 本机产物一起拖进容器，形态反而更不真）。
#
# 用法：scripts/platform_shape_rehearsal.sh <requirements目录> [任务名]
#   PKG=<zip> 指定提交包（缺省自动跑 build_submission.py 造 v9）
#   默认只构建并打印启动命令；加 RUN=1 才真正发起（会产生真实 token 消费）
set -euo pipefail

REQ_SRC="${1:?用法: $0 <requirements目录> [任务名]}"
TASK="${2:-$(basename "$(dirname "$REQ_SRC")")}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$ROOT/.tmp/linux-dryrun/agent-shape"
WORK="$ROOT/.tmp/linux-dryrun/shape-work/$TASK"
OUT_DIR="$ROOT/.tmp/linux-dryrun/out"
LOG="$OUT_DIR/shape-$TASK.log"
IMAGE="tb-shape:${TASK}"
NAME="tb-shape-${TASK}"
PKG="${PKG:-$ROOT/.tmp/submission-pack/v9.zip}"

[ -d "$REQ_SRC" ] || { echo "需求目录不存在: $REQ_SRC" >&2; exit 2; }

echo "[1/5] 取提交包（官方 runner 拿到的就是它）"
if [ ! -f "$PKG" ]; then
  echo "      $PKG 不存在 → 现场构建"
  (cd "$ROOT" && python3 scripts/build_submission.py --out "$PKG")
fi
echo "      包: ${PKG##*/} $(du -h "$PKG" | cut -f1)"

echo "[2/5] 解包暂存（并删掉 config.json，逼出无配置分支）"
rm -rf "$STAGE"; mkdir -p "$STAGE"
unzip -q "$PKG" -d "$STAGE"
rm -f "$STAGE/config.json"
[ -f "$STAGE/requirements.txt" ] || { echo "缺 requirements.txt" >&2; exit 1; }
echo "      包内文件数: $(find "$STAGE" -type f | wc -l | tr -d ' ')"

echo "[3/5] 构建镜像（python:3.11-slim + 包内 requirements，无 node）"
cat > "$STAGE/Dockerfile.rehearsal" <<'DOCKER'
FROM python:3.11-slim
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PYTHONUNBUFFERED=1 \
    LITELLM_LOCAL_MODEL_COST_MAP=True
WORKDIR /agent
COPY . /agent/
RUN pip install --no-cache-dir -r requirements.txt
CMD ["sleep", "infinity"]
DOCKER
docker build -q -f "$STAGE/Dockerfile.rehearsal" -t "$IMAGE" "$STAGE" >/dev/null
docker run --rm --name "${NAME}-probe" "$IMAGE" sh -c \
  'command -v node npx >/dev/null 2>&1 && echo "WARN: 镜像里有 node，演练形态失真" || echo "      形态确认：无 node（自测闸走 node-free 分支）"; \
   test -f /agent/config.json && echo "WARN: 容器里仍有 config.json" || echo "      形态确认：零 config.json"'

echo "[4/5] 载入题面到容器工作目录"
rm -rf "$WORK"; mkdir -p "$WORK/requirements" "$OUT_DIR"
cp -a "$REQ_SRC"/. "$WORK/requirements/"

KEY_LINE=$(grep -E '^OPENAI_(API_KEY|KEY)=' "$ROOT/.env" | head -1 || true)
BASE_LINE=$(grep -E '^OPENAI_(API_BASE|BASE_URL)=' "$ROOT/.env" | head -1 || true)
MODEL_LINE=$(grep -E '^MODEL=' "$ROOT/.env" | head -1 || true)
[ -n "$KEY_LINE" ] || { echo ".env 里没有网关 key" >&2; exit 1; }
# MODEL 缺失必须现在停：容器里 MODEL 为空时 _apply_runner_model 直接 return，
# 编制退化成包内默认四模型（gpt-4o/claude/…，本机全无 key）——预检全灭看着
# 像网关故障，实际是演练自己少配了一行（9/23 首次演练即栽在这，白起一次镜像）。
[ -n "${MODEL_LINE#MODEL=}" ] || { echo ".env 里没有 MODEL=（演练形态要求单模型注入）" >&2; exit 1; }
[ -n "$BASE_LINE" ] || { echo ".env 里没有 OPENAI_API_BASE/OPENAI_BASE_URL" >&2; exit 1; }
ENV_FILE="$WORK/.shape.env"
{ echo "$KEY_LINE"; echo "$BASE_LINE"
  echo "MODEL=${MODEL_LINE#MODEL=}"; echo "PYTHONUNBUFFERED=1"
  echo "LITELLM_LOCAL_MODEL_COST_MAP=True"; } > "$ENV_FILE"
chmod 600 "$ENV_FILE"
# 只印键名：值即密钥，绝不进日志
echo "      env 文件已生成: $(cut -d= -f1 "$ENV_FILE" | tr '\n' ' ')"

CMD="docker run -d --name $NAME --env-file $ENV_FILE \
  -v $WORK:/work -v $OUT_DIR:/out $IMAGE \
  sh -c 'cd /agent && python3 -u main.py /work/requirements --output-dir /work/out --type web > /out/shape-$TASK.log 2>&1; echo rc=\$? >> /out/shape-$TASK.log'"

if [ "${RUN:-0}" != "1" ]; then
  echo "[5/5] 未启动（默认只构建）。发起真实运行："
  echo "      RUN=1 $0 $REQ_SRC $TASK"
  echo "      或手工：$CMD"
  exit 0
fi

echo "[5/5] 启动容器化生成（真实消费，进度看 /out/shape-$TASK.log）"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --env-file "$ENV_FILE" \
  -v "$WORK:/work" -v "$OUT_DIR:/out" "$IMAGE" \
  sh -c "cd /agent && python3 -u main.py /work/requirements --output-dir /work/out --type web > /out/shape-$TASK.log 2>&1; echo rc=\$? >> /out/shape-$TASK.log" >/dev/null
echo "      跟踪：docker exec $NAME tail -20 $LOG"
