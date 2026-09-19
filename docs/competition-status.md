# 竞赛备战状态快照（供会话压缩后续接）

更新时间：2026-09-19 22:55（北京）

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

- **local_loop 首跑**：本地生成 Keep（带 UI 双杠杆）→ 官方 32 题评分
- 进度（22:50 实测）：16:56 发车，全部模块 20:07 完成 → 验收 R0 结束 →
  R1 锚点修复（20:18-21:29，home/notes/seed_data/settings/view 活跃改写）
  → **R1 旅程修复中**（22:17 仍有写入，跑健在）
- 输出目录：`.tmp/local-loop-keep-ui1-0919-1656`
- 评分报告：`scripts/official_grade/grade-summary.json`
- 后台任务 ID：exec_f5951d1b-1dd4-4989-a54b-283086e63a1c（完成会通知）

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
