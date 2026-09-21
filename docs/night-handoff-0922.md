# 9/21 深夜交接（面向 9/22 早判读）

## 一句话现状

官方 lite 双题冷启动彩排：bookstack 6/34（已知）、**keep 3/32（真实分，22:55 出）**；
stackoverflow（66 需求）生成中（22:28 发车，预计 5-6am 出分）。v8 提交包已就绪合规零残留。

## 今晚三个根因（全部已定位，两个已修）

### 1. keep 全站 500：接口漂移一个下划线（生成质量缺陷，未修——等审计器）

`interfaces.json` 里 3 处 `init_app` + 1 处 `init_db` 自相矛盾；实现侧写成 `_init_db`（私有），
views 按契约调 `init_db()` → 每个请求 before_request 里 AttributeError。
验收发现了但停在「尽力交付」，修复器修不动跨模块符号漂移（与修复环短板同源）。
已手工加一行公共别名让 keep 能评分（.tmp/.../arcbench-app_20260921_200508/code/data_layer/data_layer.py）。

→ **D 线第一优先：属性级接口审计器**（零 LLM）：扫描全部 `X.attr` 调用点 vs 模块 X 实际
顶层 def，含前导下划线隐私错位；并审计 interfaces.json 自身一致性（契约内两名并存即报）。

### 2. keep 种子全靠编造（生成质量缺陷，未修——等提取器）

官方 requirements.yaml 每节点带逐字种子声明（`Seed data: pinned note "Sprint goals" and
regular note "Groceries"`），生成器只捡到零星（"...existing" 后缀那批），主种子
（Sprint goals/Groceries/Project ideas/Travel plans/Delete me 2.3.x）全靠 LLM 编造
（实种 "Call dentist existing"/"st" 等脏数据）。REQ-2.x 整簇 16 项因此落空。

→ **D 线并列第一：种子声明提取器**（零 LLM）：ingest/拆分期 regex 抽取全部 `Seed data:`
子句逐字注入数据层模块契约 + 生成后审计每个声明名在 seed/DB 中非空。价值 ~13 keep 测试。

### 3. 评分基建双洞（已修 19c2f78）

- local_loop 起服失败读陈旧 grade-summary，把 bookstack 旧 6/34 打印成 keep 成分（已加 rc=2 不读 summary 闸）
- local_grade 起服子进程 stderr 进 DEVNULL，500 根因无现场（已落 app-boot.log + 尾 12 行直出）

## 修复环判读（晚间已结案）

两轮修复 6/34 零提升，第 1 轮修复把 main.py 重写成蓝图片段 + 幻觉 `import infra` 毁入口，
终评 rc=2 连败循环带损毁态崩溃。加固已提交（c9bd19f：起服预检闸/回滚后再抛/修复段日志），
彩排项目已回滚到 6/34 状态。**结论：分数杠杆在生成期契约，不在修复期。**

## B 线成果（已就绪）

- v8 包 `token-burner-submission-v8.zip`：201 文件，新模块全进包（新清单=基线∪git 跟踪文件），
  合规 grep 零残留（12 处题目专名/题量注释已泛化，cb028e6）。**随时可提交平台。**
- Qoder 交叉审查 4 高危全部修复（4f1c7ba）：requirements p.stem、resume 护栏登记、
  回滚备份断言、FastAPI 冒烟守卫。

## 情报勘误

官方 4 大题全在本地 `.tmp/arc-bench-repo/arc-bench/webapp/`：stackoverflow 66 /
prestashop 86 / 12306 117 / ctrip 125，requirements 全 GIVEN/WHEN/THEN 格式。
stackoverflow 官方测试已装入 `scripts/official_grade/specs/stackoverflow/`。

## 早间行动序列

1. 看 stackoverflow 分数（.tmp/local-loop-so-v8-0921-0921-2227）→ 双域判读
2. 建 D 线三件套：接口审计器 + 种子提取器（两个"并列第一"）+ 节点级重试（看 so 是否卡体量）
3. keep/stackoverflow 失败簇按通用化判据（换域仍成立吗）升维进契约
4. v8 定版提交平台（初赛 9/24 开，早交拿基线，历史最好成绩计入）
5. Docker Desktop 装机 → 官方本地模拟演练（入口契约 Linux 全真验证）

## 提交清单（今晚）

- 4f1c7ba Qoder 四高危修复 + 契约通用化
- 9f7afaf 上会话遗留 connections 探测（53 测试过）
- cb028e6 包合规扫尾
- c9bd19f 修复环验尸闸
- 19c2f78 评分基建双洞
