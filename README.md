# token-burner

文档消耗器 · AI 多智能体软件交付系统

Set your tokens on fire!

把一句软件需求变成**可运行的项目**：评估路由 → 多模型组队 → 方案讨论 →
spec 确认 → 模块拆分 → 逐模块「写码 → 测试 → 执行」循环 → 交付物汇总。
全程 token 可审计、可预算、可恢复；**决策归 LLM，校验与边界归程序**。

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

- **并行模块开发**：无依赖模块同层并发（worker 数可配），
  依赖分层间保持拓扑序，等待时间 2-4× 压缩

- **repo-patch 模式**：除从零生成外，支持克隆真实仓库至 base commit、
  以 issue 文本为需求产出补丁并跑仓库自带测试（`scripts/swebench_run.py`）

- **可视化**：Web 工作台实时监控（阶段耗时 / token 曲线 / 模块全景）、
  对话流图、模式推荐、深浅主题、分类设置页

### 交付质量（确定性闸门）

- **机械审计器**：schema / 包结构 / 符号导入 / 命名漂移垫片 / 子模块绑定 /
  UI 语言一致性 / 种子契约 / 接口属性漂移 / 内存哨兵等——零 LLM，失败可定位
- **编译自评分**：从需求抽逐字事实（种子 / 控件 / 文案）→ 起服秒级判红，
  按需求编号灌入修复通道
- **机械装配**：AST 扫描 blueprint / `init_*` 确定性接线 `create_app`；
  需求含 UI 时守卫页面模块；可选 `module_mode=monolith` 减少模块间接缝
- **模型链保护**：超时接力编队内其余模型；账户级止损；修复「不劣化」回滚；
  模块级优雅冻结
- **自测交付闸**：可自生成 Playwright 验收规格；失败时把页面可访问性树
  （按失败定位器附近裁窗）交给修复环，各轮刷新现场
- **预算硬帽**：`max_task_tokens_cap` 可真正压住单次试跑成本

## 快速开始

```bash
# macOS 一键（venv + 依赖 + Playwright chromium + 全量自检）
bash setup-mac.sh

# 或手动
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

> 第三方 OpenAI 兼容端点还需设置 `OPENAI_API_BASE`（或 `OPENAI_BASE_URL`）。

### ⚡ 90 秒上手（Web 工作台引导）

1. `python -m app.server` → 浏览器打开 http://127.0.0.1:8000/
2. 首次打开会弹出**连接向导**：选模型服务商模板 → 粘贴 API Key →
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

`vscode-extension/`：活动栏面板内发起任务 / 实时进度 / 代码应用 / 成本看板。

```bash
cd vscode-extension && npm install && npm run compile
```

## 关键配置（config.json 覆盖 `Settings` 默认值）

| 配置                                             | 默认     | 说明                              |
| ---------------------------------------------- | ------ | ------------------------------- |
| `max_task_tokens`                              | 200000 | 单任务预算总闸（自动验证模式 ×2.5）            |
| `max_task_tokens_cap`                          | 0      | 硬帽（0=关闭；>0 时限制信封上限，便于控费试跑） |
| `workflow_mode`                                | auto   | `auto` / `single` / `multi` 编队归一   |
| `module_mode`                                  | modular | `modular` 或 `monolith`（一体化模块） |
| `selftest_specs_enabled`                       | true   | 交付前自生成 Playwright 自测规格         |
| `model_routing_enabled`                        | false  | 难度分三档智能路由                       |
| `fast_triage_enabled`                          | false  | System-1 快判前置                   |
| `researcher_enabled`                           | false  | Researcher 前置调研                 |
| `docker_executor_enabled`                      | false  | 自动模式容器级沙箱                       |
| `enable_git`                                   | true   | 生成项目本地 git 版本管理                 |

完整参数见 `app/config.py`。

## 架构一览

```
需求（不可信输入 → 数据边界包裹）
  → [可选快判] 评估路由（三分类 + 难度分）
  → [可选 Researcher]
  → 组队 → 方案讨论 → spec 确认
  → 模块拆分 + 接口契约
  → 逐层开发（同层并发；写码 → 测试 → 门禁 → 执行）
  → 交付闸（冒烟 / 自测 / 机械审计 / 定向修复）
  → 交付物 + 成本看板
```

## Headless / CI 入口

适合自动化流水线或外部 runner（OpenAI 兼容网关，环境变量注入模型）：

```bash
OPENAI_API_KEY=<key> OPENAI_BASE_URL=<gateway> MODEL=<model> \
python main.py <requirements_dir> --output-dir <output_dir> --type web --mode auto
```

- 支持 `requirements.yaml` 树形需求摄取与可选参考图视觉转写
- 交付后分层验收 + 失败自动修复；`--resume` 断点续跑

## 安全与信任边界

用户需求、反馈日志、LLM 产出、联网摘要均按**不可信输入**处理。
自动模式默认 Docker 沙箱（资源配额 / 只读 / 无网络 / 非 root）；
**安全模式不执行任何生成代码**。

## 测试

```bash
python -m pytest tests/ -q                  # 全量 stub，无需密钥
cd vscode-extension && npm test
```

## 基准口径（诚实边界）

- **bench_v1（自建）**：10 类真实需求 greenfield，模块通过率约 71%、任务交付 10/10。
- **SWE-bench Lite**：环境适配域修复后同域样本可达约 60% resolved（仓库根 pytest
  口径，非官方 per-repo conda）；详见 `logs/bench_v1/` 与相关脚本说明。

## 发布

推送 `v*` 标签触发 GitHub Actions：pytest → PyInstaller → 体积检查 → Release 附 EXE。

## 文档

- [CHANGELOG.md](CHANGELOG.md) — 版本历史
- [v1.0.md](v1.0.md) / [v1.0-workplan.md](v1.0-workplan.md) — 1.0 规格与批次计划
- [docs/demo-script.md](docs/demo-script.md) — 演示脚本
- [文档目录.md](文档目录.md) — 文档索引
