# 夜间工作报告（2026-09-12 深夜 → 09-13 晨）

> 按「每 5 次测试 → 修复暴露问题 → 再测」循环执行。本文件持续更新，
> 早上 9 点前为终稿。所有结论均带证据路径，可复核。

## 一、总体结论（TL;DR）

1. **赛道已定**：ARC-Bench 唯一可报赛道 = Competition 页的
   **Smoke Competition**（2026-09-01 → 10-17）。所谓多赛道
   （MOBILE/KERNEL）在 Playground 页脚标注 coming soon，尚未开放。
   该赛道即我们演练了 r3-r13 的 WEB/Playwright 全旅程形态——优势赛道。
2. **计分口径（重要发现）**：`Avg. Pass Rate`（主）→
   `Efficiency = pass/CNY`（同分胜负手）→ Token → Runtime。
   头部 8 队全部 100 分且清一色用最便宜的 **deepseek-v4-flash**。
   含义：先保通过率拿分（一半队伍 0-50 分），再打效率牌——
   建议白天加跑 flash 单模型编制对比实验（见 §五决策点）。
3. **演练主线（r10→r13）**：预算闸门按设计中止（500k 对 7 模块任务
   不再够，已提至 800k 供复核）→ resume 特性实战接续 → 旅程闸门两处
   管道缺陷修复（脚本 NameError 误判方向性浪费）→ 真应用缺陷确诊
   （惰性 teardown 注册 + 跨模块 DB 漂移）→ 生成器规则 15/16 落地 →
   r13 全新生成验证（结果见 §三）。
4. **SWE-bench Lite 夜批（8 批循环）**：同 5 实例从 **0/5 → 2/5 →
   3/5（60%）**，修复全部按批内取证驱动（9 commits + 15 回归测试）；
   历史 base 线 2%。详见 §四。

## 二、赛道调研详情（官方页面实测）

- Competition 排行榜列名实测：`Avg. Pass Rate | Efficiency | Total Token | Runtime`；
- 头部格局快照（2026-09-13）：Top8 = 100.0 分，全 deepseek-v4-flash；
  第 1 名 VOLO AI 效率 6241 pass/CNY、0.00M tokens、5s runtime；
  第 6-8 名 3.96M-9.09M tokens、10-11m runtime 仍 100 分；
- Research 页为文献图谱（ARC 框架=上交/国大 treed compiler 谱系），
  非赛道；
- 已回写作战手册：`docs/competition-plan.md` §1（提交 57d3888）。

## 三、r10 全新完整演练（多模型 + 新契约回归）

- 启动：03:43，MODEL=glm-5.3 注入，编制=开发 deepseek-v4-pro /
  测试 minimax-m3；日志 `.tmp/rehearsal-r8/run.log`，
  产物 `.tmp/rehearsal-r8/out/projects/arcbench-app_20260913_034319`；
- **结果：BudgetGuard 在 520,655/500,000 token（104.1%）处按设计中止**
  （模块开发阶段）。7 个模块完成 6 个（shared_db/seed_data/auth/
  train_search/booking/webui），仅剩 e2e_verify。**闸门语义正确**：
  中止现场干净（pipeline_state.json + cost_report 落盘，未产出
  completed.json，退出码有误导性=0，已记录为待修项）。
- **成本归因**（重要）：测试阶段烧 248,293（48%）>开发 183,505（35%）
  >方案讨论 76,445（15%）。minimax-m3 写测试 270k token 是最大头。
  规则 12 加固后提示词变大 + 7 模块任务，**500k 预算对全旅程任务
  不再够用**。
- **行动**：max_task_tokens 提至 800k（config.json，供 9 点复核）；
  启动 r11 = 同目录断点续跑（resume 特性首次实战：历史用量重新计入
  新闸门，M14-6 防多次 resume 超支语义生效）。r11 结果见下。

### r11（r10 断点续跑，resume 实战）

- 04:57 带 `--resume` 重启（04:54 首次重启忘带旗标变成全新任务，发现
  后立即止损杀掉、删除半成品目录——教训：resume 必须显式旗标）。
  心跳正确显示「恢复续跑」，从 e2e_verify 接续。
- **结果：交付完成 → [verify] FAIL（诚实拒绝，退出码 1）**。
  冒烟 PASS（11 条路由、Blueprint 组装零缺陷），旅程第 1/2 版脚本均
  `NameError: client is not defined`——**脚本自身缺陷被误判为应用缺陷**
  送 RepoFixer 修应用（方向性浪费）。
- 修复（已提交）：① 旅程样板加 `client = c` 别名；② 新增脚本缺陷分类
  `_is_script_defect`（脚本帧 + NameError/AttributeError 等 → 重生成
  第 3 版，仍败 SKIP 交人工，**绝不送应用修复**；AssertionError 仍归
  应用缺陷）。

### r12（r11 交付复验，旅程闸门修复后）

- 删 completed.json 复验。脚本问题消失后**真应用缺陷浮出**：
  POST /api/register 500。修复环 2 轮未收敛 → 诚实 FAIL。
- 人工根因确诊（本地复现 traceback）：
  1. `_shared/db.py` 在 `get_db()` 请求路径中**惰性注册**
     `teardown_appcontext` → Flask 3 抛 AssertionError（setup finished）
     → 500。生成器级修复：**规则 15**（应用级钩子必须 create_app 内
     注册，标准 init_app(app) 模式）；
  2. auth 模块借用 booking 的 DB 封装类 + 假设 `users.id` 列而 seed
     DDL 未建——跨模块耦合与表结构漂移。生成器级修复：**规则 16**
     （DB 访问单一入口 get_db、DDL 唯一权威在 seed_data）。
- 交付 app 属一次性产物：teardown 已示范性手修；跨模块漂移留给 r13
  全新生成验证（规则 15/16 已入库，7 ingest 测试过）。

### r13（全新生成，规则 12+15+16 全量验证）— 今夜收官跑

- 启动：05:29，日志 `.tmp/rehearsal-r13.log`，产物 `.tmp/rehearsal-r13/`。
- 结果：（待完成）

## 四、SWE-bench Lite 循环（每 5 实例 → 修复 → 再测）

**历史基线**（9/7-9/8，修复前）：50 实例 resolved 1（2%）；20 实例
resolved 1（5%）。

### 批 1（seed 43 × 5，deepseek-v4-pro @ 竞赛中转站，venv 后端）

结果：**5/5 全部 env_unverifiable，零 token 消耗**（S2 环境闸门按设计
拦截——不烧冤枉 token，但拦截率 100% 本身就是要修的问题）。

暴露并已修复的 4 个产品缺陷（提交 57d3888）：

| # | 缺陷 | 取证 | 修复 |
| --- | --- | --- | --- |
| 1 | env_precheck 只看 stdout 尾巴，stderr 全盲 → 4/5 实例失败原因为空串，无从排查 | pytest/sphinx/pylint/flask 4 实例 error 均空 | stdout+stderr 合并取尾 |
| 2 | Py3.12 venv 不自带 setuptools → 老仓库 `import pkg_resources` 即炸 | xarray-5131 ModuleNotFoundError | venv 兜底补装 setuptools |
| 3 | conda 分支不装 pytest → sphinx/pylint 家族 pin 无 pytest，F2P 验证命令瞎 | 家族 pin 清单核对 | conda 分支兜底装 pytest+setuptools |
| 4 | RepoFixer 路径无模型级回退、无墙钟 → 网关长挂烧 6023s 后整实例死亡（旧批取证） | seaborn-2848 duration_s=6023 | `SWEBENCH_WALL_CLOCK`/`SWEBENCH_FALLBACK_MODELS` 环境变量钩子 + dev_loop 同款备胎链 |

### 批 2（同 5 实例，conda 家族环境后端 + 420s 墙钟 + 备胎链）

结果：5/5 全部 error、零 token——但这次抓到一个**存量级缺陷**：
`ensure_family_env` 注解要 `Path`，argparse 实传 str，
`envs_root / name` 直接 TypeError——**conda 后端此前从未真正能跑**
（印证历史 `logs/swebench_full_env` 批无 summary 的悬案）。已修复并补
3 项回归测试（`tests/test_swebench_runner.py`，9 passed）。

### 批 3（同 5 实例，conda 路径修复后）

- 全部被闸门拦截但拿到了**真诊断**（stderr 修复生效），暴露三层环境代沟：
  `--no-deps` 缺真实依赖（flask 缺 click、pylint 缺 tomlkit、sphinx 缺
  babel）；兜底 `pip install pytest` 覆盖仓库自装旧版 → 与新版 hypothesis
  钩子互斥；2026 版 setuptools 移除 pkg_resources / 老仓库 PEP 660 不可
  editable 安装。
- 修复链（4 个 commit）：全依赖安装+缺才补装、`setuptools<81`+wheel 底座、
  `--no-build-isolation`+editable 失败回退、家族年代上限 cap
  （click==8.1.3、jinja2<3.0+markupsafe==2.0.1、numpy<1.24+pandas<1.5、
  urllib3<1.27、pytest~=7.2——参数化 ID 引号生成随 pytest 大版本变化，
  曾致 P2P 漂移）。

### 批 4 / 批 5（同 5 实例，环境修复链逐层验证）

- **批 5 终局：resolved 2/5（40%），0 error**（pytest-9359 ✓、
  pylint-7993 ✓，各约 42k token）；3 个 env_unverifiable 全部零 token
  诚实拦截。对比修复前历史基线 2%（1/50）：**单批 40%**。
- 批 5 中途 pin 收紧后（sphinx markupsafe 配对、xarray pandas 1.x、
  flask pytest 7.2）重启为批 6。

### 批 6（同 5 实例，验证剩余 3 个的 pin 修复）

- 启动：04:41，日志 `logs/swebench_night_b6.log`。
- 结果：（待完成）

### 批 6 / 批 7（同 5 实例，验证 pin + 数据集伪影修复）

- **批 6 终局：resolved 3/5（60%）、0 error**（pytest-9359 ✓ x2 轮、
  pylint-7993 ✓、xarray-5131 ✓——pandas 1.x cap 生效）。
- flask-5063 的 P2P 漂移根因查明：**数据集截断伪影**——P2P 存的参数化
  ID 是官方 `-v` 输出按空白解析的（`create_app2("foo", "bar")` 存成
  `create_app2("foo",`），任何环境都复现不出。修复：预检前先 `--co`
  收集映射，精确节点找不到退到函数级（`_canonicalize_p2p`）。
- 批 7 = P2P 收集映射首次实战（结果待补）。

**SWE-bench 阶段结论**：同 5 实例跨批演化 **0/5 → 2/5 → 3/5**，
修复均按批内取证驱动；已提交 8 个 commit、12 项回归测试。
剩余长尾：sphinx-8801（P2P 有节点连函数级都不存在，待查 conftest
条件收集）、flask-5063（批7 验证映射修复）。
产品教训（将反哺主比赛管线）：诊断信息必须完整落盘（stderr 盲区）、
环境类失败必须零 token 快速拦截、依赖安装严禁覆盖被测本体、
外部数据集的 ID 不可盲信（需收集映射归一）。

### 后续批次

（随循环推进追加）

## 五、明早建议决策点

1. r10 若 PASS → 以现编制报名 Smoke Competition；若 FAIL → 看 §三归因。
2. 效率牌：是否加跑 deepseek-v4-flash 单模型编制对比实验（pass/CNY）。
3. SWE-bench 循环继续的节奏与 token 预算授权（当前已按既有授权执行）。
