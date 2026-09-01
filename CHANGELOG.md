# Changelog

## v0.5.0-beta · V0（进行中）

> v0.5 Beta 开篇：Researcher Agent 降级版闭环（M10-1~10-4）+ 可视化升级 V1（M11-1/11-2）+ 运维与推荐 V2（M11-3 / M12-1 / M12-5）。规划见 `v0.5.md` / `v0.5-workplan.md`；竞品基准分析更新至 v0.4 交付后版本。

### 新增（M10 Researcher Agent，规格第 4 章）

- **M10-1** Researcher 角色骨架（`app/agents/researcher.py`）：四段式结构化摘要（来源/版本/用法示例/已知坑点）；JSON 契约程序校验——sources/versions 强制非空（规格 19 章来源与版本标注），examples/pitfalls 允许空（宁缺毋编）；校验失败重试 1 次
- **M10-2** 触发器三条件：① 用户显式指定（`research="on"`）② 评估 reason 命中陌生技术栈信号词（`research="auto"` 时程序检测）③ 同一模块修复 ≥2 轮 → `research_suggestions` 仅建议不激活（4.5「由用户确认后激活」，总则 D.1）
- **M10-3** 知识注入链路：摘要经 `sanitize_untrusted` 数据边界治理（M7-6 同构）后注入 Dev/Test 全部提示词（写码/写测/修复）；摘要落盘 `sessions/research_brief.md` 留档；resume 重读注入不重复生成
- **M10-4** 独立预算与缓存：`research_budget_tokens`（默认 20k，独立于任务总预算，研究调用经 `call_log` 计入全局消耗日志）；`ResearchCache`（SQLite，键 = sha256(技术栈+API+版本+资料)，与 embedding 缓存同构，TTL 7 天）
- 新配置：`researcher_enabled`（缺省 False，关闭态行为与 v0.4 完全一致）/ `research_cache_enabled` / `research_cache_path` / `research_cache_ttl_days`（复用既有 `research_budget_tokens` 预留字段）
- API：`POST /api/tasks` 新增 `research`（on/auto/off）与 `research_material` 字段透传
- 提示词外化：`app/prompts/research_brief_system.md` / `research_brief_user.md`（M9 资源化惯例，fail-fast）
- 新增测试：`tests/test_researcher.py` 30 用例（契约校验/触发判定/预算熔断/缓存命中/注入边界/管线集成），全量 50 文件回归无回退

### 新增（M11 可视化升级 · V1 批次）

- **M11-1** 实时监控面板（`client.html` `sec-monitor`）：阶段耗时条形图（SSE 事件驱动，`monStage` 开段 / `monStageSettle` 末段结算）、token 累积曲线（SVG polyline，滚动窗口 60 点 + 峰值标注）、模块状态全景（`m-mods`，待运行/运行中/通过/失败四态）
- **M11-2** Agent 对话流图（`client.html` `sec-flow`）：讨论消息结构化记录（`orchestrator.py` `_record_message`：role/model/round/content，覆盖 pm → 双评审 → 修订 → 收敛全序列）；落盘 `sessions/discussion_messages.json`；API `GET /api/project/{id}/messages`（404 / 空 / 损坏 JSON 三种边界兜底）；前端纵向节点链渲染（角色配色 + 点击展开原文）
- 新增测试：`tests/test_discussion.py` 消息记录 5 用例（角色顺序/轮次编号/落盘/无 file_manager 容错）；`tests/test_api_server.py` 端点 4 用例 + 前端契约 2 用例（监控与流图区块存在性、消息端点引用）

### 新增（M12-1 / M11-3 / M12-5 · V2 批次）

- **M12-1** 任务取消与僵尸清理：`DELETE /api/tasks/{id}`——pending 立即取消（job 不执行）；running 协作式取消（取消旗标经 Pipeline 注入 BudgetGuard，`ensure_allowed` 检查点抛 `TaskCancelledError` 终止任务体，线程释放）；取消与完成竞态 → 用户意图优先标记 cancelled；`recover_zombies()` 服务启动时清扫磁盘遗留 pending/running 状态（服务重启 → 僵尸标记 cancelled）；client.html 任务运行时「取消任务」按钮 + cancelled 终态友好提示（非失败）
- **M11-3** 模式智能推荐：`GET /api/recommend?requirement=…`——确定性统计历史项目（词袋相似度 ≥0.25：需求文本 sessions/requirements.md、模式 pipeline_state.json、成本与完成态 logs/cost_report.json + interruption.md），输出 `{mode, budget_tokens, reason}`（成功率优先 → 平均成本 → 保守缺省；预算 = 成功样本均值 ×1.2 取整千位）；推荐理由引用数据（N 个相似项目 / 成功 x/y / 平均 token）；无 LLM 参与（D.1），client.html 评估阶段展示推荐（仅展示，模式下拉可覆盖）
- **M12-5** A/B 框架产品化：`scripts/ab_triage_eval.py` 新增 `--cases` 外置诉求集（JSON 数组，fail-fast 校验 cat/text/expect_single/expect_dual 与合法出口）；报告默认归档 `logs/ab_reports/ab_<时间戳>.json`（`--out` 可指定），报告含 `cases_file` 来源标注
- 新增测试：`tests/test_task_cancel.py` 11 用例（pending 即时取消不执行 job / running 检查点协作中止 / 竞态取消 / 404 / 409 / 僵尸清扫 / client 取消契约）；`tests/test_recommender.py` 10 用例（无历史缺省 / 成功率决策 / 平手取廉 / 不相关回退 / API 400/200 / client 契约）；`tests/test_ab_triage_eval.py` +9 用例（外置集加载与 fail-fast 校验 / 外置集跑套件 / 归档路径）

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
