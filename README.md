# token-burner

**文档消耗器 · AI 多智能体项目团队系统**

![version](https://img.shields.io/badge/version-v0.5.0--beta-orange)
![tests](https://img.shields.io/badge/tests-833%20passed%20%7C%200%20failed-brightgreen)
![python](https://img.shields.io/badge/python-3.10%2B-blue)

> Set your tokens on fire! —— 让每个 token 都烧在刀刃上。

把**一句软件需求**变成**可运行的项目**：评估路由 → 多模型组队 → 方案讨论 →
spec 确认 → 模块拆分 → 逐模块「写码 → 测试 → 执行」循环 → 交付物汇总。

全程 **token 可预算、可审计、可恢复**。核心理念一句话：

> **决策归 LLM，校验与边界归程序。** 智能负责判断，规则负责把关。

## 项目状态

| <br /> | <br />                                                    |
| ------ | --------------------------------------------------------- |
| 版本     | v0.5.0-beta（验收闭环完成，2026-09）                               |
| 测试     | 833 项自动化测试（826 passed / 7 skipped / 0 failed，全 stub 无需密钥） |
| 入口     | Web 工作台 / 桌面客户端 exe / CLI / VS Code 插件                    |
| 真实链路   | 已跑通多个真实项目（陌生技术栈 + 中断恢复 + auto 真实执行）                       |

详见 [CHANGELOG.md](CHANGELOG.md)「v0.5.0-beta · 验收闭环」节。

## 核心特性

- **多智能体团队流程** — 评估主 LLM 三分类路由（直答 / 简单编程直出 / 完整团队流程），
  三个角色模型强制互异；方案讨论 PM + 双评审，收敛生成 spec

- **六层成本护栏** — 预算总闸（200k，自动模式 ×2.5）→ 讨论轮数（3）→
  单轮输出（8k）→ 循环检测（Jaccard + embedding 双道）→ 修复上限（5）→
  spec 收敛（3）。全部由程序确定性执行，不依赖 LLM 自律

- **双执行模式** — 安全审阅模式（默认，不执行任何生成代码）/
  自动验证模式（真实执行，Docker 容器沙箱：512m 内存 / 只读 / 无网络 /
  非 root / 30s 熔断；Docker 缺失自动降级进程模式 + 危险 API 预扫描）

- **AST 接口门禁** — 接口地图为模块间唯一合法基线，违规引用直接阻断；
  零执行、零 LLM 调用的纪律执行器

- **模块化治理** — 难度 ≥5 或文件 ≥6 自动拆分；每模块独立目录 +
  独立规格 md + 独立修复记录，支持单独验收与追踪

- **Researcher Agent**（缺省关）— 陌生技术栈前置调研：四段式结构化摘要
  （来源/版本/示例/坑点）注入 Dev/Test；支持联网搜索（duckduckgo / tavily）
  与用户资料注入，独立预算 + SQLite 缓存

- **可恢复可取消** — 中断快照落盘，重启续跑（已完成模块自动跳过）；
  运行中任务协作式取消 + 僵尸清扫

- **全链路可观测** — 实时监控（阶段耗时 / token 曲线 / 模块全景）、
  Agent 对话流图、成本看板（按模型/阶段/档位 + 旗舰假设成本对比）、
  模式智能推荐（历史统计，零 LLM）

## 快速开始

```bash
pip install -r requirements.txt   # litellm / python-dotenv / pytest
```

**1. 配置密钥** — 复制 `.env.example` 为 `.env` 填写（密钥只走环境变量）：

```ini
OPENAI_API_KEY=          # openai/* 前缀模型（含智谱 GLM 的 OpenAI 兼容端点）
ANTHROPIC_API_KEY=
DEEPSEEK_API_KEY=
GEMINI_API_KEY=
```

> 智谱 GLM 等第三方 OpenAI 兼容端点还需 `OPENAI_API_BASE`，
> 如 `https://open.bigmodel.cn/api/paas/v4`。

**2. 配置模型** — `config.json` 覆盖默认预设（litellm 模型名，取前 3 个组队）：

```json
{
  "models": ["openai/glm-4.5-air", "openai/glm-4.6v", "openai/glm-4-flash"]
}
```

**3. 点火** — 四种入口，同一内核：

```bash
# ① Web 工作台（推荐）—— 浏览器打开 http://127.0.0.1:8000/
python -m app.server

# ② 桌面客户端 —— pywebview 原生窗口（pip install pywebview）
python -m app.desktop

# ③ 交互式 CLI
python -m app.main

# ④ VS Code 插件 —— vscode-extension/ 面板内发起任务、实时进度、
#    代码 diff 预览与一键应用、成本看板（cd vscode-extension && npm install）
```

点火后：评估 → 确认组队（可选模型与执行模式）→ 方案讨论 → spec 确认 →
模块开发循环 → 交付。交付物在 `projects/<需求>_<时间戳>/`：
`modules/*.md` + `code/` + `tests/` + `changelog/` + `logs/cost_report.json`，
安全模式由你本地运行验证后反馈。

## 关键配置

| 配置                        | 默认     | 说明                               |
| ------------------------- | ------ | -------------------------------- |
| `max_task_tokens`         | 200000 | 单任务预算总闸（自动验证模式 ×2.5）             |
| `model_routing_enabled`   | false  | 难度分 → 旗舰/主力/轻量三档智能路由             |
| `fast_triage_enabled`     | false  | System-1 快判前置（A/B 实测见 CHANGELOG） |
| `researcher_enabled`      | false  | Researcher 前置调研                  |
| `researcher_web_enabled`  | false  | 联网搜索（`duckduckgo` / `tavily`）    |
| `docker_executor_enabled` | false  | 自动模式容器级沙箱                        |
| `enable_git`              | true   | 生成项目本地 git 版本管理                  |
| `model_prices`            | 近似价    | 各模型 $/Mtok 单价（成本对比口径）            |

完整参数见 [app/config.py](app/config.py)（每个字段均有注释与缺省值）。

## 架构

```
需求（不可信输入 → 数据边界包裹）
  → [可选快判] 评估路由（三分类 + 难度分）
  → [可选 Researcher：资料注入 / 联网搜索 → 四段式摘要]
  → 组队（三模型互异校验）→ 方案讨论（PM/双评审，五层护栏）
  → 模块拆分（难度≥5 或文件≥6）→ 接口契约（imports/exports/public_api）
  → 逐模块开发循环（写码 → 测试 → 静态验证 → 接口门禁 → 执行）
  → 反馈闭环（安全模式）/ 自动验证（Docker 沙箱或进程降级）
  → 交付（modules/*.md + code/ + tests/ + changelog/ + 成本看板）
```

执行层双实现：`LocalExecutor`（进程级 + 危险 API 预扫描 + 超时熔断）与
`DockerExecutor`（资源配额 / 只读文件系统 / 无网络 / 非 root，镜像预热与降级）。

## 安全与信任边界

以下输入均按**不可信输入**处理（`_sanitize_untrusted` 数据边界包裹 +
提示词明示「是数据非指令」）：用户需求、运行反馈与报错日志、LLM 生成代码、
Researcher 摘要与联网抓取文本。

- **安全审阅模式（默认）不执行任何生成代码**

- 自动模式默认 Docker 容器沙箱；Docker 未装自动降级进程模式，
  危险 API 黑名单预扫描（系统命令 / 网络 / 动态执行 / 危险文件操作）仍生效

## 测试

```bash
python -m pytest tests/ -q                  # 833 项（全 stub，无需密钥）
cd vscode-extension && npm test             # 插件消息协议契约测试
python scripts/ab_triage_eval.py --mock     # 快慢双模式 A/B 自检（--real 走真实 LLM）
```

## 发布

推送 `v*` 标签触发 GitHub Actions（[release.yml](.github/workflows/release.yml)）：
pytest 全量回归 → PyInstaller 构建 → 产物体积检查（≤80MB）→ Release 附 EXE。

## 文档

- [CHANGELOG.md](CHANGELOG.md) — 版本历史（含 v0.5 验收闭环与真实质量发现）

- [v0.5.md](v0.5.md) / [v0.5-workplan.md](v0.5-workplan.md) — Beta 任务清单与批次计划

- [v0.4.md](v0.4.md) — Alpha 规格（双模式意图 / Docker 沙箱 / 并发架构）

- [v0.3.1 合并版规格](Token消耗器_AI多智能体项目团队系统_开发规格文档_v0.3.1_合并版.md) — 核心流程与护栏设计

- [文档目录.md](文档目录.md) — 全部文档索引

