# 竞赛备战状态快照（供会话压缩后续接）

更新时间：2026-09-20 06:15（北京）

## 🚀 v7 双任务已发车（比赛首次有效提交）

- **Submission**: token-burner-v7 = `69803db8196e`（197 文件产品包，
  含今夜全部修复；API Key=中继 key，model 默认 flash）
- **Keep run**: `6d980799bdff`（06:05 发车）
- **BookStack run**: 容器 arcbench-4e3ba21e9f41-g1 已启动（06:12）
- 预计 5-6h → **中午 11:00-12:30 出分**；同 submission 双任务=资质有效
- 平台时区注意：服务器时间是 UTC（22:10 = 北京 06:10）

## 本地迭代成果（一夜链路）

0/32 → 1/32 → 3/32 → **5/32**（REQ-1.1 / 2.1 / 2.3.2 / 5.1 / 5.2）
项目 checkpoint：`.tmp/local-loop-keep-ui1-0919-1656/projects/arcbench-app_20260919_165658`
（git 检查点到 repair v4 aftermath）

## 夜间修复清单（全部提交入库）

1. af45039 看门狗误杀修复（验收期刷新 LAST_PROGRESS）
2. fd146b8 评分器输出全量落盘 + 5dece91 BookStack 34 真题本地化
3. 487fc24 三连：库路径统一 fixer / 锚点垃圾过滤 / UI 全局硬契约
4. bba203e RepoFixer 语法自证拒收垃圾写（flash 毁文件取证）
5. bb52e5e official_probe（官方真题当修复验证信号）+ 评分解析修复
   （`passed` 不是 `expected`——真实分曾被报成 0）
6. build_submission.py：v7 一条命令出包（基线清单+缺失回补）

## 根因链（平台 0 分病灶全破）

库文件分裂（seed 写 take_a_note.db / API 读 keep.db）→ 机械 fixer ✓；
内存假后端（_NOTES=[] 不接库）→ 持久化改造 ✓；UI 中文+markdown 星号
→ 英文化 ✓；首页 mockup 不接数据 → 官方真题驱动修复迭代 ✓

## 08:00 接管后待办

1. 等 Keep/BookStack 出分（runs 页面查），对照本地 5/32 判读
2. feature_rate 核对（平台 traceability 维度是否 >0）
3. 出分后继续本地迭代（下一批挂点：More options 菜单/标签管理/搜索
   高亮/设置页——错误信息都直给定位器）
4. BookStack 本地彩排（评分侧已就绪：--task bookstack）
5. 竞赛日 playbook 固化

## 评分进展（凌晨迭代链）

- 首评 0/32 → 三层根因修复（见下）→ **真实分 1/32**（REQ-1.1 Enter
  Website 通过；此前被评分解析 bug 报成 0——Playwright JSON 状态字面量
  是 `passed` 不是 `expected`，bb52e5e 修复）
- UI 已全英文 + Take a note button + 无 markdown 污染（外科 v2 达成）
- 剩余根因：**home.py 是硬编码 mockup**（6 张写死卡片+假工具栏），
  与完整可用的 API 层（增删改查/pin/archive/labels/undo/settings 全就绪）
  完全脱节；view.py 里有半成品动态页可参考
- **修复 v3 在跑**（exec_84a33d75，04:20 发车）：auto_repair 的验证信号
  换成官方真题本尊（scripts/official_probe.py：导出→起服→跑 4 道代表
  真题 REQ-2.1/2.2/2.8.1/2.3.1），pro 主帅锁定，修完自动全量评分

## 出分决策树（06:30 硬停前无人值守执行）

- **≥8/32** → 重建 v7 包（scripts/build_submission.py 一条命令）→
  比赛页「Save an agent snapshot」表单上传（合成 DataTransfer 注入 zip
  字节 + 填名称/API Key → Save）→ Keep+BookStack 双任务发车
- **1-7/32** → 有分就交（平台有分 > 空手）；提交动作同上
- **0/32** → 不交，8 点带完整诊断汇报
- 提交表单字段：Submission name=token-burner-v7；Base URL 默认；API Key=
  比赛中继 key；Model 保持默认（我们的 config.json 随包覆盖）

## 本地官方 32 题首评：0/32——三层根因全部取证并已修

凌晨评分（exec_73fb38a1 链）结果 0/32，verify_final ok=False。逐层根因：

1. **库文件分裂**（机械已修，487fc24）：db_core 读写 instance/keep.db，
   seed_data 把种子 INSERT 进相对路径 take_a_note.db——种子永远进不了
   API 的库。新 fixer `fix_db_path_unify` 已统一（4 单测）。
2. **内存假后端**（修复中）：notes.py 用模块级 `_NOTES=[]` 列表当存储，
   API 根本不读库（库里 38 行含 Sprint goals，/api/notes 永远返回 []）。
   journey 三轮 LLM 修不动——架构级缺陷非语句级。
3. **UI 中文 + markdown 污染**（修复中）：界面"我的笔记/搜索笔记…"，
   按钮渲染成 "**Settings**"（星号成字面文字）；官方 32 题全部用
   `getByRole('button', {name: /take a note/i})` 英文 ARIA 语义定位
   ——中文 UI = 全部找不到 = 0 分。composer 是 "+ Create" 不是
   "Take a note" button。

## 产品加固（今晚已提交）

- af45039 看门狗误杀修复（验收期 LLM 修复刷新 LAST_PROGRESS）
- 487fc24 三连：库路径统一 fixer + 锚点垃圾 token 过滤（'<模块名>'/
  正则残渣空烧 3 轮）+ inject_ui_manifest 全局硬契约（英文 role 匹配/
  禁 markdown 星号/禁内存假后端/单库文件）
- fd146b8 评分器 playwright 输出全量落盘 grade-run.log
- 5dece91 BookStack 34 真题本地化 + PLAYWRIGHT_TEST_DIR 任务开关

## 当前在跑（后台 exec_4f988d64，02:00 发车）

`.tmp/repair_ui_store.py` 外科手术修复（探针 ui_store_probe.py 作验证
信号：API_SEED + UI_ANCHOR + UI_MARKDOWN + UI_LANG 四闸）→ 修完接
官方 32 题评分（无论修复成败都出分）。预计 03:30-04:30 出新分。

## 出分决策树（无人值守执行）

- **≥8/32** → 从当前 HEAD 打 v7 zip（产品包 197 文件布局，参考
  token-burner-submission.zip 16:22 版；非 frontend/backend 布局）→
  浏览器会话上传新 submission → Keep+BookStack 双任务并发发车
  （平台跑 5-6h，压 8 点接管前出分）
- **1-7/32** → 再来一轮外科修复（同探针）→ 复评；06:00 硬停前
  有分就交
- **0/32** → 不交（白烧 ¥100），8 点带完整诊断汇报
- 上传通道：平台 /api/submissions 需登录态，ak_ key 不认（409 实测）；
  备选=浏览器页面内 fetch（用户会话 cookie 在 IAB 标签里）；
  IAB 文件选择器不可自动化，若表单是 file input 需走 API 路径

## 比赛规则（已钉死）

- 赛事：arc-bench-lite，**只有 2 个任务**：Keep（32 题）+ BookStack（34 题）
- **资质规则**：必须用**同一个 submission** 跑完两个任务才有累计分（is_complete）
- **评分双维度**：avg_pass_rate（测试通过率）+ avg_feature_implementation_rate（功能实现率，来自 traceability 登记）
- 成本效率 = 通过率/token 花费，阈值 80（头部选手用自有 key，我们决定继续用平台 key）
- 时间窗：9/10-9/10/2036，但用户目标初赛 9/21-9/30

## 平台运行状态（9/19 17:30 实时核对修正）

| Run ID | 任务 | 提交 | 状态 | 结果 |
|---|---|---|---|---|
| 5d21c4bcdac7 | Keep | v6-3 (95c2b02cdb17) | **FAILED（已评分 0/32）** 14:28 结束，¥45.66/214万token | 占位壳+隐藏塞串，反作弊三件套已修 |
| 1135c9109e07 | Keep | v6-2 | FAILED exit 1（交付策略修复前，未评分） | 尸检发现占位壳+塞串 |
| 7db882d27b0f | Keep | v6 | FAILED 0/32（文案翻译+占位壳） | 已评 0 分 |
| 8af4f8462b02 | BookStack | v6 | 已删除（原 PAUSED，占槽位） | —— |
| 747441cac95a | BookStack | v6-1 | CANCELLED（用户停止） | —— |
| 69c5ede2816b | Keep | v6-2 | PENDING（我建的排队跑，用户可删） | —— |

**勘误**：本文件此前把 5d21c4bcdac7 写成"RUNNING 预计 15:00 出分"——
是过期记忆，该跑 14:28 已完成并评分 0/32（用户指出后核对修正）。
教训：状态快照必须实时查询，禁止凭记忆落盘。

## 本地任务（后台运行中）

- **local_loop 首跑**：生成 391 分钟全部完成（completed.json 20:07），但
  **验收尾段 23:27 被看门狗误杀**（rc=75：只认 Pipeline 阶段变更的
  LAST_PROGRESS，验收期 5 小时活跃修复被判「200 分钟无进展」）
- **已修复**（af45039）：_beat + 每次 LLM 响应完成均刷新 LAST_PROGRESS
- **已续跑**（exec_73fb38a1，23:34 发车）：resume_verify.py 验收收尾
  → local_loop --grade-only 官方评分（FAIL 也评分）
  ⚠️ completed.json 项目走不进 main.py --resume（keep7 取证），
  必须用 resume_verify.py
- 项目：`.tmp/local-loop-keep-ui1-0919-1656/projects/arcbench-app_20260919_165658`
- 评分报告：`scripts/official_grade/grade-summary.json`

## 9/19 晚间加固（已提交）

1. **fd146b8**：local_grade playwright 输出全量落盘 grade-run.log +
   无报告时带 GRADE_REPORT 路径；验收修复环逐腿心跳打点
   （修复 20:07→21:29 的 82 分钟心跳静默盲区）
2. **5dece91**：**BookStack 34 真题本地化**（specs/bookstack/）+
   PLAYWRIGHT_TEST_DIR 任务开关——9/20 彩排命令就绪：
   `python scripts/local_loop.py --requirement .tmp/arcbench-official/arc-bench/webapp/bookstack/requirements --task bookstack`
3. **排雷结论**：15:5x「无评分报告」= 当时带自定义 --report 路径跑尸体评分
   （现场 scripts/official_grade/scripts/official_grade/grade-report-v63.json），
   非基础设施缺陷；08:23 同版本脚本正常出报告
4. **教训**：Git Bash `python` = 无 flask 的系统 Python，跑测试/脚本
   必须用 `.venv/Scripts/python.exe`（全量 1309 passed, 7 skipped）

## 产品已修复清单（全部提交入库）

1. **交付策略**：验收 FAIL 也照常交付评分（exit 1 = 不评分 = 0 分教训）
2. **布局适配**：交付自动导出官方 frontend/+backend/ 布局（platform_export.py）
3. **锚点门禁**：可见文本匹配（反隐藏塞串）+ Seed data 优先 + ≤6 词可满足形态 + 修复用探针验证 + 非交付闸
4. **契约同步**：接口门禁纯 extra 失配机械同步（零 LLM 轮）
5. **建表接线冒烟**：DDL 声明表 vs sqlite_master 比对，缺表 FAIL 点名
6. **模型链**：墙钟 600s + 超时换腿不重试 + UI 模块主帅模型路由
7. **UI 双杠杆**：页面清单契约注入拆分层 + UI 模块主帅写
8. **本地基础设施**：local_loop.py（生成+评分一条命令）、local_grade.py（官方真题评分器）、官方 32 题已本地化
9. **工作台 403**：client.html + desktop.py 令牌接线（用户白天实测问题）

## 核心结论（用户质询已回答）

- 平台 0/32 根因：UI 占位壳 + 隐藏 textarea 塞串骗过锚点探针 + 修复指令教唆占位页——已三层修复（可见文本匹配/占位页禁令/建表接线冒烟）
- 指令→理解→实现的归因：指令到位、理解正确（spec.md 优质）、**断点在实现层**（flash 写不出完整 UI）
- 修复方向：UI 双杠杆（清单契约 + 主帅写 UI）+ 本地免费迭代

## 下一步（按序）

1. local_loop 出分后判读：对照平台 0/32 基线，≥20/32 达提交线
2. 达标 → 上传 v7 zip，**同一 submission 跑 Keep + BookStack 双任务**
3. 不达标 → 本地迭代（改提示词/轮次/模型分配）→ 再本地评分，直到达标
4. BookStack 正赛第二战 + TrainTicket 跨域泛化验证
5. feature_rate 验证：下一次必评分的跑核对 feature_implementation_rate 是否 >0

## 关键数字

- v5 平台跑：¥215/1100 万 token/个（6 个并发烧了约 ¥1300）
- v6-3 平台跑：¥46/214 万 token（flash + 墙钟收紧，省 67%）
- 本地生成：同 token 成本，但失败可免费重跑
- 提交线目标：本地 ≥20/32

## 参赛须知判读（9/21 官方 PDF，来源用户）

### 硬事实（修正此前假设）
- **初赛 9/24 0:00 ~ 9/30 23:59**（此前以为 9/21 开闸）→ 9/21-9/23 是黄金准备期
- **正式测试用例隐藏**，public-exercise 只是对齐参考 → 需求忠实实现 > spec 逐字拟合
- **正式评测用平台内置 key**（不传自己的 key），消耗记队伍 500¥ 比赛券
- **不限提交次数 + 历史最高分**（此前"每任务≤2次"作废）；同队不能并发两次正式评测
- 练习券 100¥×5 次（= 本地用的 ak_ key，额度低自动补）；单任务上限 48h
- 榜单前 20 晋级决赛

### 计分公式（b₀=1.2, α=0.1, β=0.2）
S(p,b)：p=双任务合计通过率%；b=双任务总开销。b≤1.2p 时奖励区
（S 可高于 p），b>1.2p 惩罚区。例：p=90 时预算 108¥，花 90¥ 得
≈92.3，花 150¥ 得 ≈84.3——**成本纪律值约 8 分**，flash 为主配置
（~46¥/任务）正好在奖励区。

### 合规红线（审核=自动+人工）
- 预置文件禁止含任务特定页面/业务逻辑（BookStack/Keep 页面严禁进包）
- 契约规则必须保持框架级通用（现有 secret_key/转义/匿名语义规则合规）
- 智能体必须真实调用大模型；禁止复制预制任务答案

### 官方本地模拟环境对表审计（hackathon-local-simulation，已克隆 .tmp/）
- ✅ 智能体入口契约：ZIP 根 main.py+requirements.txt，
  `python3 main.py <requirements_dir> --output-dir <dir>`——v7 包已合规
- ✅ 部署布局：frontend/+backend/ 标准路径——v7 生产 runner 实证可达
- ⚠️ **deploy.sh 契约是本地模拟器独有**（example 明确警告 production
  runner 没有）——正式提交不得依赖，未采用
- ✅ 模型注入：runner 下发 OPENAI_API_KEY+OPENAI_BASE_URL+MODEL
  （litellm 原生识别，单模型模式 main.py 已支持）；视觉走
  VISUAL_BASE_URL/VISUAL_MODEL（vision.py 已读取）
- ✅ template/ = 官方通用 Express+React 脚手架（须知明示允许）
- 本地模拟计分与正式同公式；正式双任务先汇总再计分

### 9/24 前行动表
1. 彩排出分（跑中）→ ≥20/34 即具备 v8 冻结条件
2. 用官方本地模拟环境跑一次完整 v8 模拟提交（需 Docker Desktop）
3. 9/24 开闸尽早发第一个正式提交拿基线分，之后本地迭代+再次提交
4. 提交节奏：¥500 ≈ 3-5 次双任务提交，每次间隔本地迭代

## 官方容器彩排对表（9/23，shape-mini 四需求题，解包后的提交包实跑）

两跑都是「submission zip → tb-shape 镜像（python:3.11-slim，无 node/git）→
容器内 main.py 全流程」，即判分容器同形态；容器内日志时间戳是 UTC（本地 = +8），
下表起跑时刻一律按本地。

| | run A（v15 包，12:36 起跑） | run B（v20 包，16:47 起跑） |
|---|---|---|
| rc | 0（带坏交付） | 0 |
| 墙钟 | ~3.5h | ~1h24m |
| cost_report total_tokens | 624,234（47 次调用） | 330,462（33 次调用） |
| 总闸口径 | 883,398 / 880,000 撞信封 | 未撞 |
| 导出 | 验收后才落盘 | 抢先交付 11 文件 → 最终 15 文件（#25 顺序修复生效） |
| 修复环 | 3 轮瞬时 raise 在同一行预算耗尽 | 机械修复 import 路径漂移×2 生效；无进展止损首次触发 |

两个口径必须先分清（`_build_dashboard` 只吃主客户端的 `call_log`、且只在管线末落盘）：
**cost_report 是「生成段主通道切片」，总闸才是整跑实花**。run A 的
883,398 - 624,234 = 259,164 就是报告射程外的部分（验收/修复段的零散客户端）。
官方计分的 b 按 key 真实扣费走＝总闸口径，所以成本纪律只能盯总闸读数。

同口径可比的增量在环节切分上：

| 环节 | run A | run B |
|---|---|---|
| 方案讨论 | 152,953 | 126,303 |
| 拆分接口 | 17,956 | 18,370 |
| 开发 | 89,721 | 77,796 |
| 测试 | **363,604（58%）** | **107,993（33%）** |
| output 合计 | 478,359 | 240,172 |
| 调用次数 | 47 | 33 |

注意 v15→v20 之间压了 9 个提交（批次#30~#38），所以整跑 -47% 不能全额记到某一条
头上。能单独立据的是「阶梯重试」本身——把两次 call_log 按 (model, stage,
input_tokens) 归组，取 output 呈 8000→16000→24000 爬升的重复组、扣掉每组第一次：

- run A：5 组、空烧 **184,000** output token（全部落在 `glm-5.3 / 测试`，占该跑记录量 29%）
- run B：1 组、空烧 **16,000**（同一条腿同一环节）

#38 的效果读数就是这一条，其余差值归到批次#34/#36 的口径收口（红字变少→修复轮变少）。

三处结论值得钉住：

- **推理模型的「吃满 max_tokens」是会重复发生的**：同一入参在 `glm-5.3` 上
  连着三次撞上限，翻倍重试只陪一档、每模型一次的封顶把 5 组压成 1 组。
- **run B 不是修复环的干净对照**：R1/R2 两轮 LLM 修复各自死在
  `litellm.RateLimitError: Free allocated quota exceeded`（三模型皆然），
  修复通道未被行使过一次——只有 build 阶段的时序与成本读数可用。练习券额度已打空，
  且官方口径是「开闸时清零、另发 500」，所以存额度没有收益。
- **成本可见性还差一段**：报告射程外的 259k 无人认领。但运行时的节流/止损判定读的
  是总闸（口径正确），官方扣费也是总闸口径，所以这个盲区只影响我们离线看账——
  **不动提交包**，需要时在本地用 `guard.used_tokens` 对表即可，别为一个零分收益的
  改动烧掉一次单变量上传名额。

### runA 全红的真死因（批次#42 定位，9/23 夜）
不是预算、不是模型链，而是**生成器写模板继承就不写父模板**：本机 13 份带模板交付里
用到 `{% extends %}`/`{% include %}` 的有 3 份、指令 12 条，其中 **10 条指向从未
生成的模板**——runA 那份 6 条全悬空（六个页面各 extends 一个不存在的 `base.html`）=
每页 500 = 判分面整片归零；9/20 那份 5 条里 4 条悬空。唯一一条能解析的继承来自 runB，
也就是说这道坎完全取决于模型当天有没有想起来要写父文件。
已两处收口（零 LLM 摘除 + 生成侧规则），提交 1b06ebe 与其后的取证数字更正。

### 预算信封标定的读法（避免把 run A 误当系统性缺陷）
`size_aware_budget` = base 800k + 20k/条（封顶 3.5M）。run A 撞的 880,000 是
四需求题面的小信封，而单轮修复实测要 ~280k，所以「总闸被打穿后修复环零进展
照烧墙钟」是小分母题面的特有形态；32 需求题面的信封是 1.44M，已知最重交付
keep=537k（余量 2.7x）、bookstack=1.19M（1.2x），修复保留额 25% ≈ 360k 高于
单轮修复成本，不会被前置阶段吃空。**不改标定**，只保留 #29b 的阶段隔离与
`_repair_blocked()` 的开工前体检（钱不会在修复途中变多，判一次就够）。

### 待上传候选
v27（202 文件 541KB，合规自检通过）＝v26 文件集逐名一致，内容差异只有两处
（`app/utils/auto_fixer.py` + `app/agents/module_builder.py`，批次#42 悬空模板继承）。
递进链：v25（#40 判分红字挂死因）→ v26（+#41 修复落点守卫）→ v27（+#42 悬空继承摘除）。
四读复验全过：文件集与 v26 逐名一致、内容差异仅上述两文件、py3.11 容器内 93 个源文件
compileall rc=0、官方形态容器（tb-shape:runA-mini，真 Flask）里用**包内代码**复放
runA 交付：修复前 0/6 页可渲染（`TemplateNotFound: base.html`）→ 修复后 4/6 且
列表/表单/搜索三页正文可见，与本机读数逐字一致。
上传节奏按「每次只改一件事」：若开闸后要先拿干净基线分，v27 是首选（三条都是
零 LLM 的确定性收口，不改模型链与预算）；若要逐条归因，v25/v26/v27 的回退顺序已记在这里。
