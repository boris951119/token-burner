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

- 05:08 启动（首次因 `--project-dirname` 非法 CLI 参数立即失败，去掉
  重启；已记入教训），07:0x 结束，**退出码 1（诚实 FAIL）**，总耗
  ~610k token（800k 预算内）。
- **进步**：17 条路由（r10 同任务 11 条）；冒烟 PASS；注册 201/登录
  200/搜索 200 全通（手动复验）。
- **旅程 FAIL 根因链**（手动确诊，零 token）：
  1. `/api/trains/<id>` 查 `train_id` 列而 DDL 建的是 `id`——**模块内
     schema 漂移**，详情接口 500，级联毁掉选车次+订票步；
  2. auth 写 session 的键与 booking 读的键不一致（跨模块契约漂移，
     规则 16 描述过的病，生成时未守住）；
  3. 修复环 2 轮未能从旅程级输出中定位到列名级根因 → 未收敛。
- **结论：头号瓶颈已从「生成完整性」转移为「修复收敛深度」**。两次
  独立全跑（r10 系、r13）都卡在同一环节。建议下一步（白天）：
  修复指令注入「schema 审计」（对失败接口附 DDL 与实际查询列的
  确定性 diff）；interface_check 增加列名引用 vs DDL 的静态门禁；
  修复轮次按缺陷类型分级（路由级 2 轮、schema 级 3-4 轮）。
- 规则 12/15/16 生效证据：r13 无 r10 的 teardown 500（规则 15 生效）、
  无「页无 API」缺陷（规则 12 生效）、路由数上升（Blueprint 契约生效）。

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
- **批 7 回归取证**：全部「真缺失」——收集命令里多加的 `-q` 与
  run_pytest 自带的 `-q` 叠成双 `-q`，pytest collect-only 输出退化成
  per-file 计数摘要，节点 ID 全部消失。去掉后批 8 复跑即恢复。
- **批 8 终局：resolved 3/5（60%）、0 error**（pytest-9359 ✓、
  pylint-7993 ✓、xarray-5131 ✓ 全部跨批可复现）。**flask-5063 首次
  通过环境闸门进入真实修复**（92k token 后未收敛——问题性质已从
  「环境适配」转移到「修复收敛」）；sphinx-8801 是唯一剩余环境拦截。
- **批 9（seed 44 × 5，全新实例测泛化）**：
  - seaborn-3407 / requests-863 / sphinx-8801 env_unverifiable（零
    token——requests-863 是 2013 年代、seaborn P2P 有 120 个节点收集
    不到，年代考古深水区，闸门如实拦截）；
  - flask-5063「failed」：**123k token / 2 轮仍未收敛**（P2P 映射后
    进入修复域，与 r13 同款「修复收敛」瓶颈）；
  - pytest-dev 实例「failed」：155k token / 2 轮 / **8396 秒（2.3 小时）**
    ——真实改了代码（`src/_pytest/_code/code.py`）但验证未收敛；
    时长坐实决策点 6（实例级无总时间预算）。

**批 9 终局：resolved 0/5**——泛化测量口径：环境闸门全部如实拦截
（未冤枉、未放行、零浪费 token），两个实例进入修复域但均未收敛。

**SWE-bench 阶段总结论**：同 5 实例（seed 43）跨批演化
**0/5 → 2/5 → 3/5（60%）**，pytest/pylint/xarray 跨批可复现 resolved；
seed 44 泛化批暴露「修复收敛」为剩余瓶颈；环境适配域已基本打通
（9 commits + 15 回归测试；历史 base 线 2%）。
产品教训（将反哺主比赛管线）：诊断信息必须完整落盘（stderr 盲区）、
环境类失败必须零 token 快速拦截、依赖安装严禁覆盖被测本体、
外部数据集的 ID 不可盲信（需收集映射归一）、pytest 输出格式对 `-q`
重复敏感（工具化封装时慎叠加全局旗标）。
产品教训（将反哺主比赛管线）：诊断信息必须完整落盘（stderr 盲区）、
环境类失败必须零 token 快速拦截、依赖安装严禁覆盖被测本体、
外部数据集的 ID 不可盲信（需收集映射归一）、pytest 输出格式对 `-q`
重复敏感（工具化封装时慎叠加全局旗标）。

### 后续批次

（随循环推进追加）

## 五、明早建议决策点

1. **报名**：赛道唯一（Smoke Competition，至 10-17），建议尽快以
   r10-r13 验证过的提交流程正式提交一单真实任务，拿真实排位与
   pass/CNY 基线（需用户账号操作）。
2. **头号攻坚**：「修复收敛深度」——建议顺序：
   a. 修复指令注入 schema 审计（失败接口的 DDL 列 vs SQL 引用列的
      确定性 diff，零 LLM）；
   b. interface_check 加列名引用静态门禁（生成期拦截，优于修复期）；
   c. 修复轮次按缺陷类型分级预算。
3. **效率牌**：是否加跑 deepseek-v4-flash 单模型编制对比
   （头部全 flash + pass/CNY 计分指向此路；一次演练约 1-1.5h）。
4. **预算语义**：max_task_tokens 已提至 800k（config.json，可复核）；
   是否常态化为 1M 以容纳验证+修复余量，请拍板。
5. **SWE-bench 循环**：机制已健全（环境域基本打通），后续批次性价比
   取决于第 2 点的修复收敛改进——建议改进落地后再跑批 10+ 对比。
6. **新暴露（b9 尾实例取证）**：实例级无总时间预算——单闭包调用
   最坏 3 模型 × 3 重试 × 420s 墙钟 ≈ 1.5 小时，建议加实例级总时长
   上限（如 30 分钟，超时记 status=timeout 零诊断上抛）。
   主比赛管线同理：任务级 wall-clock 兜底值得对称补齐。

## 六、r14 flash 单模型实验：排行榜水分裁决（09-13 上午）

**设置**：三角色全 deepseek-v4-flash、单模型模式（纯复刻排行榜头部
形态），同一 requirements 包。09:04 启动，~10:16 结束，
**FAIL（诚实退出码 1）**，总耗 **476,413 token / 约 72 分钟**。

**结果与解读**：

1. **模型不是胜负手**。flash 与 pro/glm 大编制死在同一个地方——旅程
   级缺陷的修复不收敛。三个编制、同一死法 ⇒ 头部 100 分若属实，靠的
   是管线形态（极瘦/特化实现），不是"选了 flash"。
2. **flash 不便宜（在重管线里）**。方案讨论阶段 flash 写了 97,783
   token，比 glm-5.3（76,445）还多——flash 输出冗长，省的是单价
   不是用量。经济性前提是"瘦 agent + flash"，不是"重管线换 flash"。
3. **头部 5s / 0.00M 判定为口径特例或非全旅程实现**。任何诚实走完
   需求讨论→模块开发→验收的最小流程都不可能 5 秒/0 token。效率列
   作为同分排序依据可复制性低，我方回到"先过率、后提效"既定策略。
4. **产品守卫全线正确开火**（实验的正面收获）：
   - 冒烟 PASS（8 条路由，flash 组装无缺陷）；
   - 第 2 版脚本缩水 → **缩水守卫拒收**；
   - 修复致路由面 8→0 → **回滚守卫拦下破坏性修复**；
   - 最终诚实 FAIL、退出码 1。
5. **配置已恢复**最优编制（pro 开发/minimax 测试/glm 主帅）。
   同日新增的确定性 schema 审计（commit 见下）直接针对三编制共通的
   死因，是下一步修复收敛工作的第一块基石。

## 七、r15：schema 审计武装后的首轮验证（09-13 上午）

**设置**：最优编制（glm 主帅 / pro 开发 / minimax 测试）+ 旅程闸门
注入确定性 schema 审计。10:20 启动，11:47 结束，
**FAIL（诚实退出码 1）**，模块开发阶段耗 ~293k token。

**结果与根因**（手动确诊，零 token）：

- 冒烟 PASS、15 条路由；旅程卡在 **register 500 → search 500** 级联。
- search 500 真因：`SELECT departure, arrival FROM trains` 而 DDL 列为
  `departure_time/arrival_time`——**审计器当时的盲区**（v1 只查
  INSERT 清单/WHERE 谓词/限定引用，SELECT 清单未覆盖）。已补齐并
  防字符串/数字字面量误报；对 r15 真 app 复跑：**7 处发现全为真阳性**
  （5 INSERT + 2 SELECT）。
- 另发现行为级违约：重复注册返回 201 而非 409（需求明文要求拒绝），
  webui 内还有一套硬编码 demo 车次数据（规则 13 违规，被真路由遮蔽
  未生效）。行为级缺陷不在 SQL 审计射程内。
- 修复环依旧 2 轮未收敛——**带审计仍不够**：诊断覆盖面追着缺陷族跑。

**本轮元结论**：确定性诊断的方向正确（7 处真阳性即证据），但它是
"覆盖清单"问题——每轮演练暴露一个新缺陷族（r13 INSERT 漂移 →
r15 SELECT 漂移 → 行为级 409/硬编码兜底）。下一步建议：
1. 旅程脚本作者提示词加入「重复注册应 409」「以种子字符串断言
   搜索结果」等行为探针（使行为级违约在旅程层可发现）；
2. 审计增加表名漂移检查（查询不存在的表当前静默跳过）；
3. 修复轮次按审计发现数动态增配。

**观测盲区备忘**：交付后的 verify 阶段不更新 heartbeat——排障时
「心跳长时间冻结 + completed.json 已存在」即验收进行中信号。

## 八、r16：全套武装首轮（09-13 下午）

**设置**：行为探针 + 完整审计（含 SELECT/表名漂移）+ 轮次动态增配，
最优编制。12:04 启动，14:0x 结束，**FAIL（退出码 1）**。

**新机制全部开火（机制面全绿）**：
- 行为探针生效（旅程脚本含重复注册/精确种子断言）；
- 「审计发现 6 处 → 修复轮次 3+2」动态增配按设计触发；
- 缩水守卫/回滚守卫正常待命。

**仍 FAIL 的根因链（手动确诊）**：
1. 首页曾被 `/` 路由以内联/JSON 转义形态服务——**修复轮确实把它
   修好了**（终验后手动重跑脚本，步骤 2 已过）；
2. register 500 的真因是**修复反噬**：LLM 读了审计结论后没有把 SQL
   对齐 DDL，而是写了运行时 schema 自适应层（`_pick_column` 列名
   猜测 + `users table schema unsupported` 500 绊线），探测逻辑自身
   失灵 → 所有注册请求被打死；
3. 修复指令此前只给了诊断、没给**修复形态约束**。已补：审计注入段
   新增「直接改 SQL 字面量，严禁新增 schema 探测/自适应/兼容层」。

**元结论**：确定性诊断是把双刃剑——诊断注入必须配套"修复形态
约束"，否则 LLM 会用过度工程"回应"诊断而不是"服从"诊断。
r17 将带此约束跑。

## 九、r17：冒烟级新缺陷族（09-13 下午）

**结果**：FAIL（退出码 1）——死于冒烟阶段（比旅程更早）：
`import web_ui: ModuleNotFoundError("No module named 'auth'")`。

**根因（确定性确诊）**：计划/接口/真代码全部叫 `f1_auth/f2_search/
f3_booking`，组装模块 web_ui 却按语义名 `import auth/search/booking`；
目录里另有三个只有 `__init__.py` 的**空壳包**（auth/search/booking）
把水搅浑。模块命名漂移 + 空壳包干扰，smoke auto_repair 的诊断里
没有实际包名映射，修不动。

**对策（已提交）**：`_package_layout_section` 包结构审计——零 LLM 扫
顶层 import 对照"有实现的包"，近名（f1_auth~auth）即报映射；空壳包
单独警示"不要为它补代码"。对 r17 真 app 验证：3 漂移 + 3 空壳全部
命中（3 项测试）。已注入 smoke auto_repair 指令。r18 带 此跑。

**缺陷族谱系更新**：INSERT 漂移(r13) → SELECT 漂移(r15) → 修复
反噬(r16) → 命名漂移+空壳包(r17)。每个族都有确定性检测器 + 真
app 实证。初赛倒计时 8 天，管线在可见地变厚。

## 十、r18 + 视觉通道落地（09-13 晚）

**r18**：FAIL（16:58 正常退出，79 分钟）。缺陷=组装层又现命名分裂
（web_frontend/webui 并存，全库无 `/` 路由注册 → 首页 404）；旅程
审计发现 3 处、轮次 3+1 触发，修复未收敛。
【勘误】此前记录的"终局挂死 6.5h"系误判：r18 用 nohup 发车没走完成
通知，我在 23:18 把 keep1 的进程误当成 r18 的僵尸并误杀（keep1 已重
启）。双重教训：①长任务必须走通知通道；②verify 阶段心跳冻结是观测
盲区（本条已修：验收各阶段直接写心跳），判断进程死活以日志 mtime 为准。

**视觉转写通道上线**（初赛裁决：新题 + 截图会提供）：
- 探测：11 模型仅 **kimi-k3** 可用（完美描述 UI 布局/文案/按钮），
  minimax-m3 备胎；glm-5.3 与 qwen 全家拒图，flash/pro 大图假称截断；
- 架构：视觉转写（kimi 当眼 → 结构化中文描述 → 注入需求文本），
  管线保持纯文本；带缓存（断点不重复计费）+ 逐备胎降级 +
  幻觉防线（无效图绝不上发——kimi 对垃圾输入会编造以假乱真的描述）；
- 官方 keep 截图实测：22 张引用全部识别，转写内容准确
  （"Take a note"输入栏/导航/按钮文案全部吻合）；
- 修复：vision.py 漏 import io 曾致全部转写静默失败（NameError 被
  兜底吞掉）——教训：吞异常的兜底必须配日志。

## 十一、keep1：真实规模首战——规模墙暴露（09-14 凌晨）

**设置**：官方 keep 应用（Google Keep，32 条原子需求 = 以往演练 5 倍
体量）+ 视觉通道（20/22 张转写，缓存命中）+ 最优编制（glm 主帅）。

**结果**：FAIL（85 分钟，退出码 1）——**死在方案讨论阶段的规模墙**：
32 需求 + 视觉描述让讨论提示词暴涨，glm-5.3 单次推理超 600s 墙钟，
3 次重试全部超时；讨论路径此前没有模型级备胎，RuntimeError 直接
炸穿管线。

**已修复**：`orchestrator._chat` 加模型级备胎链（dev_loop._chat_
resilient 同款，settings.models 逐备胎，3 项测试）。

**keep2 策略调整**：主帅换 deepseek-v4-pro（大生成实测 182s，不撞
墙钟），glm 留编制内当备胎；视觉缓存命中不重复计费。

**白天待办（规模架构题）**：32+ 需求的讨论提示词需要分层压缩——
讨论阶段吃 FOLDER 级摘要，拆分阶段才吃 ATOMIC 明细。这是比换模型
更本质的规模解，列入初赛备战的核心工程。

## 提交包就绪（09-14 上午）

**`token-burner-submission.zip`（344KB，150 文件）已生成**，结构=
官方 Blank Template 骨架（README/skills/examples/SDK）+ 我方实现
（main.py/app/config.json/requirements.txt）。

- 依赖审计补齐：pillow（视觉通道）、httpx（显式化）——此前仅传递
  依赖不保证在官方环境可用；
- 敏感文件扫描：干净（无 .env/密钥）；
- 导入链冒烟：--help 与 main 模块全链可达；
- **用户手动实弹**：登录平台 → Smoke Competition 提交入口 → 上传
  此 zip → 触发运行 → 看榜单（首单价值=流程与平台侧未知，不是分数）。

## 十二、晨间速览（8:30 版，随 keep2 结果更新）

**昨夜到今晨的产品资产净增**：
- 视觉转写通道（kimi-k3 当眼→截图结构化描述注入；官方 keep 22 图实测；
  缓存/降级/幻觉三防线）——初赛"截图会提供"裁决的直接对策；
- 讨论阶段模型级备胎链（keep1 规模墙取证：glm-5.3 在 32 需求下单次
  推理超 600s 墙钟，讨论路径曾无备胎）；
- 冒烟层 GET / 必须 200（r18 首页 404 族提前拦截）；
- 验收阶段实时心跳（消除 verify 观测盲区——曾引发 r18 误判连环）；
- 包结构审计（import 名↔实际包名映射 + 空壳包识别）+ 审计 SELECT
  清单覆盖 + 修复形态约束；
- 官方基准仓库接入：6 应用真实规模需求树 + Playwright 测试作为备战
  教材（管理员裁决：初赛=同编译器新生成题目 → 通用能力路线确认）。

**keep1（官方 keep 首战）**：FAIL——规模墙（讨论超墙钟）。已修复并
升级编制策略（pro 主帅）。
**keep2（终止于 04:20）**：讨论/拆分通过（回退+pro 策略生效），
模块开发推进到 2/8 时 dev 环节也撞墙钟——32 需求的单模块代码生成
（数千行 UI/逻辑）连 pro 都要 >600s。**处置**：杀 keep2，墙钟
600s→1200s（config.json，hang 防御仍在），发 keep3。

**keep3（进行中，晨间快照 07:00）**：讨论阶段 40 分钟通过（1200s
墙钟生效），模块开发推进中（db_core ✓，节奏 ≈30-40 分钟/模块，
keep 共 8 模块）——**预计中午前后出终局**。终局判定（PASS=第一次
全链路真 PASS；FAIL=新缺陷族进射程）会自动分析并更新本节。
后台任务通知机制在位，无需人工干预。

**轨迹取证上线（09-14 上午，节奏获批后第一件）**：旅程样板加
TESTING+PROPAGATE——应用侧异常带着 file:line 直接冒泡进报告，
修复指令不再只看 HTTP 状态码；_is_script_defect 升级为「最深帧」
判定（异常最终抛出的文件在脚本=脚本缺陷，在应用=应用缺陷），
双向分类测试通过。

**keep3 处置**：按当前节奏终局在 15:00 前后且验证期用不上新器官——
已杀并断点续跑（resume 保留 db_core/seed_data 两模块与视觉缓存，
新进程加载全部新器官）。6 模块剩余 + 验收，预计 13:00-14:30 终局。

**今日（9/14）建议**：keep2 终局分析 → 规模架构题立项（讨论吃
FOLDER 摘要、拆分吃 ATOMIC 明细的分层管线）→ keep 系列迭代至
真 PASS → 提交流程彩排。


## 十三、实弹双轨启动（09-14 深夜）

**平台实弹已跑两单 + 第三单在途**：
- generation-1（Train Ticket 143 需求）：3.5h 跑到验收修复，死于备胎缺失
  （已修复）；真实计费 1.202M token = ¥29.62；
- generation-2（同任务）：修复验证版，2h 死于模块开发 pro 超时×3——
  **第二个单点：_chat_resilient 备胎调用裸奔**（已修复：全链保护 +
  ModelChainExhausted 专类型 + 模块级优雅冻结）；计费 750k = ¥15.85；
- **generation-3（Keep 32 需求，run cd2a82fe6dae）00:45 启动**：
  快照 token-burner-v2（备胎链+优雅降级+轨迹取证+内存哨兵全器官），
  Stage 1 过（43 需求/32 场景），Stage 2 依赖安装中。预计 05:00-07:00
  终局——**第一次完整的平台端到端数据**（含 Playwright 真实评分）。

**本地 keep4**：18:30 启动（分层管线+七器官同款配置），模块开发 2/8，
预计 04:00-05:00 终局。keep4 与 generation-3 同任务同代码——
**双跑对照将分离"平台环境因素"与"产品因素"**。

**预算调整**：max_task_tokens 800k → 2M（gen-1 实证 Train Ticket 规模
1.2M token 起步即超 800k——闸门语义不变，超了照样干净中止）。
