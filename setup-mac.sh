#!/bin/bash
# Mac mini 环境搭建：clone 后在项目根目录执行 ./setup-mac.sh
# 前置：已装 Homebrew；.env 与 token-burner-submission-v8.zip 已手动拷入项目根目录
set -euo pipefail
cd "$(dirname "$0")"

command -v brew >/dev/null || { echo "先装 Homebrew: https://brew.sh"; exit 1; }

echo "[1/5] 安装 python@3.12 / node（已装则跳过）"
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12
brew list node >/dev/null 2>&1 || brew install node

PY=$(brew --prefix python@3.12)/bin/python3.12

echo "[2/5] 建 venv 并装依赖"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "[3/5] Playwright（评分链路走 node 侧 npx，非 pip playwright 包）"
# 国内网络建议：npm config set registry https://registry.npmmirror.com
# 并导出 PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright
(cd scripts/official_grade && npm install --no-fund --no-audit \
  && npx playwright install chromium)

echo "[4/5] 配置自检"
[ -f .env ] || echo "  !! .env 缺失——从中转机拷贝后再跑生成/评分"
[ -f token-burner-submission-v8.zip ] || echo "  !! v8 提交包缺失——重建包时需要它作 baseline"

echo "[5/5] 测试套件（期望 ~1370 通过）"
.venv/bin/python -m pytest tests -q

echo "完成。验证额度: .venv/bin/python scripts/quota_probe.py（若已拷）或重新跑探针"
