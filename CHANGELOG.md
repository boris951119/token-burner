# Changelog

## v1.0 · M17-1 付费档达标（2026-09-05）：paid_pilot3 通过率 62% · 准入线首次通过

> 阿里 MaaS 快速阵容（qwen3.6-flash PM / deepseek-v4-flash dev /
> qwen3-coder-plus test）+ V2.9 契约注入,报告 `logs/bench_v1/paid_pilot3/`。

- **结果**:任务 3/3 succeeded;模块 **10/16 = 62%,50% 准入线首次通过**,
  单任务 15-30 分钟（免费档同任务 2.5 小时+）。逐轮演进:免费档 0% →
  glm-4.7 组 11% → 付费快阵 6%（暴露 M15-7 缺口）→ **契约注入后 62%**。
- **归因**:V2.9（M15-7）单轮使通过率 6%→62%——「代码/测试从同一份契约
  命名」是全部机制修复中杠杆最大的一项;剩余 6 个冻结为单模块语义收敛
  残差（断言失败/门禁不收敛）,无系统性签名。
- **V3 解锁**:50% 准入线通过,进入全量 10 任务基准的前置条件达成。
- 附:测试用阿里 MaaS Key 已按用户要求从 `.env` 删除（仅本地存在过,
  从未入库）。

## v1.0 · V2.9（2026-09-05）：写码注入模块契约——M15 家族最后一块拼图

> 付费档 paid_pilot2 取证（阿里 MaaS：qwen3.6-flash/deepseek-v4-flash/
> qwen3-coder-plus,任务级 3/3 但模块 1/16）:15 个冻结中 9 例同根——
> **写码提示词只有职责描述没有契约**,dev 模型自由起名 → ①接口门禁
> extra/missing 震荡 5 例;②测试按契约 import(M15-5/6 工作正常)而代码
> 无此名致 pytest 收集 ImportError 4 例。跨模型家族(glm-4.7 组同款)
> 复现,证明是系统性提示词缺口而非模型能力。

- **修复（M15-7）**:`_write_code` 新增 contract 参数,契约 public_api
  (缺省回退 exports)以「必须实现以下全部导出」段注入用户提示词,并
  前置 extra 处置指引(契约外顶层公开符号会被拦,内部辅助 _ 私有化);
  `run_module` 透传。与 M15-5(测试侧)成对——**代码与测试现在从同一份
  契约出发命名**。无契约时提示词与修复前逐字节一致。

- **测试**:新增 `TestWriteCodeContractInjection` 3 项(注入/无契约不变/
  调用路由双向);既有 M15-5 路由断言随行为升级修正(写码也含契约段);
  全量回归 **1027 → 1030 passed / 7 skipped / 0 failed**。

- 附带记录:提速换阵实测吞吐(qwen3.6-flash 150 / qwen3-coder-plus 124 /
  deepseek-v4-flash 76 / deepseek-v3 39 tok/s)——39 tok/s 时全程 6-10h,
  换阵后 1.5h;`__import__` 硬类 1 例仍直接冻结(提示词已禁但模型违反,
  属 hard 类语义维持)。

## v1.0 · M17-1 基准试跑终局（2026-09-05）：三组对照 · 机制收敛证明

> bench_v1 四轮跑批（round-2f/r3/r4/r5）终局,报告 `logs/bench_v1/pilot_r5/
> bench_report.json`;评审结论《产品评审与市场对比_v1.0.md》同步成稿。

- **三组对照**:T1 免费档基线 0/7 → T2 dev=glm-4.7+旧策略 1/6 → T3 dev=
  glm-4.7+V2.8 1/5;任务级 3/3 succeeded,模块级合计 2/18=11%（50% 准入线
  未达）。三组共 18 模块,**机械性缺陷零复发**;os.remove 直接冻结在 T3
  归零（V2.8 生效的独立验证）。

- **瓶颈收敛证明**:剩余冻结 100% 归因基座模型能力层（接口门禁不收敛/
  断言不收敛/收集错误）——机制层（M14/M15/M16 + V2.1~V2.8）无待办,
  通过率的下一杠杆为付费档旗舰 dev 模型（用户已计划以最先进模型亲测,
  免费档 11% 为对照基线）。

- **工具链沉淀**:`bench_v1_run.py --models`（按任务覆盖三角色模型）;
  T2/T3 与 T1 的对照即由该参数驱动——为 V3 全量基准与模型档位 A/B 
  提供了标准化通道。

## v1.0 · V2.8（2026-09-05）：危险操作分级处置（规格 3.6.3 修订）+ 约束提示词前置

> bench_v1 round-5 取证（T2 glm-4.7）：data_reader/data_processor 两模块死于
> `os.remove()` 被危险扫描直接冻结（3.6.3 原文：BLOCKED 不进修复循环）。
> 模型越强越爱写"自然"的文件清理代码——策略误杀随基座能力上升而放大。
> 用户批准的规格修订（方案 A+B）。

- **方案 B（分级处置）**：`local_executor` 新增 `scan_dangerous_graded` →
  (hard, soft)。hard（不可替代高危：动态执行/系统命令/网络/子进程/序列化
  逃逸）维持执行器 BLOCKED 直接冻结；**soft（fs 删除族 · 模块代码侧：
  os.remove/unlink/rmdir/removedirs/renames、shutil.rmtree/move）降级为
  可修复**——`dev_loop` 门禁链在执行器之前拦截（平台门禁之后），进修复
  循环并附修复指导（调用方清理/待清理清单/tempfile 上下文三种替代设计）。
  双执行器（Local/Docker）同口径只拦 hard；测试侧放行（V2.4）不变；
  `scan_dangerous` 合并返回保持兼容。

- **方案 A（提示词前置）**：`danger_prompt_constraint()` 与扫描黑名单同文件
  同源（单一数据源，对齐 platform_policy 设计锚点），注入 write_code /
  fix_code system 提示词——首版即合规，省掉"生成→拦截→冻结"的整模块
  投资损失。

- **配置**：`max_response_tokens` 8000 → 16000（config.json；glm-4.7 思考型
  输出更长，减少截断-续写往返）。

- **测试**：新增 `test_danger_graded.py` 10 项（分级拆分/软级进修复循环/
  执行器只拦 hard/提示词内容与注入）；全量回归 **1017 → 1027 passed /
  7 skipped / 0 failed**，既有危险冻结测试（os.system 类）行为不变。

## v1.0 · V2.7（2026-09-05）：round-4 热修——门禁自炸防护 + 测试竞态根除 + 网关参数硬化

> bench_v1 round-4 取证：T1/T2 死于免费档网关 Timeout/RateLimit；**T3 死于
> V2.6 门禁自身缺陷**——测试代码含 class 定义时 `ClassDef` 误入函数分支访问
> `.args` 抛 AttributeError，在 29 万 token 深处炸死整任务。

- **M15-6 热修**（`test_check.py`）：`ClassDef` 从函数签名分支拆出（只绑定
  类名）；`dev_loop` 门禁调用包 try/except **异常降级放行**（同 M14-7
  「增强非硬门禁」哲学：校验器自身缺陷绝不杀任务）。新增 3 项回归
  （class 定义不炸/类内调用不误报/门禁异常降级放行路径）。

- **既有偶发测试根除**（`test_async_tasks.py`）：`test_events_update_state_
  broadcast_and_persist` 实为竞态——job_factory 在 submit 时同步调用且原
  写法返回 dict（非 callable），worker 内 `job()` TypeError 后异步发
  done(FAILED) 帧，与主线程 4 个事件抢队列顺序（本机复现 4/5 失败）。
  修正为 factory 返回阻塞到事件发完的 job，done 必然最后；单次 10.5s →
  0.5s，6/6 稳定绿。

- **网关参数硬化**（config.json，延续 V2.2 方向）：`llm_timeout_seconds`
  120 → 240、`llm_max_retries` 5 → 6——T1 连续两轮死于同一位置的 ~120s
  超时线，免费档高峰存在分钟级停顿，需更长单次等待窗口。

- 全量回归：**1014 → 1017 passed / 7 skipped / 0 failed**。

## v1.0 · V2.6（2026-09-05）：测试侧绑定门禁——round-3「测试漏 import」冻结根因修复

> bench_v1 round-3 取证（T2，logs/bench_v1/pilot_r3/）：六个模块中三个
> （analytics/cli/export）冻结于同一签名——测试文件只 import pytest/mock
> 等第三方库，裸调用被测函数，执行必 `NameError`；修复循环只修代码不修
> 测试，代码侧永远无从修复，5 轮震荡后冻结。

- **根因**：M15-5 契约注入解决了「函数名发明」，但 glm-4.5-flash 连
  `from <module> import ...` 语句本身都漏写——属同一「测试侧缺陷、
  代码侧不可修」家族的第二种症状。

- **修复（M15-6）**：新模块 `app/utils/test_check.py`——`check_test_bindings`
  AST 解析测试文件，收集全部绑定名（import/def/class/赋值/参数，保守超集
  防误报），契约符号「**被实际引用却未绑定**」→ 阻断并给出精确修复指令
  （只拦必炸 NameError 的引用，测试只覆盖契约子集属合法，不强制全量绑定）；
  测试文件语法错误同样阻断。接入 `dev_loop._drive` 门禁链（逻辑审查之后、
  执行之前）：命中 → 修复轮**只重新生成测试**（提示词携带缺陷清单），代码
  不动。无契约时门禁空转（行为兼容）。

- **测试**：新增 `test_test_gate.py` 9 项（裸引用/合规 import/star import/
  无契约空转/语法错误/内建不误报/public_api 首名提取/再生分支路由/一次通过）；
  既有 `test_write_tests_contract`、`test_logic_review` 桩测试随门禁收紧同步
  修正（桩测试补 from-import）；全量回归 **1005 → 1014 passed / 7 skipped /
  0 failed**。

- **运营记录**：round-3 T1 死于网关 Timeout（5 次重试耗尽，41,841 tokens）；
  T2/T3 任务级 succeeded 但模块 0/12 非冻结（执行失败类 3 + 接口门禁不收敛
  类 3/模块）。接口门禁不收敛类（config/core/utils：flash 模型不理会
  M15-2 改名指导）留待观察——非本轮修复对象，属基座模型能力层。

## v1.0 · V2.5（2026-09-05）：写测试注入接口契约——round-2f 三模块同签名冻结根因修复

> bench_v1 round-2f 取证（T1，logs/bench_v1/pilot_r2/）：password_generator /
> blacklist_checker / strength_evaluator 三模块同签名 FROZEN——接口门禁通过
> 但执行期 `ImportError: cannot import name ...`。

- **根因**：`_write_tests` 只喂模块名与代码，测试 LLM（glm-4.5-flash）凭需求
  语义发明契约之外的函数名（calculate_strength / is_weak_password /
  generate_batch_passwords）；执行失败后修复循环只修代码不修测试，改代码凑
  测试名 → 接口门禁拦截 → 改回契约名 → 测试再失败，震荡 5 轮冻结。此为
  潜伏缺陷：此前各轮模块均死于更早环节（限流/pyc/链接误报/fs 误拦），从未
  大规模到达执行阶段，v1.0 门禁链修通后首次暴露。

- **修复（M15-5）**：`dev_loop._write_tests` 新增 contract 参数，契约
  public_api（缺省回退 exports）以「模块接口契约」段注入用户提示词，测试
  调用强制按契约签名；`run_module` 透传契约。无契约时提示词与修复前逐字节
  一致（行为兼容）。

- **测试**：新增 `test_write_tests_contract.py` 5 项（注入/无契约不变/
  空契约不变/exports 回退/调用路由——写代码调用不含契约段、写测试调用必须含）；
  全量回归 **1000 → 1005 passed / 7 skipped / 0 failed**。

- **运营记录**：T1 于 2026-09-04 23:58 死于 GLM 账户级限流（5 次重试耗尽，
  V2.2 任务级 traceback 完整落盘）；跑批进程随旧会话窗口关闭被连带终止，
  T2/T3 未执行——round-2f 数据归档供对照，round-3 携本修复重跑。

## v1.0 · V2 回炉修复批次（V2.1–V2.4，2026-09-04）：基准试跑取证修复链

> bench_v1 pilot 试跑（M17-1 中期准入线）驱动的四个运营韧性/误报修复批次，
> 全部以真实失败取证定位根因（数据归档 `logs/bench_v1/`）。

- **V2.1 续写拼接换行腐蚀**（`model_client` 续写拼接）：max\_response\_tokens
  截断触发续写时，GLM 续写响应以真实换行开头而非原位接续——裸拼接在拼接点
  产生 unterminated string literal，5 轮不收敛冻结（pilot round-1 取证：0/17
  模块通过）。修复：句中截断剥除续写头部换行；新增 TestContinuationJoin 7 项
  回归。本批同时交付 M17-1 标准需求集（`scripts/bench_tasks.json`，10 任务 × 5
  类别）与基准跑批脚本 `scripts/bench_v1_run.py`。

- **V2.2 运营韧性三修复**（round-2 取证）：① `list_files` 排除
  `__pycache__/*.pyc`（pyc 被 read\_text 读出 UnicodeDecodeError 杀死任务的
  根因），`read_file` 对不可解码二进制纵深防御返回 None；② GLM 网关偶发 GBK
  错误页（UnicodeDecodeError/JSONDecodeError）归入瞬态退避重试，重试硬化
  3×1s → 5×15s（免费档分钟级限流窗口）；③ 任务失败附截尾 traceback；
  候选池移除 glm-4.6v（探针证实 `\n` 转义输出为真实换行，
  `logs/bench_v1/model_probe_20260904.json`）。

- **V2.3 链接门禁子模块导入误报**（round-2d 取证）：`from _shared import
  log_config` 为合法子模块导入（`_shared/log_config.py` 存在），旧逻辑只在
  `__init__.py` 符号集里找 → 误报 missing → LLM 代码本身正确无从改起，4 模块
  连续冻结。修复：符号缺失判定前先验证 `pkg/sym.py` 子模块文件存在性。

- **V2.4 危险扫描测试侧放行 fs 删除族**（round-2e 取证）：生成的测试以
  os.unlink/shutil.rmtree 清理临时产物（标准写法）被危险扫描一刀切 BLOCKED
  → 按 3.6.3 直接冻结。修复：测试侧放行 fs 删除/改名族（执行环境为一次性
  tmp 目录）；进程控制类、eval 族、危险 import 对测试仍全禁；模块代码侧
  黑名单不变（维持宁可误报绝不放过）。

- 全量回归：**986 → 1000 passed / 7 skipped / 0 failed**（2026-09-04 复验）
  ；round-1/2/2c/2d/2e 各失败批次数据均归档 `logs/bench_v1/` 供对照。

## v1.0 · V2 批次（2026-09-04）：自适应与扫描——M14-5/6/7 + M15-3/4 + M16-1

> v1.0 Release 质量收敛第三批（规格 v1.0.md，含 2026-09-03 组件评审追加项）。
> 主题：safe 模式门禁全覆盖 + 自适应契约风格 + JS 首道防线补全。

### 新增

- **M14-5 平台黑名单上移门禁链**（`app/agents/dev_loop.py`）：平台/危险预扫描
  此前仅在执行器层（auto 模式）生效，safe 是默认模式却零覆盖——fcntl 代码
  静默通过全部门禁。现门禁链升级为「语法 → 静态 → 链接 → **平台** → 接口 →
  逻辑审查」，双模式统一覆盖；命中进修复循环（LLM 换平台可用方案）而非冻结。

- **M14-6 resume 预算恢复**（`app/agents/pipeline` + `app/dashboard`）：resume 时
  从项目 `logs/cost_report.json` 读历史 total\_tokens 注入新 BudgetGuard，
  看板预算口径同步累计——多次 resume 不再稀释「单任务总预算」语义。

- **M14-7 safe 模式 LLM 逻辑审查**（`dev_loop._logic_review` + 新提示词
  `logic_review_system/user.md`）：规格 3.6.2 三件套补全（AST 静态 + LLM 审查 +
  手动反馈）。契约函数级审查（控成本）；verdict=fail 进修复循环；
  LLM 调用/解析失败降级放行（增强非硬门禁）；auto 模式不审（有真实执行反馈）；
  新配置 `logic_review_enabled` 缺省开。

- **M15-3 契约风格可配置**（新模块 `app/utils/contract_style.py`）：配置
  `contract_style: function | class | auto`（缺省 function 与 M15-1 一致）；
  auto = 首轮实现到达接口门禁时按实际代码顶层符号一次性反推回写契约
  （确定性零 LLM，审计落盘 `sessions/style_adaptation.jsonl`，同模块防震荡）；
  类式契约门禁按顶层类符号校验（`extract_public_defs` 去 self）。

- **M15-4 修复循环上下文增强**（`dev_loop._fix_context`）：修复轮提示词拼接
  ① 接口地图全文（全部模块契约，改动须保持兼容）+ ② 已通过依赖方对本模块
  API 的真实调用示例（每文件 ≤12 行 / ≤8 文件，防提示词膨胀）；无项目/契约/
  依赖方时行为与增强前完全一致。

- **M16-1 JS 静态危险扫描**（`local_executor` / `docker_executor`）：新增
  `scan_dangerous_js`——require/import 黑名单（child\_process/net/http/vm/
  worker\_threads 等）+ fs 删除改名类方法拦截 + eval/`new Function`/动态
  require 检测；JS 源码不再因「非 Python 语法」静默放行（清偿 M2-5 技术债）；
  Docker 链 node --test 改用显式 tap reporter（spec 格式无 `# pass N` 汇总行）。

### 测试

- 新增 `test_platform_policy`（门禁链接入 8 项）/ `test_budget_resume.py`（12）/
  `test_logic_review.py`（15）/ `test_contract_style.py`（22）/
  `test_fix_context.py`（10）/ `test_js_scan.py`（28）；既有并发/接口/
  Docker 测试随行为升级同步修正（逻辑审查 +1 次调用计数等）

- 全量回归：**874 → 986 passed / 7 skipped / 0 failed**（+112，目标 ≥880 已达成）

- 清理空残留文件 `app/utils/platform_policy.py.b64`

## v1.0 · V1 批次（2026-09-02，补录）：收敛手段——M14-3/4 + M15-1/2

> v1.0 Release 质量收敛第二批（规格 v1.0.md M14-3/M14-4/M15-1/M15-2）。

- **M14-3 平台约束注入**：`Settings.target_platform`（缺省 windows）+
  `platform_policy` 单一数据源，write\_code / fix\_code / write\_tests 提示词
  注入平台约束段
- **M14-4 危险扫描平台黑名单**：`scan_dangerous` 平台不可用模块清单
  （windows: fcntl/termios/pwd/grp/resource…），命中 BLOCKED，双执行器 +
  工厂透传
- **M15-1 拆分阶段契约风格约束**：interface/write\_code 提示词 API 风格约定
  （顶层可调用导出 + 正反示例）
- **M15-2 门禁报告修改指导**：`InterfaceIssue.guidance`——missing 附签名模板、
  extra 附处置二选一，门禁报告拼接指导
- 测试：**850 → 874 passed**（+24），0 回归

## v1.0 · V0 批次（2026-09-02）：机制堵漏——\_shared 合并守卫 + 全局链接门禁

> v1.0 Release 质量收敛第一步（规格 v1.0.md M14-1/M14-2）。
> 修复 v0.5 真实验收暴露的「\_shared 覆盖破坏」缺口，双重防线 + 端到端取证。

### 新增

- **M14-1 \_shared 符号级合并守卫**（`app/utils/shared_merge.py`）：
  `write_shared_file` 落盘前 AST 符号级合并——新版静默丢失的既有顶层符号
  （函数/类/常量，含多目标/解包赋值）自动保留；同名内容变更采用新版
  （LLM 修改意图优先）；显式删除须 `# DELETED: <name>` 注释标记
  （大小写不敏感、逗号批量）；语法解析失败回退整文件覆盖（门禁兜底）。
  合并动作写入项目日志（审计可查）。

- **M14-2 全局链接门禁**（`app/utils/link_check.py`）：
  门禁链新增第三层（静态 → **链接** → 接口 → 执行）——对全部已落盘模块
  （**含 FROZEN**，交付物仍会 import）+ 待验模块内存态，解析项目内
  import（`from <module>/<pkg>/_shared.<f> import <sym>`、`import <module>`）
  的符号存在性；包级 `__init__.py` star 重导出自动展开（file\_manager 约定）；
  缺失 → 阻断并输出「引用方文件+符号+来源+修复指引」精确清单。
  符号索引 mtime/size 增量缓存，DevLoopEngine 跨模块/跨修复轮复用。

### 修复（v0.5 验收真实缺口）

- **validate\_isbn 断裂事故根因消除**：v0.5 中后续模块重写 `_shared/utils.py`
  丢掉 `validate_isbn`/`validate_date` → book\_validator import 断裂静默流入
  交付物。现双重防线：合并守卫落盘即补救（覆盖写入不再丢符号）；链接门禁
  确定性兜底（守卫失效也拦截，含 FROZEN 模块断裂）。

### 测试

- 新增 `test_shared_merge.py`（14）/ `test_link_check.py`（10）

- 端到端取证脚本 `scripts/_v0_evidence.py`（v0.5 事故链路重放：双防线全过）

- 全量回归：**850 passed / 7 skipped / 0 failed**（基线 826 → 850，+24）

## v0.5.0-beta · 验收闭环（2026-09-01 补录，同日完成全部遗留项）

> 对 v0.5 Done 定义逐项实测验收（脚本 `scripts/_accept_*.py`，证据可复跑）。

### 验收结果

- **M11-3 模式推荐回放**：3 个历史项目需求回放，推荐与实际模式一致率 **3/3 = 100%**（KPI ≥80% 达标）；推荐理由引用真实历史数据（3 样本、safe 成功 2/3、均值 182,329 token → 预算 219k = 均值 ×1.2）；冷启动（不相似需求）缺省 safe 并说明理由

- **M12-3 Docker 未装降级路径**：`/api/docker/status` 三态正确（未装 → 明确提示 + 降级 process + 安装指引）；`build_executor('auto')` 自动降级 LocalExecutor；服务健康不受影响（Docker 沙箱 <5s 计时顺延——本机未装 Docker，需有 Docker 的环境复测）

- **M13-2 exe 产物复验**：体积 **75.2MB ≤ 80MB 达标**；冷启动实测 \~17s 未达 <2s——归因：安全软件（火绒）对未签名 exe 解压出的 5,580 个文件逐个实时扫描（\_MEI 目录时间戳证据：目录创建后 14.6s 最后一个文件才落盘，子进程随即出现）；改进路径：代码签名证书 / onedir 模式 / 用户信任区

- **M10 Researcher 真实链路**（陌生技术栈=标准库 cmd 模块 + 用户资料注入，auto 模式真实 LLM 全流程）：

  - `sessions/research_brief.md` 落盘，四段式（来源/版本/用法示例/坑点）关键词 4/4 命中

  - **PM 初始方案直接消费研究内容**（方案文本采用 cmd.Cmd/do\_\* 正确用法）；交付代码 `command_handler.py`、`book_manager.py` 均基于 cmd API 实现

  - 模块化拆分 8 模块全部交付（终态见下方质量发现）

- **M11-2 对话流图数据源**：`GET /api/project/{id}/messages` 返回结构化消息（role/model/round/content，PM 方案 + dev\_review 结构化打分 8/7/6）；events 阶段事件流正常

- **中断恢复（意外真实触发）**：首跑因 45 分钟验收脚本上限退出 → `interruption.md` 中断快照自动落盘 → `kind=resume` 续跑自动跳过已完成模块、续建剩余模块——断点续跑机制在真实链路验证通过

### 遗留项完成（同日，API 余额恢复后）

- **最后模块续跑完成**：模型余额分型号耗尽（glm-4-plus/air 不可用、4.5-air/4.6v/flash 可用）→ 快照模型替换为可用组合（主 glm-4.5-air / 开发 glm-4.6v / 测试 glm-4-flash，三模型互异保持）→ resume 续跑 **succeeded**：8/8 模块 + 8 份测试文件交付，interruption.md 按完成语义清除，cost\_report 终态落盘（本轮续跑 37,483 token：开发 35k + 测试 2.5k）

- **A/B 真实报告归档**（`logs/ab_reports/ab_20260901_181857.json`，20 条标准诉求 × 双模式）：单模式 18,133 token / 21 调用 / 0 误判；双模式 42,892 token / 53 调用 / 1 误判 / 快判承接 10/20（50%）。**结论：以 glm-4.5-flash 作快判时双模式反而多耗 136% token**（快判模型相对主力不够便宜 + 低置信升级路径翻倍调用）——KPI 未达（承接 ≥60% ❌ / 误判 <5% ❌ 边缘），**验证 fast\_triage 缺省关闭的设计决策**；正式启用需先换更廉价快判模型复测

### 真实质量发现（验收的意外收获，供 v1.0 参考）

- **接口门禁收敛率低**：cmd 图书管理项目 8 模块全部 FROZEN（各修复 5 轮达上限）；跨项目统计（todo-cli 7/7、contacts 5/7 FROZEN）显示冻结是常态。典型失败模式：**契约声明函数式 API（read\_file 等）而 LLM 坚持生成类式实现（FileManager 等）**，5 轮修复不收敛。门禁「宁严勿松、绝不静默放行」符合设计哲学，且冻结模块均落盘已知问题与降级方案；但提示两条改进线：① 模块拆分阶段的接口契约提示词强化（对齐 LLM 的实现偏好）；② 考虑契约风格可配置（函数式/类式）

- **\_shared 覆盖破坏**（真实缺口）：book\_validator 依赖 `_shared.utils.validate_isbn`，后续模块重写 `_shared/utils.py` 时丢失该函数 → 跨模块 import 断裂。「共享库变更整包回归」机制在该链路未拦截——需排查 shared\_check 的触发条件（疑似 resume 路径或重写判定盲区），建议 v1.0 修复

- **平台可移植性**：file\_utils 生成代码使用 Unix-only 的 `fcntl`（Windows 不可用）——该模块已冻结未放行，但提示提示词应注入目标平台约束（本项目交付环境为 Windows）

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

- **M12-9** 模型路由明细：call\_log 档位标注（`tier_map` 旗舰/主力/轻量）→ cost\_report 与实时看板新增 `by_tier`、逐调用档位列、实际成本 vs 旗舰假设成本对比（`model_prices` 价目表可配置，缺价 `available=false` 不误导）

- **M12-10** 插件消息协议契约测试（`vscode-extension/tests/contract.test.mjs`，Node 内置 runner 零依赖）：双侧源码提取 command 集合做闭合性断言

### 新增（M10-1\~10-4 · V0 批次）

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

- **M8-3** 异步任务 API：`POST /api/tasks`（kind=run/resume/feedback）提交即返回 task\_id；`GET /api/tasks/{id}` 状态查询；任务状态落盘 `sessions/task_state.json`（服务重启可恢复）；线程池并发 ≥4

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

