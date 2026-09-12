# ARC-Bench 参赛规划（factory26）

> 更新：2026-09-11。本文档是参赛作战手册：赛制理解、提交契约、
> 模型策略、演练计划、风险预案、提交前检查清单。

## 1. 赛制理解

ARC-Bench（https://arc-bench.com）是软件工程智能体基准工作台，分三块：

- **Playground**：低压力草稿区，设计需求、检查基准结构、迭代 agent；
- **Competition**：正式计分赛（我们的目标）；
- **Research**：研究协作。

**任务形态**：平台下发 `requirements.yaml` 需求树（FOLDER/ATOMIC 两级，
ATOMIC 节点与 Playwright 端到端用例一一对应，"需求即测试"）。

**验收方式**：智能体交付真实可运行的 Web 应用，评测方以真实浏览器走
完整用户旅程（首页 → 注册 → 登录 → 搜索 → 业务操作 → 提交）。硬性契约：

1. 真实 HTTP 服务器监听环境变量 `PORT`（严禁任何 HTTP 模拟/占位打印）；
2. `GET /api/health` 返回 200；
3. 启动时初始化数据库 + 写入种子数据（精确字符串以 `tests/helpers.ts`
   夹具为准，生成侧须把该文件一并作为上下文）；
4. 前端由后端托管静态页（无需 Node 构建链），页面用 fetch 调真实 API。

**Usage Rule**：过程可视化只能通过官方 SDK（`arcbench_agent_runtime`）
上报——事件写 `.arc/runner-events.jsonl`，traceability 落
`.arc/traceability/*.json`，git 提交刷新预览。**禁止手工构造事件 payload**。

## 2. 提交契约（已对齐官方 Blank Template，2026-09-08 下载核对）

- 入口：`python main.py <requirement_path> --output-dir <dir> --type web`
  （`--type`/缺省路径兼容 `ARCBENCH_TASK_DIR`/`ARCBENCH_OUTPUT_DIR`/
  `ARCBENCH_TASK_TYPE` 环境变量）；
- 依赖：`requirements.txt` 含 `./arcbench-agent-runtime` 路径依赖
  （平台全新 pip install，SDK 必须随仓库提交）；
- 模型：runner 注入 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `MODEL`
  （OpenAI 兼容网关，单模型）。`main.py` 自动对齐 litellm 的
  `OPENAI_API_BASE` 并剥除代理环境变量（httpx trust_env 踩坑，见 §6）；
- 交付：`projects/arcbench-app_<ts>/code/` 下可运行应用 +
  `create_app()` 约定 + 交付后集成冒烟（import 全模块 + health 200）
  失败自动修复 ≤3 轮。

**平台网关**：`https://api.arc-bench.com/v1`（本地演练用；可用模型以
`GET /v1/models` 为准，当前 11 个：deepseek-v4-flash/pro、glm-5.2/5.3、
kimi-k3、minimax-m3、qwen3.6-flash/plus、qwen3.7-max/plus、qwen3.8-max）。

## 3. 我方管线映射（token-burner → ARC-Bench）

| 平台概念 | token-burner 实现 | 文件 |
|---|---|---|
| requirements.yaml | 需求树摄取：FOLDER→模块划分指令，ATOMIC→验收标准，helpers.ts→种子契约 | `app/arcbench_ingest.py` |
| 单模型下发 | `MODEL` → settings.models=[m] + single_model_mode（三角色同模补位） | `main.py` + `app/pipeline.py::_model_triplet` |
| 过程可视化 | Pipeline 事件 → SDK 翻译：interfaces_ready→契约登记+设计完成；module_done→实现/测试状态+git 提交 | `app/arcbench_bridge.py` |
| traceability | 需求树 / 接口（逐 export）/ 测试（每模块 pytest）三表登记，模块名→FOLDER id 模糊映射 | 同上 |
| Playwright 验收 | 组装模块契约（create_app + 全路由 + static 托管）+ 交付冒烟 + RepoFixer 自动修复 | `app/arcbench_smoke.py` |

## 4. 模型策略

平台单模型下发，三角色（主/开发/测试）同模运行。选型原则：
**代码能力强 > 便宜 > 快**（预算闸门 500k token/任务，超支即失败终点）。

| 候选 | 角色 | 备注 |
|---|---|---|
| `glm-5.3` | **首选（演练中）** | 代码/指令跟随强，中文任务包理解好 |
| `deepseek-v4-pro` | 多模型组队·开发副 LLM | 代码强；r6 探测 2.4-4.4s |
| `qwen3.8-max` | 多模型组队·测试副 LLM | r6 探测 2.2s（r4 夜间挂为网关拥塞，非硬封） |

**r6 探测（2026-09-12）：比赛 key 是多模型中转站**——单 key 直连全部
11 个模型全通（HTTP 200），三模型并发各自独立服务（7s 总耗时）。
已实现 `platform_multi_model` 开关（config.json，当前 **true**）：
注入 MODEL 任主 LLM，开发/测试副 LLM 取 config 预设互异者，恢复
产品三模型互异组队（PM+双评审多模型、开发/测试异模）；预设不足
自然回落单模型。✅ 规则口径已确认（组织方允许，2026-09-12）：
网关其他模型可调用，开关保持 true。

正式提交前至少完成：首选模型全流程绿（含冒烟 PASS）+ 一次断点恢复
（`--resume`）演练。

## 5. 演练计划

同构任务包：`.tmp/rehearsal/requirements/`（train-ticket 购票站，
4 FOLDER / 6 ATOMIC + `tests/helpers.ts` 夹具，与代码注释记录的平台
评测场景同构）。**目录布局注意**：`requirements/` 与 `tests/` 是
兄弟目录（`load_fixture_hint` 读 `req_dir.parent/tests/helpers.ts`），
夹具放错层级会静默丢失种子契约（r3 演练取证：搜索模块自造降级列表，
与 data_storage 种子不一致）。

```bash
OPENAI_API_KEY=<key> OPENAI_BASE_URL=https://api.arc-bench.com/v1 \
MODEL=glm-5.3 ARCBENCH_OUTPUT_DIR=<abs out> \
python main.py .tmp/rehearsal/requirements --output-dir <out> --type web --mode auto
```

### r3 演练结果（2026-09-11，glm-5.3，真实网关）

**全流程绿（79 分钟）**：评估 → 讨论（5 层护栏收敛）→ 拆分 5 模块
（auth / data_storage / train_search / booking / app_shell）→ 逐模块
写码-测试-门禁-修复循环 → _shared 回归 → 组装 → 冒烟 **PASS**。

- 平台事件流：101 事件（run_started → completed 全链）；
- traceability：31 interfaces（逐 export）+ 25 已实现标记 + 5 tests
  + node_states F1-F4（模糊映射生效）；
- 成本：**181,547 / 500,000 token（36%）**，讨论 47.9k / 开发 81.3k /
  测试 42.4k；
- 真实 HTTP 用户旅程 **8/8**：health 200 → 首页 Register/Login →
  注册 201 → 登录 + 会话 → 搜索 → 订票 201 "Order confirmed" →
  订单持久化（curl 全程，无浏览器）。

### 模型 A/B（r3 同任务包并行）

| | glm-5.3 | qwen3.8-max |
|---|---|---|
| 终点 | **成功交付 + 冒烟 PASS** | 失败（讨论阶段单调用 4 次尝试全部挂满墙钟 600s） |
| 墙钟防御表现 | 未触发 | 按设计快速失败，错误信息精确到原因 |
| 结论 | **正式提交首选** | 该网关侧暂不可用，提交前不必再试 |

### r4/r5 强化（2026-09-11/12）与实弹取证

**真浏览器验证（r3 交付站）**：注册→登录（Welcome 横幅+Sign out）→
搜索（结果表格）→ 订票（Order confirmed）→ My Orders（持久化）
五站全通，前端 fetch 流程真实可用，达到 Playwright 验收形态。

**交付验收 v2（verify_delivery 两段式）**：基础冒烟 + 旅程验收
（路由探测 → LLM 生成主旅程脚本 → compile 预检 → 危险扫描 → 执行；
失败先自修复脚本一轮，仍失败 RepoFixer 修应用，验证命令=旅程脚本）。
验收 FAIL = run_failed 终态，不再带病交付。首实弹即拦截一份
create_app 阶段崩溃的坏交付（旧链路会把它当成功交出去）。

**实弹暴露并修复的 P0**：
- **RepoFixer 无 .git 硬拒绝**：实现与文档（"无 .git 跳过 diff"）相
  悖，而平台入口 enable_git=False → 交付修复安全网在参赛路径恒为
  0 轮死路（r2 时代就如此）。已修：无 git 照常修复。修后同一份
  坏交付 2 轮修复通过（LLM 对 LocalProxy getattr 崩溃的修复质量高）。
- **单模型索引残留**：auto_repair 取 models[1]，单模型下发即
  IndexError（与首发 P0 同类）。
- **旅程脚本幻觉**：LLM 虚构路由表外端点（/api/register_routes）→
  修复循环把这些端点真加进应用（脚本幻觉与修复对齐互相强化）。
  硬化：compile 预检（语法不合格就地重生成，绝不冤枉应用）+
  提示词硬性规则（只走主旅程 5-8 步、路径逐字取自路由表、禁测
  内部端点）。
- **pycache 陈旧模块**：等长同秒覆写骗过 pyc 双重校验，验证跑到
  旧代码（29 字符 return↔raise 实证）→ 验证前强制清 __pycache__。

**--resume 生产验证**：手动硬杀 + 断点恢复 → 从快照正确重建 →
交付完成（completed.json）→ 新验收链路正确拦截缺陷交付。
恢复判据修复（快照且未完成；协作式中断优先）已随产线验证。

**网关长挂是真实风险**（两模型都出现单请求 >25 分钟）：防御
`llm_wall_clock_seconds=600`（main.py 兜底）是必备项，勿删。

验收锚点（全绿才算演练通过）：

- [ ] 网关预检 OK（`[gateway] preflight OK`）
- [ ] `.arc/runner-events.jsonl` 有 run_started → run_completed 全链
- [ ] `.arc/traceability/` 七表有数据（requirements/interfaces/tests 非空）
- [ ] `code/` 交付：create_app 可用、/api/health 200、静态页可走用户旅程
- [ ] `[smoke] PASS`（或自动修复后 PASS）
- [ ] 成本报告 ≤ 预算（auto 模式 500k token 闸门内）

## 6. 风险与预案（含已修复取证）

| 风险 | 状态 | 预案 |
|---|---|---|
| 单模型下发炸互异校验（Settings._validate + TeamBuilder._check_models） | **已修**（single_model_mode + _model_triplet，P2P 演练取证） | 回归测试 test_team_builder/test_model_routing |
| 沙箱代理变量劫持网关连接（httpx trust_env） | **已修**（main.py 剥除 HTTP(S)_PROXY/ALL_PROXY） | r2 彩排两次同因失败，勿回退 |
| 网关失败重试拖时间（6 次 × 15s 退避） | **已缓解**（预检用降配副本 1 次 + 15s 快失败） | 预检失败看精确原因再动 |
| 组装级缺陷（漏注册路由/静态页无人认领） | **已修**（交付冒烟 + RepoFixer ≤3 轮） | r2 演练取证 |
| 测试已引用符号被私有化 → 门禁震荡 | **已修**（interface_check 指引明示禁止） | M15-2/演练取证 |
| 预算超支（budget_exceeded 终点） | 监控中 | 演练记录各阶段 token 基线；必要时调 max_task_tokens |
| flask/werkzeug 版本地狱 | **已固化**（pin 组实测：werkzeug 2.0.3 全家桶 + setuptools 59.8） | 环境预检闸门（env_unverifiable 零 token 跳过） |

## 7. 提交前检查清单

- [ ] 全量 pytest 绿（当前基线 1099+，含桥接/组队/路由新测试）
- [ ] `.env` / secrets 不入库（.gitignore 已覆盖；key 只走环境变量）
- [ ] `arcbench-agent-runtime/` 随仓库提交（路径依赖必须可装）
- [ ] `main.py` 与官方 Blank Template CLI 契约逐字核对
- [ ] 演练 §5 全绿 + 产出留档（runner-events、traceability、cost_report）
- [ ] README/CHANGELOG 参赛章节更新（测试数、网关、演练结论）
- [ ] 平台 Playground 先跑一遍小任务确认 token 流转与面板刷新正常
