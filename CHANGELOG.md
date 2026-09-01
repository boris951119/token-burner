# Changelog

## v0.5.0-beta（2026-09-01）

> v0.5 Beta 全量交付：Researcher 降级版闭环 + 联网调研、可视化升级、运维与生态（镜像预热/主题/设置页/路由明细）、发布流水线。基线 v0.4.0-alpha（500+ 测试）→ 813+ 测试。

### 新增（M10-5 联网调研 · V5 批次）

- **M10-5** 联网调研通道（`app/agents/web_research.py`）：可配置供应商 duckduckgo（免 key）/ tavily（`TAVILY_API_KEY`），搜索结果确定性拼装为调研资料后进入 Researcher 生成环节（纯 urllib 零新依赖）；任何失败返回空串 → 自动回退用户资料注入模式（降级链路单一，任务不阻塞）
- 新配置：`researcher_web_enabled`（缺省 False）/ `research_web_provider` / `research_web_max_results` / `research_web_timeout`（供应商白名单校验，拼写错误尽早失败）
- 抓取文本沿用 `sanitize_untrusted` 治理（`Researcher._one_pass` 统一入口，M7-6 同构）

### 新增（M12 运维与生态 · V3/V4 批次）

- **M12-2** 镜像预热：`app/execution/prewarm.py` + `POST /api/prewarm`——python/node 镜像缓存校验（命中跳过 pull），报告逐镜像耗时与总耗时；client.html Docker 可用时提供「预热镜像」入口
- **M12-3** Docker 检测引导：`GET /api/docker/status` 三态（配置关闭 / 可用 / 未装降级）；client.html 可关闭横幅——未装显示安装指引并保持进程模式，可用显示预热入口
- **M12-4** 插件配置页：VS Code settings 新增 `tokenBurner.budgetTokens`（任务预算总闸覆盖）与 `tokenBurner.defaultModels`（三角色默认模型），设置变更即时生效；`defaults` 消息下发面板默认值（M12-10 契约测试发现并修复 webview 缺失 case 的协议缺口）
- **M12-6** 自定义路由策略：分档阈值从 orchestrator 硬编码迁入 config（`route_flagship_threshold`/`route_main_threshold`），config.json 可覆盖，非法值尽早失败
- **M12-7** 设置页重设计：新增「⚙ 设置」页签，四组分类（🎨 外观 / 🤖 模型 / 💰 预算 / 🛡️ 安全）；外观主题三选即时生效，安全组 auto 模式二次确认开关
- **M12-8** 深浅主题切换：浅色 token 双套（19 配色 + 2 阴影覆盖）+ `system→dark→light` 循环（顶栏 🌓）+ `prefers-color-scheme` 跟随系统实时切换
- **M12-9** 模型路由明细：call_log 档位标注（`tier_map` 旗舰/主力/轻量）→ cost_report 与实时看板新增 `by_tier`、逐调用档位列、实际成本 vs 旗舰假设成本对比（`model_prices` 价目表可配置，缺价 `available=false` 不误导）
- **M12-10** 插件消息协议契约测试（`vscode-extension/tests/contract.test.mjs`，Node 内置 runner 零依赖）：双侧源码提取 command 集合做闭合性断言

### 新增（M10-1~10-4 · V0 批次）

- **M10-1** Researcher 角色骨架（四段式结构化摘要 + JSON 契约程序校验，sources/versions 强制非空）
- **M10-2** 触发器三条件（显式指定 / 陌生技术栈信号词 / 修复 ≥2 轮建议不自动激活）
- **M10-3** 知识注入链路（`sanitize_untrusted` 边界治理 → Dev/Test 全部提示词；`sessions/research_brief.md` 留档，resume 重读注入）
- **M10-4** 独立预算与缓存（`research_budget_tokens` 默认 20k 独立 BudgetGuard；`ResearchCache` SQLite TTL 7 天）
- 新配置：`researcher_enabled`（缺省 False，关闭态行为与 v0.4 完全一致）；API 新增 `research` / `research_material` 透传

### 新增（M11 可视化 · V1 批次）

- **M11-1** 实时监控面板：阶段耗时条形、token 累积曲线（SVG）、模块状态全景
- **M11-2** Agent 对话流图：讨论消息结构化记录 + `GET /api/project/{id}/messages` + 纵向节点链渲染
- **M11-3** 模式智能推荐：`GET /api/recommend` 确定性统计历史项目（词袋相似度，成功率优先 → 平均成本 → 保守缺省，零 LLM 参与）

### 新增（M12-1/M12-5 · V2 批次）

- **M12-1** 任务取消与僵尸清理：`DELETE /api/tasks/{id}` 协作式取消 + `recover_zombies()` 启动清扫
- **M12-5** A/B 框架产品化：`--cases` 外置诉求集 + 报告归档 `logs/ab_reports/`

### 新增（M13 发布 · V5 批次）

- **M13-1** GitHub Actions 发布流水线（`.github/workflows/release.yml`）：push `v*` 标签 → pytest 全量回归 → PyInstaller 构建 → 产物体积检查（≤80MB）→ Release 附 EXE
- **M13-2** 版本号 `app.__version__` 升至 `0.5.0-beta`；本条目即发布 CHANGELOG

### 测试

- 新增：`test_researcher.py`（30）/ `test_discussion.py`（5）/ `test_task_cancel.py`（11）/ `test_recommender.py`（10）/ `test_ab_triage_eval.py`（+9）/ `test_api_server.py`（+6）/ `test_v3.py`（9）/ `test_v4.py`（25）/ `test_v5.py`（13）/ 插件契约测试（4）
- 全量回归：813 passed / 7 skipped（v0.4 基线 500+ → 813+）

## v0.4.0-alpha（2026-08-31）

> 核心能力补全：IDE 集成、容器级沙箱、并发架构、意图双模式、智能路由与缓存、桌面端 UI。基线 v0.3.1（472+ 测试）→ 500+ 测试。

### 新增

#### M9 双模式意图识别（System-1 / System-2）
- **M9-1/9-2** 快判契约与 FastTriage 前置接入 TaskRouter：轻量模型快判 `{intent, confidence, reason}`；高置信闲聊/无意义 → declined、基础 → 直答；编程/研究·分析/低置信/边界信号 → 升级 System-2；任何异常静默降级（失败方向单一）
- **M9-3** declined 出口语义：附友好文案，CLI / API / client.html 三端适配
- **M9-5** System-2 评估调用固定降档主力档（复用 M3-1 分层）
- **M9-4** 快慢双模式 A/B 评测框架（`scripts/ab_triage_eval.py`：标准诉求集 20 条，token / 误判率 / 延迟三维对比 + KPI 判定；真实运行 `--real` 需密钥）
- 新配置：`fast_triage_enabled`（缺省 False，行为与 v0.3.1 一致）/ `fast_triage_model` / `fast_triage_confidence_threshold`

#### M8 服务端并发架构
- **M8-1/8-2** ModelClient 任务级隔离（`ModelClientFactory` 每任务独立实例）+ `ProjectLockManager` 项目级锁（替代全局串行锁）
- **M8-3** 异步任务 API：`POST /api/tasks`（kind=run/resume/feedback）提交即返回 task_id；`GET /api/tasks/{id}` 状态查询；任务状态落盘 `sessions/task_state.json`（服务重启可恢复）；线程池并发 ≥4
- **M8-4** SSE 进度事件流：`GET /api/tasks/{id}/events`（首帧快照 + 增量事件 + 心跳保活，断线重连）
- **M8-5** 全局 LLM 限流器：令牌桶按供应商排队；429 退避复用 9 章重试

#### M2 Docker 沙箱
- **M2-1/2-2/2-3** DockerExecutor：卷挂载传输、超时熔断、只读文件系统、无网络（可配置）、非 root 运行；Docker 不可用自动降级进程模式（safe 模式完全不受影响）
- **M2-4** 资源配额：`--memory/--memory-swap/--cpus/--pids-limit` + tmpfs 磁盘上限；超限 exit 137 → FAILED 语义
- **M2-5** 多语言镜像：Node.js 运行时（`node:20-slim` + 内置 `node --test`，TS 支持预热）；`language` 配置参数与 `docker_node_image` 配置项

#### M1 VS Code 插件
- **M1-1/1-2** 插件脚手架 + 任务发起面板（需求/模型/模式选择，服务未启动时终端一键引导）
- **M1-3** 实时进度：SSE 事件流消费 + 轮询兜底（阶段/进度条/执行日志）
- **M1-4** 生成代码预览与应用：diff 预览、应用全部/逐文件（Workspace Edit API，可 Undo）
- **M1-5** 成本统计：预算进度条（≥90% 转红）、按模型明细、节省量指标
- **M1-6** 历史任务列表：「项目」Tab（需求摘要/模式徽章/token/更新时间）
- **M1-7** 中断恢复：中断标识 + 一键续跑（异步任务通道）

#### M3/M4 智能路由与上下文缓存
- **M3-1/3-2** 三档模型分层（旗舰/主力/轻量）+ 按难度动态选模（`model_routing_enabled` 缺省关）
- **M4-1** Embedding 缓存层（SQLite，键 = 内容 hash + 模型 + 维度，7 天过期）
- **M4-2/4-3/4-4** 论点库持久化、`_shared` 公共模块缓存、缓存命中率看板

#### M5 桌面端 UI（client.html）
- **M5-1** 设计规范与组件库：design tokens 全套（配色/字体/间距/圆角/阴影/动效/焦点环）+ 通用组件 class（按钮/卡片/进度条/徽章/气泡/弹窗/日志区），旧类名兼容别名零破坏
- **M5-2** 工作台/项目库双视图：快速模板、历史项目列表（继续续跑/看板回填）；新增 `GET /api/projects` 端点
- **M5-3** 执行页切异步任务 API：SSE 事件驱动时间线 + 实时日志区 + token 实时面板

#### M6/M7 成本与工程质量
- **M6-1** 成本看板新增「已节省 Token / 节省比例 / 缓存命中率」
- **M7-1** 集成测试：4 路并发压测（`tests/test_integration.py`：提交隔离/终态/续跑语义）
- **M7-2** 性能基线脚本（`scripts/perf_baseline.py`：标准任务集 × 固定剧本，token/耗时/成功率可复现对比）
- **M7-3** PyInstaller 打包 spec 就绪（含 `app/prompts` datas 同步）；EXE 构建与体积/冷启动验收须在用户环境执行 `pip install pyinstaller && pyinstaller token-burner.spec`
- **M7-6** 需求注入面防护：`_sanitize_untrusted` 公共模块接入全部 requirement 插值点 + 注入回归用例

### 变更
- 执行器工厂 `build_executor` 支持多语言参数（缺省 python 行为不变）
- 服务端新增只读端点：`GET /api/projects`、`GET /api/project/{id}/files|file`
- 旧同步 API（/api/route、/api/run）保留兼容

### 已知边界
- 快判的 JS 静态扫描属 v0.5 TS 支持范围（node 运行时首道防线为容器级隔离）
- M8-6 任务取消 / M2-6 镜像预热 / M2-7 Docker 桌面引导 / M3-3 路由 A/B 框架 / M3-4 自定义路由 / M5-4/5-5 / M6-2 / M7-5 发布流水线（P2）顺延

### 升级说明
- 从 v0.3.1 升级：无需数据迁移；全部新能力缺省关闭，行为与 v0.3.1 完全一致
- 启用新能力：`fast_triage_enabled` / `docker_executor_enabled` / `model_routing_enabled`（建议先跑各自回归验证再灰度）
- VS Code 插件：`vscode-extension/` 目录 sideload 安装，需本地 `python -m app.server` 运行（≥ 本版本，支持异步任务 API）
