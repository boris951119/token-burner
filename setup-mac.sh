#!/bin/bash
# Mac mini 环境搭建：clone 后在项目根目录执行 ./setup-mac.sh
# 前置：已装 Homebrew；.env 与 token-burner-submission-v8.zip 已手动拷入项目根目录
set -euo pipefail
cd "$(dirname "$0")"

command -v brew >/dev/null || { echo "先装 Homebrew: https://brew.sh"; exit 1; }

echo "[1/6] 安装 python@3.12 / node（已装则跳过）"
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12
brew list node >/dev/null 2>&1 || brew install node

PY=$(brew --prefix python@3.12)/bin/python3.12

echo "[2/6] 建 venv 并装依赖"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "[3/6] Playwright（评分链路走 node 侧 npx，非 pip playwright 包）"
# 国内网络建议：npm config set registry https://registry.npmmirror.com
# 并导出 PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright
(cd scripts/official_grade && npm install --no-fund --no-audit \
  && npx playwright install chromium)

echo "[4/6] Docker 验证镜像（守护进程可用时）"
# DockerExecutor 在容器内跑 pytest，官方 python:3.11-slim 不带 pytest——
# 本地把 pytest 烘进同名 tag（仅覆盖本机 tag，_ensure_image 见本地即不重拉）。
# Colima 注意：macOS 临时目录在 /var/folders，须把该路径加进 ~/.colima/*/colima.yaml
# 的 mounts，否则容器内 bind mount 为空（live 测试 9/22 取证）。
if docker info >/dev/null 2>&1; then
  if ! docker run --rm python:3.11-slim python -c "import pytest" >/dev/null 2>&1; then
    dtmp="$(mktemp -d)"
    printf 'FROM python:3.11-slim\nRUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple pytest\n' > "$dtmp/Dockerfile"
    docker build -q -t python:3.11-slim "$dtmp" >/dev/null && rm -rf "$dtmp" \
      && echo "  python:3.11-slim 已烘焙 pytest"
  fi
  docker pull node:20-slim >/dev/null 2>&1 || echo "  !! node:20-slim 拉取失败（node 模块容器验证不可用）"
else
  echo "  docker 不可用——执行器走 LocalExecutor 降级，live 容器测试将跳过"
fi

echo "[5/6] 配置自检"
[ -f .env ] || echo "  !! .env 缺失——从中转机拷贝后再跑生成/评分"
[ -f token-burner-submission-v8.zip ] || echo "  !! v8 提交包缺失——重建包时需要它作 baseline"

echo "[6/6] 测试套件（期望 ~1380 通过）"
.venv/bin/python -m pytest tests -q

echo "完成。验证额度: .venv/bin/python scripts/quota_probe.py（若已拷）或重新跑探针"
