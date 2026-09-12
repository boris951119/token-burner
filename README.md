# token-burner

文档消耗器 · AI 多智能体项目团队系统（v1.0.0）

Set your tokens on fire!

把一句软件需求变成**可运行的项目**：评估路由 → 多模型组队 → 方案讨论 →
spec 确认 → 模块拆分 → 逐模块「写码 → 测试 → 执行」循环 → 交付物汇总。
全程 token 可审计、可预算、可恢复，决策归 LLM、校验与边界归程序。

## 功能一览

- **多智能体团队流程**：评估主 LLM 三分类路由（直答 / 简单编程直出 / 完整团队流程），
  三个角色模型互异；方案讨论 PM + 双评审（轮数/循环/收敛五层护栏）；
  难度 ≥5 或预估文件 ≥6 自动模块化拆分 + 接口契约

- **双模式意图识别**：轻量模型快判（闲聊/无意义直接拒答省 token），
  低置信自动升级全量评估（`fast_triage_enabled`，缺省关）

- **智能模型路由**：难度分 → 旗舰/主力/轻量三档分发（阈值与档位列表均可进
  `config.json` 自定义；`model_routing_enabled` 缺省关）

- **Researcher Agent**（缺省关）：陌生技术栈可在开发前生成四段式结构化摘要
  （来源/版本/用法示例/坑点）注入 Dev/Test 提示词；支持联网搜索
  （duckduckgo 免 key / tavily，`researcher_web_enabled` 缺省关，失败自动回退
  用户资料注入）；独立预算 20k + SQLite 缓存（TTL 7 天）

- **双执行模式**：安全模式（默认，不执行生成代码，交付后由你本地验证）/
  自动验证模式（真实执行，Docker 容器沙箱：资源配额/只读/无网络/非 root，
  Docker 不可用自动降级进程模式）

- **成本治理**：六层护栏（预算总闸 → 讨论轮数 → 循环检测 → 修复上限 →
  spec 收敛 → 输出截断）；`logs/cost_report.json` 全程审计；
  成本看板含档位路由明细与旗舰假设成本对比（`model_prices` 价目表可配置）；
  Embedding 缓存与 Researcher 缓存节省量统计

- **可恢复与可取消**：中断后恢复续跑（已完成模块自动跳过）；运行中任务
  协作式取消 + 僵尸任务启动清扫

- **并行模块开发**（v1.2）：无依赖模块同层并发（worker 数可配），
  依赖分层间保持拓扑序，等待时间 2-4× 压缩

- **repo-patch 模式**（v1.2）：除从零生成外，支持克隆真实仓库至 base commit、
  以 issue 文本为需求产出补丁并跑仓库自带测试（SWE-bench Lite 跑分线，
  `scripts/swebench_run.py`）

- **可视化**：Web 工作台实时监控（阶段耗时 / token 曲线 / 模块全景）、
  对话流图、模式推荐、深浅主题、分类设置页

## 快速开始

```bash
pip install -r requirements.txt        # litellm / python-dotenv / pytest
```

**配置密钥**：复制 `.env.example` 为 `.env`，按所用供应商填写
（密钥只从环境变量读取，不写入代码或 config.json）：

```ini
OPENAI_API_KEY=          # openai/* 前缀模型（含智谱 GLM 的 OpenAI 兼容端点）
ANTHROPIC_API_KEY=
DEEPSEEK_API_KEY=
GEMINI_API_KEY=
```

**配置模型**：编辑 `config.json` 覆盖默认预设（litellm 模型名）：

```json
{
  "models": ["openai/glm-4-plus", "openai/glm-4-air", "openai/glm-4-flash"]
}
```

> GLM 等第三方 OpenAI 兼容端点还需设置 `OPENAI_API_BASE` 环境变量，
> 例如 `https://open.bigmodel.cn/api/paas/v4`。

### ⚡ 90 秒上手（Web 工作台引导）

1. `python -m app.server` → 浏览器打开 http://127.0.0.1:8000/
2. 首次打开会弹出**连接向导**：选模型服务商模板（智谱 / DeepSeek /
   Moonshot / 阿里云百炼 / OpenRouter / 本地 Ollama）→ 粘贴 API Key →
   点「🔍 自动发现模型」→ 点「验证连通」绿灯即成
3. 回到工作台输入一句需求（如"开发一个待办事项 CLI"）→ 点火

连接保存在服务端 `secrets.local.json`（密钥只写不读），修改模型免重启；
交付目录可在「⚙ 设置 → 📁 交付目录」随时切换。

### 三种打开方式

```bash
# ① Web 工作台（推荐）：浏览器打开 http://127.0.0.1:8000/
python -m app.server

# ② 交互式 CLI
python -m app.main

# ③ 桌面客户端（pywebview 原生窗口，需 pip install pywebview）
python -m app.desktop
```

点火后：评估 → 确认组队（可选三个模型与执行模式）→ 方案讨论 →
spec 确认 → 模块开发循环 → 交付。安全模式下交付物在
`projects/<需求>_<时间戳>/`（`modules/*.md` + `code/` + `tests/` +
`changelog/` + `logs/cost_report.json`），由你本地运行验证后反馈。

### VS Code 插件

`vscode-extension/`：活动栏面板内发起任务 / 实时进度 / 代码应用 / 成本看板，
支持预算与默认模型设置（`tokenBurner.*`）。构建与打包：

```bash
cd vscode-extension
npm install
npm run compile        # 产物在 out/；消息协议契约测试：npm test
```

## 关键配置（config.json 覆盖 `Settings` 默认值）

| 配置                                             | 默认     | 说明                              |
| ---------------------------------------------- | ------ | ------------------------------- |
| `max_task_tokens`                              | 200000 | 单任务预算总闸（自动验证模式 ×2.5）            |
| `model_routing_enabled`                        | false  | 难度分三档智能路由                       |
| `model_tier_flagship` / `_main` / `_light`     | 预设     | 三档模型列表（须 ⊆ models）              |
| `route_flagship_threshold` / `_main_threshold` | 7 / 4  | 分档难度阈值（可自定义）                    |
| `fast_triage_enabled`                          | false  | System-1 快判前置                   |
| `researcher_enabled`                           | false  | Researcher 前置调研                 |
| `researcher_web_enabled`                       | false  | 联网搜索（供应商 `duckduckgo`/`tavily`） |
| `docker_executor_enabled`                      | false  | 自动模式容器级沙箱                       |
| `enable_git`                                   | true   | 生成项目本地 git 版本管理                 |
| `model_prices`                                 | 近似价    | 各模型 $/Mtok 单价（看板成本对比口径）         |

完整参数见 `app/config.py`（每个字段都有注释与缺省值）。

## 架构一览

```
需求（不可信输入 → 数据边界包裹）
  → [可选快判] 评估路由（三分类 + 难度分，System-2 固定降档）
  → [可选 Researcher：资料注入 / 联网搜索 → 四段式摘要]
  → 组队（三模型互异校验）→ 方案讨论（PM/双评审，五层护栏）
  → 模块拆分（难度≥5 或文件≥6）→ 接口契约（imports/exports/public_api）
  → 逐层模块开发循环（同层并发；写码 → 测试 → 静态验证 → 接口门禁 → 执行）
  → 反馈闭环（安全模式）/ 自动验证（Docker 沙箱或进程降级）
  → 交付（modules/*.md + code/ + tests/ + changelog/ + 成本看板）
```

执行层双实现：`LocalExecutor`（进程级 + 危险 API 预扫描 + 超时熔断）与
`DockerExecutor`（资源配额/只读文件系统/无网络/非 root，镜像自动预热与检测降级）。

## 安全与信任边界

以下输入均按**不可信输入**处理（`_sanitize_untrusted` 数据边界包裹 +
提示词明示「是数据非指令」，M7-6 治理模式全链路同构）：

- 用户需求文本、用户反馈（运行结果/报错日志）、LLM 生成代码的输出、
  Researcher 摘要与联网抓取文本；

- 自动模式的代码执行：默认 Docker 容器沙箱（内存 512m / cpus 1.0 /
  pids 128 / tmpfs 64m / 只读文件系统 / 无网络 / 非 root / 超时熔断），
  Docker 未安装自动降级进程模式（危险 API 黑名单预扫描仍生效）；
  **安全模式（默认）不执行任何生成代码**。

## 测试

```bash
python -m pytest tests/ -q                  # 1116 项（全 stub，无需密钥）
cd vscode-extension && npm test             # 插件消息协议契约测试 4 项
python scripts/ab_triage_eval.py --mock     # 快慢双模式 A/B 自检（--real 走真实 LLM）
```

## 发布

推送 `v*` 标签触发 GitHub Actions（`.github/workflows/release.yml`）：
pytest 全量回归 → PyInstaller 构建 → 产物体积检查（≤80MB）→ Release 附 EXE。

## ARC-Bench 参赛模式

平台 runner 以 headless CLI 调用（模型经环境变量注入，OpenAI 兼容网关，
平台提交包 = 仓库 zip，根目录含 `main.py` + `requirements.txt`）：

```bash
OPENAI_API_KEY=<key> OPENAI_BASE_URL=<gateway> MODEL=<model> \
python main.py <requirements_dir> --output-dir <output_dir> --type web --mode auto
```

- 需求树摄取：`requirements.yaml`（FOLDER/ATOMIC）→ 管线需求文本，
  FOLDER 对齐模块划分、ATOMIC 对齐验收标准、`tests/helpers.ts` 种子契约注入
  （`app/arcbench_ingest.py`）
- 过程上报：Pipeline 事件 → 官方 SDK 翻译（事件流 + traceability + git 提交），
  本地无 SDK 自动 no-op（`app/arcbench_bridge.py`）
- 交付后集成冒烟：import 全模块 + `create_app()` + `/api/health` 200，
  失败自动修复 ≤3 轮（`app/arcbench_smoke.py`）
- 中断恢复：`--resume` 跳过已完成模块续跑

赛制理解 / 提交契约 / 演练计划见 [docs/competition-plan.md](docs/competition-plan.md)。

## 文档

- [CHANGELOG.md](CHANGELOG.md) — 版本历史（v1.0.0 正式版交付清单；v1.2 参赛适配与 SWE-bench 基准线）

- [docs/competition-plan.md](docs/competition-plan.md) — ARC-Bench 参赛作战手册
  （赛制理解 / 提交契约 / 模型策略 / 演练计划 / 风险预案）

- [v1.0.md](v1.0.md) / [v1.0-workplan.md](v1.0-workplan.md) — 1.0 定稿规格与批次计划

- [文档目录.md](文档目录.md) — 全部文档索引

