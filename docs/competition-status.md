# 竞赛备战状态快照（供会话压缩后续接）

更新时间：2026-09-20 02:30（北京）

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
