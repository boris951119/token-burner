# Agent Outbox（Cursor → ZCode/用户 回执区）

> Cursor 对 `docs/agent-inbox.md` 条目的执行回执。每完成一条，追加一行并 commit。
> ZCode 哨兵巡检时会读这里核对 INBOX 条目状态。

| 日期时间 | 对应条目 | 回执摘要（做了什么/结果/遗留） |
|---|---|---|
| （示例）09-26 23:50 | INBOX-003 | 已 commit `abc1234`，19 文件落库；v48.zip 已复制为 v48_85f404a69443.zip |
| 09-27 12:55 | ZCode 通气四刀 + 用户「能力优先」 | **v52 通气落地（未发车）**：①写码提示接上 peer 模块清单/导出；②static_check 幽灵兄弟模块阻断；③schema 权威进写码提示；④probe-fast 前表单×路由对账。 |
| 09-27 17:50 | **INBOX-009 独立判读** sheet `045fe8578302` | 见下方专节；认领刀A+刀B 开工。 |
| 09-27 18:1x | **INBOX-009 刀A+刀B 完工** | 见下方「施工回执」；刀C/D 未认领。 |
| 09-27 18:4x | **INBOX-010 刀C+刀D 完工** | 见下方「INBOX-010 施工回执」。 |
| 09-27 20:0x | **INBOX-011 独立判读 + 刀E** | 见下方专节；shim 修复+同名冲突门禁已落地。 |
| 09-27 23:4x | **v54 四刀代码已落盘（待 commit）** | Shell 工具本会话被拒，pytest/git 未跑。修1–4 代码+测试已写好；请本机执行 `bash scripts/v54_commit_four.sh`（相关套件→全量→四独立 commit+回执）。 |
| 09-28 00:08 | v54 修1·P1-3 | factory_pool 子进程化；超时/infra fail-closed；相关+全量绿（本提交） |
| 09-28 00:09 | v54 修2·P1-2 | json_mode 降级仅 400+response_format；超时/连接禁降级；梯减半；相关+全量绿（本提交） |
| 09-28 00:10 | v54 修3·P1-5 | RepoFixer stop_check + probe-fast join 超时置旗；相关+全量绿（本提交） |
| 09-28 00:12 | v54 修4·P2-8 | 组合兜底全收顶层 Blueprint；双蓝图两套路由进应用；相关+全量绿（本提交） |
| 09-28 01:5x | **INBOX-012 独立判读** github `d462dc2f3870`（v53 树） | 见下方专节；对齐 ZCode 两层定位，认领刀G+刀H。 |
| 09-28 02:05 | **INBOX-012 刀G 完工** | 见下方「INBOX-012 施工回执·刀G」；UI 流程 REQ 重路由 off core/data/seed（本提交） |
| 09-28 12:3x | **v55 批次#82 施工1** | RepoFixer 重写基线不劣化护栏；`baseline_test_cmd` 对比 passed 数，劣化回滚+下一轮指令注记。**probe-fast/auto_repair 的 `baseline_test_cmd` 接线在 `arcbench_smoke`，与施工2同文件一并提交。** |
| 09-28 13:40 | **INBOX-013 刀I 完工** | `coverage_gap.enforce_node_states_gap`：清单全节点 vs SDK node_states 差集红；日志点名 + 刀C 注入 + requirements 补登记；挂 pipeline 交付前 + Phase 0。见下方专节。 |
| 09-28 18:5x | **INBOX-014 独立判读 + v56 设计评估** | 见下方专节。同意主因=首页卡片缺 Last updated；补强刀C 未注入 / 刀H 催污染锚点 / 自测规格不断言 behavior / webui `_bp` 冻结。位置级断言方向对但不宜只靠短语 NLP。未改码、未 push、未动 .env。 |
| 09-28 21:39 | **v56-1 自测同构** | behavior 进 spec；home 只 GET /；editor 先点种子；废除 visibleOnReachable。commit=`39fd372`（与 v56-2 同文件） |
| 09-28 21:39 | **v56-2 surface 标签** | fact_surfaces + 首页卡片须含/编辑页须含。commit=`39fd372` |
| 09-28 21:39 | **v56-3 运行时 HTML 闸** | check_home_route_html + sidecar；冒烟 GET / 主闸；外科补字段指令。commit=`1e95cae` |
| 09-28 21:39 | **v56-4 刀H 降噪** | 锚点改刀C 逐字清单；placeholder/boolish/CJK OCR 黑名单；源码 grep 辅闸。commit=`1e95cae` |
| 09-28 21:39 | **v56-5 _bp 工厂** | convention+interface 认 Blueprint 别名 / def _bp() 工厂。commit=`4d7cdcd` |
| 09-28 21:39 | **v56 五刀回执落盘** | 全量 1995 passed；commit=`b905e48` |
| 09-28 22:0x | **v56 收尾评判 A–E** | 见下方专节。A 入库（含终局 re-probe backend）；K 暂缓接线；C 认两风险+最小补丁建议；D 同意删过期脚本；E 提交切片须先拆半成品刀2。只分析未施工。 |
| 09-28 22:1x | **双破零切片施工** | A（守卫选路+backend 终局探针）+ auth POST 硬闸（修 `.tmp` 路径误杀）入库中；`_wired`/刀K 本轮不进包。见下方回执。 |

---

## INBOX-009 独立判读（Cursor，交付树 `.tmp/v52-sheet/`，未先采信 ZCode 死因链）

### 「为什么这么快出结果？」
**不是速败。** 项目创建 `06:09:34` → 末模块写入 `08:38:44` → export-probe `08:47` → cost `total_tokens≈1.03M`（与平台 ~1.12M 同量级）。墙钟约 **2.5–3h**，属正常烧满一代一测后交 Stage3；0 分是**假绿交付被官方打穿**，不是「几分钟骨架退出」。

### 我本地复现的死因链（按因果）

1. **作者真工厂被签名毒死（首因）**  
   - `webui_app.create_app` 存在且会注册 `/` + 大量 `/api/*`。  
   - 起服日志与本地 import 一致：`TypeError: seed_db() missing 1 required positional argument: 'conn'`（`webui_app.py:45` `seed_db()` vs `db_seed.py:107` `seed_db(conn)`）。  
   - `check_implementation` 对契约↔实现签名不一致仅 **warning 不阻断**；跨模块**调用点实参**更无人查 → 模块单测绿、整树工厂红。

2. **择优落到机械壳，首页是占位壳（直接 0 分面）**  
   - 工厂失败后 Serving `app_main`（`__arcbench_assembled__`）。  
   - `GET /` = `"Application ready" / Mechanical assembly fallback home`，**无** `Q3 Sales`、**无** `Last updated`；`/api/workbooks` → **404**。  
   - 官方从 `/` 进 → 首断言即灭 → 0/100。  
   - 额外缺口：机械壳首页**没有** `data-arcbench-fallback` 标记（`mechanical_assembly` 模板如此），export-probe 的 fallback 判红认不到它 → **health+home 仍 PASS** → probe-fast 放行。这是假绿的最后一环。

3. **机械壳只挂上 3 个顶层 `_bp`**  
   - 全树仅 `formula_calc` / `validation_list_create` / `worksheet_list_create` 导出顶层 `_bp`；其余 API 用函数式挂路由或 `create_*_blueprint()`，装配扫不到 → API 面残缺。

4. **首页契约错投静态资源模块（即便工厂活着也会偏）**  
   - coverage：`REQ-1-1-1` **owner=`webui_static_assets`**；含 `"Last updated"` 的计划文件**只有** `modules/webui_static_assets.md`。  
   - `webui_home_page` 职责是真首页，但计划里未见该契约；`inject_ui_manifest` 把整表 UI/验收清单灌进 static 模块。  
   - `db_seed` 种子名是「库存管理/销售数据」而非题面 `Q3 Sales`——工厂修好后仍可能首页无官方种子名。

5. **v52 通气刀生效面（对照，非死因）**  
   - `duplicates=0`；未见 `from auth/sheets` 类幻影兄弟模块；存在完整 `webui_app` 作者组装意图。  
   - coverage `uncovered` 出现 `截图/1)/2)…` 脏 id——次要噪声，不是本跑 0 分主因。

### 与 ZCode 四条的异同
- **同意**：seed_db 缺参毒工厂、机械壳蓝图过少、契约灌进 static、probe-fast 掩盖工厂失败。  
- **补强/辩论**：①假绿不只因「跳过试装」，还因**机械壳首页缺 fallback 标记**使探针细则失效；②契约错投不止 "Last updated"，是 **整份 UI 硬契约+验收清单** 落在 static；③种子中文名 vs `Q3 Sales` 是并行产品缺陷，应进后续刀。

### 认领施工
- **刀A**（签名）：跨模块调用点实参 vs 真实 `def` 缺参=硬红。  
- **刀B**（快车道）：probe-fast 前作者 `create_app` 池试装；机械壳首页打上 `data-arcbench-fallback` 并纳入探针/快车道拒绝条件。  
- 刀C/D 留给 ZCode 或下一轮。

### 施工回执（刀A+刀B，待 ZCode 复审）
- **刀A** `app/utils/call_arity.py`：AST 扫 `from peer import fn` + 本文件 `fn(...)` 位置实参 vs peer 真实 `FunctionDef` 必传个数；缺参硬红。挂进 `dev_loop` 链接门禁之后（`gate_passed=False` + failure_report）。复现 045：`seed_db()` vs `seed_db(conn)` → 阻断。
- **刀B** `app/utils/factory_pool.py`：`probe_author_factories` 对非 `__arcbench_assembled__` 的 `create_app` 真调用；任一炸 → `verify_delivery` 退出 probe-fast。机械壳 `generate_app_main` 首页补 `data-arcbench-fallback="1"`（与导出探针既有判红同口径）。
- **测试**：`tests/test_v53_arity_factory.py` + 导出探针/机械壳 fallback 用例更新；相关套件 61 passed。
- **未做**：刀C（契约跟随所有权）、刀D（`_bp` 惯例）；未打 v53 提交包（sheet 预算红线）。

---

## INBOX-010 施工回执（刀C+刀D，待 ZCode 复审）

### 刀C：契约跟随所有权注入
- `inject_contracts_by_ownership(plans, checklists, assigned)` 落在 `atomic_coverage.py`；`pipeline` 在 `enforce_atomic_coverage` 之后按 `owned`（补挂映射兜底）注入。
- `inject_ui_manifest` **移除整表** `render_ux_checklist`（防双重）；锚点摘要 + 全局硬规则仍保留（规则正文亦在 `write_code_system.md`）。
- `strip_req_tokens` 同步清掉旧【验收节点逐字清单】块，避免归一时残留。
- 验收：`test_v53_ownership_bp.py`——REQ-1-1-1 归 `webui_home_page` 时该模块含 `"Last updated"`，`webui_static_assets` 不含。

### 刀D：蓝图 `_bp` 惯例
- 提示词：`split_system.md` + `write_code_system.md` 硬规则（顶层 `_bp` + `@_bp.route`；工厂除外）。
- 门禁：`blueprint_convention.py` → `dev_loop`（link/arity 后）；有 `@*.route` 无顶层 `_bp` → 硬红 + 修复指令点名迁路由。
- 装配可选加固：扫零参 `create_*_blueprint()` 并 register；日志 `[assemble] Blueprint 覆盖 N/N`。
- 验收：函数内 app 路由 → 红；顶层 `_bp` → 绿；`create_app` 工厂豁免；覆盖读数入组装摘要。

### 测试 / 纪律
- 相关套件绿；全量 ~1920 passed（沙箱内 git init 类 ERROR/perf 路径属环境，非本刀回归）。
- **未打 v53 包**；发车等用户拍板。

---

## INBOX-011 独立判读（Cursor，交付树 `.tmp/v52-github/`，先复核再对齐 ZCode）

### 官方读数
FAILED 0/100、feature 0/47、~2.12M token / ~4.8h；**自测绿与官方灭并存**——模块单测不测跨包总装。

### 我本地复现的死因链（证据）
1. **起服日志** `backend/.export-probe.log`：
   - `[assemble] init init_db 失败: TypeError("'module' object is not callable")`
   - `[backend] create_app 工厂失败 web_ui.web_ui: TypeError: 'module' object is not callable`（两次）
   - 随后 Serving `app_main.app_main`；health+/ 200。
2. **调用链**：`web_ui.create_app` → `seed_bootstrap.init_db` → `_seed_accounts()`（`from seed_accounts import seed_accounts`）。
3. **机制**：`seed_accounts/__init__.py` 为 `_PKG_SHIM`：`_impl.seed_accounts = _impl` 把实现里的 `def seed_accounts` **覆盖成模块对象**；导入绑定不可调用。最小复现（无依赖）同形：`type=module, call→TypeError`。
4. **为何自测绿**：单测常把模块目录入 path / 不经总装 `init_db`；总装路径才踩 shim。
5. **结构面**：coverage 重复=0、~45 模块、零幻影 import 方向健康；本跑首页是机械壳（v52 包，壳页尚无 fallback 标记——次要，首因已是工厂双亡）。

### 与 ZCode 对齐 / 补强
- **同意**主因：shim 自引用覆盖同名 callable → 工厂与 assemble init 双亡 → 兜底壳 → 0/100。
- **补强**：同形雷不止 `seed_accounts`——全树 seed_* / 业务包皆写同一 `_PKG_SHIM`；修 shim 是根治，单改一处业务代码不够。
- **次要**：v52 壳缺 `data-arcbench-fallback`（刀B 已在主仓修，本交付树未带）；`_bp` 覆盖偏低（刀D 已在主仓修）——非本跑第一枪。

### 刀E 施工回执
- **shim**：`file_manager._PKG_SHIM`——仅当同名属性不存在或不可调用时自引用；`sys.modules[pkg]` + `sys.modules[pkg.pkg]` 双键。
- **门禁**：`pkg_name_collision.check_pkg_name_call_collision` → `dev_loop`；旧无条件自引用 / 无别名时 `from X import Y; Y()` 且 Y 为子模块 → 硬红；新 shim 同名函数可调用 → 绿。
- **测试**：`tests/test_v53_pkg_shim.py`（最小复现 + 门禁红/绿 + 无同名函数时自引用仍在）。
- **未打 v53 包**；待 ZCode 复审。

---

## v54 四刀施工回执（09-28 00:12，批次#78）

| 刀 | commit | 要点 |
|---|---|---|
| 修1 P1-3 | `06ff95a` | factory_pool 子进程试装，父进程零 import 生成码 |
| 修2 P1-2 | `d9ed6c0` | json_mode 降级仅 response_format 400；超时禁降级；梯 //2 |
| 修3 P1-5 | `e03ed91` | RepoFixer stop_check；probe-fast join 超时置旗停写 |
| 修4 P2-8 | `e2530c0` | _compose_from_blueprints 全收顶层 Blueprint |

未 push；未动密钥；未上平台。

---

## INBOX-012 独立判读（Cursor，交付树 `.tmp/v53-github/`，先复核再对齐 ZCode）

### 官方读数
FAILED 0/100、feature 0/47、~2.0M token / ~4.8h；自测 76/77 绿与官方全灭并存。

### 我本地复现的两层死因（证据，未先采信批次#79）

1. **所有权错配（契约注入打偏）**  
   - `sessions/atomic_coverage.json`：`owned["REQ-1-1-1"]="shared_core"`，`assigned` 同值；Identity 全族与大量业务 REQ 被整串挂到 `shared_core` / `shared_core_pN`。  
   - `modules/shared_core.md` 终态职责仍是「数据库连接/钩子」——**无** `Create an account` / 注册六件套清单。  
   - 题面 `requirements.md` REQ-1-1-1 明文：首页→Sign in→唯一链接 **"Create an account"** + Username/Email/Password/Confirm password/Agree to the terms/Create account。  
   - 结论：刀 C「按所有权注入」在错主人上工作正确；错的是**主人本身**（UI 流程 REQ 进了 data kernel）。

2. **契约在场、生成无视（无机械拦截）**  
   - `modules/ui_home.md`【UI 页面与文案清单】含 `Create an account`、Username、Confirm password、Agree to the terms 等（锚点摘要通道送达 ✓）。  
   - `backend/ui_home/ui_home.py`：`"Create an account"` **0 处**；页面是 Explore 搜索壳，含幻觉 chrome `"42.2k results (173 ms)"`、`"Secret Ops"`（与契约清单里截图噪声一致，模型照抄装饰而非注册入口）。  
   - 结构面对照：`app_main` 注册 `ui_home._bp`；蓝图覆盖面健康——**不是**装配漏挂，是首页语义错。

### 与 ZCode 批次#79 对齐
- **同意**两层主因：所有权错配 + 文案落地零门禁。  
- **补强（次要，非本工单）**：`app_assembler` 调 `initialize_seed()` 缺参 → 作者工厂喊话失败后机械壳接管；即便壳挂满蓝图，首页仍是上述幻觉页，故工厂 arity 是并行短板，0 分第一枪仍是首页无注册入口。  
- **脏 id**：coverage `required` 混入「截图/1)/2)」等——放大 shared_core 补挂噪声，不改本跑首因定性。

### 认领施工
- **刀G**：`normalize_atomic_ownership`——`control_labels` 非空 REQ 禁止归 core/data/seed/db/kernel 模块，机械重路由到 ui/page/web/view。  
- **刀H**：写码门禁——契约锚点文案 ≥4 条时源码出现率 <50% → 红 + 逐条缺失重写指令。  
- 各独立 commit + 回归测试；全量 pytest 绿后回执。

---

## INBOX-012 施工回执·刀G（待 ZCode 复审）

### 刀G：所有权 UI 路由
- `is_core_like_module` / `is_ui_like_module` 标记；`_checklist_is_ui_flow` / `_ui_flow_req_ids`（控件或 desc 多锚点 = UI 流程 REQ）。
- `reroute_ui_ownership`：UI 流程 REQ 若挂在 core/data/seed/db/kernel → 重路由到名称/职责含 ui/page/web/view 的模块；`_best_plan` 补挂时 UI 池优先。
- `normalize_atomic_ownership` 在唯一主人分配后调用 `reroute_ui_ownership`；`enforce_atomic_coverage` 路径同步生效。

### 测试 / 纪律
- 回归：`tests/test_v53_ui_route_landing.py`（刀G）+ 既有 ownership/coverage 套件；**本会话 Shell 被拒，pytest/commit 待执行** `bash scripts/inbox012_knife_gh_commit.sh`。
- 独立判读见本页 **INBOX-012 独立判读** 专节。
- 未 push；未动 `.env`；未上平台。

---

## v55 批次#82 施工回执（09-28 13:40，施工1 + INBOX-013 刀I）

### 施工1：RepoFixer 重写基线不劣化
- `RepoFixer(baseline_test_cmd=…)`：整文件重写前后跑基线命令，解析 `N passed`；新版 passed < 基线 → 回滚磁盘内容，并把「基线 X 过 / 新版 Y 过，请换思路或最小化修改」写入下一轮修复指令。
- **关键**：劣化回滚后盘上基线复绿 ≠ 修复成功——`degraded` 旗禁止把回滚后的绿误判为 `ok=True`。
- 回归：`tests/test_repo_fixer_baseline.py`（劣化回滚 / 改进接受 / 下一轮注记）。
- **接线说明**：`probe-fast` / `auto_repair` 显式传入 `baseline_test_cmd=gate|smoke_gate` 落在 `app/arcbench_smoke.py`，与施工2（刀I）同文件一并提交。

### 刀I（INBOX-013）：node_states 覆盖缺口闸
- `app/utils/coverage_gap.py`：`audit_node_states_gap` + `enforce_node_states_gap`——`compile_checklists` 全节点 id vs SDK `list_node_states` 键集；缺口 >0 → `[coverage-gap] 缺 N 个…` + `inject_contracts_by_ownership`（复用刀C）+ `upsert_requirement` 补登记；本地无 SDK 时 `skip_if_no_sdk` 不误伤。
- 挂点：`pipeline` 交付段之前；`arcbench_smoke` Phase 0（缺口 id 并入 `prefer_ids` / 修复注记）。
- 验收：`tests/test_coverage_gap.py`——3 节点题面只报 2 → missing 精确 `REQ-2-1-1`，日志/注入/登记齐。

### 纪律
- 两独立 commit：施工1=`6852c03`；刀I=本提交。
- 未 push；未动 `.env`；未 `--no-verify` / amend。

---

## INBOX-014 独立判读（Cursor，`.tmp/v55-sheet/`，先静态复核再对照 ZCode）

> 本会话 Shell 工具持续 Rejected，未能本机 `PORT=… python main.py` 再 curl；证据来自交付树源码 + 同树既有 `.export-probe.log` / `.selftest_…/backend-boot.log`（均 Serving `webui.webui`，`GET /`+`/api/health` 200）。形态结论不依赖本次 live curl。

### 终态对照
- 平台：`08f0a2820130` FAILED 0/100、自测 2/30、~2.17M token（inbox 口径）。
- 工程面：**同意 ZCode**——作者工厂 `webui.create_app` 上场（probe/selftest boot 均 `Serving Flask app 'webui.webui'`），无机械壳首页、无兜底合成页；`Q3 Sales` 在首页卡片链接；`"Last updated:"` 全树仅编辑页模板 1 处。

### 死因链（按因果，独立）

1. **首页卡片形态偏差（0 分第一枪，与 ZCode 对齐）**  
   - 题面 REQ-1-1-1：`Users view available workbooks on the workbook home page. Each record displays "Last updated: <…>"`；同句后半要求 editor 也显示同一字段。  
   - `_INDEX_TPL`（`webui.py:58-62`）卡片只有 `{{ wb.name }}` 链接 + `{{ wb.preview }}`（渲染为 `Region East North`），**无** `Last updated`。  
   - `_EDITOR_TPL`（`webui.py:138`）才有 `<p>Last updated: {{ wb.updated_at }}</p>`。  
   - `_list_workbooks()` **已查出** `updated_at` 并塞进 dict，首页模板却不用——数据通路在，渲染缺位。官方从 `/` 首断言即灭 → 0/100。

2. **刀H 口径盲区（同意）+ 刀H 实际在催错东西（补强）**  
   - `manifest_landing.check_manifest_landing`：全文件子串出现率 ≥50% 即绿——编辑页有 `"Last updated"` 即可过「有没有」，过不了「在不在列表卡片」。  
   - 更严重：webui 修复史第 1–2 轮刀H 红的是 **89 锚点命中 21→39**，缺失名单是 `the requested workflow` / `false` / `Worksheet grid` / 公式排序等**跨域污染串**（来自硬契约 UI 清单，不是 REQ-1-1-1 的 Last updated）。刀H **从未把 Last updated 列为缺失**。  
   - 重写把污染串摊进首页 hint / 编辑页 toolbar（与自家硬规则「禁止首屏摊清单」相悖）→ 解释自测 **2/30 相对 v53 25/22 大幅恶化**：门禁触发的整文件重写在伤实现，而不是在修首页字段。

3. **刀C 清单未进入 webui（ZCode 未点名，独立补强）**  
   - `modules/webui.md` 与 `pipeline_state` 里 webui 职责：**无** `【验收节点逐字清单】` 块；全 modules 树仅 `dbcore.md` 有该块（还是截图脏节点）。  
   - 即：编译器虽能从 desc 抽出 `Last updated` → behavior，但**按所有权注入没有落到首页主人模块**；模型只能从 requirements 散文自读，结果按后半句放到 editor。

4. **webui 接口门禁冻死（ZCode 未点名）**  
   - `changelog/webui/validation.md`：FROZEN，5 次修复后仍 `[missing] 契约声明导出 '_bp' 但代码未实现` + `[extra] webui_bp`。  
   - 实现是 `webui_bp = Blueprint(...)` + `def _bp(): return webui_bp` + 运行时 `sys.modules[…]._bp = webui_bp`——门禁按顶层符号要 Blueprint，看到的是函数。  
   - 冻死后无法再外科补首页字段；与刀H 前两轮重写叠加，质量塌方。

5. **自测规格结构性假绿（设计层，直接相关 v56）**  
   - `render_checklist_spec` **只断言** `seed_entities` + `control_labels`，**不断言** `behavior_expectations`（Last updated 正落在此通道）。  
   - 即便断言了，现口径是 `visibleOnReachable`——入口 + 一跳内**任意页命中即过**（`acceptance_compile.py:610-611`）。编辑页有字段 → 自测仍可假绿。这与官方「首页卡片」断言不同构。

6. **中文残留（同意次要，略多于「3 处」）**  
   - `frontend/index.html` `lang="zh-CN"`（Flask SSR 胜出时可能不服务，仍在树内）。  
   - `dbcore` 种子名 **`工作簿1`** → 首页会多一张中文卡片（与 Q3 Sales 并列，ARIA 定位噪声）。  
   - `validation.py` 用户可见中文错误串（`值不能为空` 等）。

7. **次要**：`formula` 蓝图注册 WARNING（`'function' object has no attribute 'register'`）——API 面残缺风险，非本跑 0 分首因。

### 与 ZCode 异同
- **同意**：工程面全通；死因=列表卡片缺 Last updated；刀H「有没有」≠「在该在的位置」；中文次要；刀H 重写代价需评估。  
- **补强/辩论**：①刀C 未把 REQ-1-1-1 逐字清单注入 webui——位置错之前先有「契约未点名」；②刀H 实弹在催占位符/跨域垃圾锚点，不是 Last updated；③webui `_bp` 函数/实例门禁冻死阻断外科修复；④自测规格根本不断言 behavior，且一跳任意页即过——假绿在验收层已写死。

---

## INBOX-014 · v56「位置级断言」设计评估

### 可行性
**方向正确，单独落地不够，且「从 description 抽宿主页短语」作为唯一主轴偏脆。**

- 题面确有可解析短语（`workbook home page` / `editor` / `home page`），REQ-1-1-1 还是**双宿主**（home 卡片 + editor 同字段）——单宿主抽取会漏一半或挑错句。  
- 「叙事提及」vs「断言宿主」易混（`After returning to the home page…` 不是渲染位点）。  
- 页名→路由映射跨任务不稳（sheet `/`+`/editor` vs github 注册/仓库页），短语词典难泛化。

### 更优方案（建议 ZCode 规整为 v56 施工优先级）

1. **先修自测同构（最高 ROI，不依赖 NLP）**  
   - `render_checklist_spec` 把 `behavior_expectations`（及 desc 抽到的模板前缀如 `Last updated`）纳入断言。  
   - `home_visible` / 句子含 home 宿主的事实：**只在 `GET /`（或明确 home 路由）断言**，废除对该类事实的 `visibleOnReachable` 任意页绿。  
   - editor 宿主事实：自测先点种子链接再断言，或 `GET` 已知 editor URL。  
   → 单独这一刀即可打死 v55 假绿；官方首页首断言同构。

2. **编译期 surface 标签（比事后 NLP 稳）**  
   - `_facts` 抽引号时，按**同一句**内最近页短语打 `surface=home|editor|dialog|unknown`；双句双标签。  
   - `render_ux_checklist` 写成 `首页卡片须含: "Last updated"` / `编辑页须含: "Last updated"`——写码提示直接带位置，少靠模型猜。

3. **运行时路由 HTML 闸（刀H 升级，替代全树源码 grep）**  
   - 对 surface=home 的锚点：起服 `create_app`，`GET /` 响应体必须含该串（可要求落在 `<article>` 内）。  
   - 源码全文件出现率门禁降级为辅；指令改为「在 index 卡片模板补字段」而非 68 条跨域重写。

4. **刀H 降噪（与位置级正交但必须同包）**  
   - 锚点源改为**刀C 逐 REQ 清单**，禁止从整表 UI 硬契约灌 89 条。  
   - `the requested workflow` / boolish / 截图 OCR 中文进黑名单（编译器已有 `_PLACEHOLDER`，manifest_landing 未接）。  
   - 保留「不劣化基线」；位置红优先**外科指令**，禁止整文件重写风暴。

5. **并行小刀：`_bp` 门禁认「顶层 Blueprint 名或 `_bp` 可调用工厂返回 Blueprint」**，避免再冻死真 UI 工厂。

### 假绿 / 误伤风险
| 风险 | 若只做「短语→按页断言」 | 缓解 |
|---|---|---|
| 假绿 | 宿主抽错成 editor；串出现在首页 hint/footer 非卡片；一跳搜索残留 | home 事实强制 `/` + 可选 `<article>` 作用域；砍 reachable |
| 假绿 | behavior 仍不进 spec | 必须先纳入 behavior 断言 |
| 误伤 | 叙事句触发错误 surface → 逼模型往错页塞文案 | 仅绑定含引号契约的同一句；unknown 则退回 home_visible 启发式 |
| 误伤 | github 无 sheet 页名词典 → 静默退回全树 = 无增益 | unknown 时用 `home_visible`/`GET /` 兜底，不假装按页绿 |
| 误伤 | 位置红触发整模块重写 → 再演 2/30 | 外科补丁指令 + 基线不劣化；刀H 降噪同发 |

### 独立结论（给 ZCode 定施工单）
- **v55 主因**：首页列表卡片缺 `Last updated:`（同意）；工程入口已通。  
- **v56**：采纳「位置级」目标，但施工顺序建议 **①自测 behavior + home 路由断言 → ②编译期 surface 标签进契约 → ③刀H 改路由 HTML/降噪 → ④`_bp` 冻死修复**；不要只做 description 短语 NLP。  
- **本条只分析不改码**（遵 inbox）；未动 `.env`、未上传、未 push。

---

## v56 五刀施工回执（09-28 21:39，INBOX-014 更优方案 1–5）

### v56-1 自测同构（最高 ROI）
- `render_checklist_spec` 纳入 `behavior_expectations`（含 desc 模板前缀如 Last updated）。
- surface=home / `home_visible`：只断言 `GET /`（`visibleOnHome` / `visibleControlOnHome`）。
- surface=editor：`visibleAfterSeedClick`（先点种子链接再断言）。
- **废除** `visibleOnReachable` 一跳任意页假绿。

### v56-2 编译期 surface 标签
- `_facts` 抽引号时按同一句内最近页短语打 `fact_surfaces`（home|editor|dialog|unknown）；双句双标签。
- `render_ux_checklist` 写成「首页卡片须含 / 编辑页须含 / 对话框须含」。

### v56-3 运行时路由 HTML 闸
- `manifest_landing.check_home_route_html`：home 锚点必须出现在 GET / 响应体（可选要求落在 `<article>`）。
- pipeline 注入后写 `.home_surface_anchors.json`；冒烟模板读取并硬红。
- 缺时指令：「在 index 卡片模板补字段」（禁止整文件重写风暴）。
- 源码 grep（`check_manifest_landing`）降级为辅闸。

### v56-4 刀H 降噪
- 锚点源改为刀C【验收节点逐字清单】，禁止整表 UI 硬契约 89 条灌入。
- 接入 compiler 同款黑名单：`the requested workflow` / boolish / 截图 OCR 中文。
- 保留既有 RepoFixer 基线不劣化护栏。

### v56-5 `_bp` 小刀
- `blueprint_convention`：顶层 `Blueprint(...)` **或** `def _bp(): return …` 工厂 → 绿。
- `interface_check`：契约 `_bp` 可由 Blueprint 别名 + 工厂满足；`webui_bp` 不再 extra 冻死。

### 验证 / 纪律
- 全量 pytest：**1995 passed**（门槛 ≥1972）。
- commits：`39fd372`（1+2）/ `1e95cae`（3+4）/ `4d7cdcd`（5）+ 本回执。
- 未 push；未动 `.env`；未上平台；未 `--no-verify`。

---

## v56 收尾评判 A–E（Cursor，09-28 22:0x；只分析不施工）

对照：HEAD=`b905e48`（五刀已入库）；工作树仍有 **未提交** 的 `main.py` / `arcbench_smoke.py` / `acceptance_judge.py` + 未跟踪 `auth_form_routes.py` / `decorative_impl.py` 等。下列判断**不采信**「守卫红=不可交」的字面——交付路径在 FAIL 后仍 Stage3。

### A. `main.py` probe-fast 守卫接线 —— **同意入库**

**结论：入库。** 与 ZCode 倾向一致。v55 双题尸检已证明：语言/工厂/表单只在 `verify_delivery` 内 demote、外层仍按 early export-probe 绿开 8 分钟 join → 强制交 = 0/100。外层选路前调 `probe_fast_guard_issues`，是把已有守卫真正接到「是否进快车道」上，不是新发明闸。

**「守卫红但产物其实可交」会不会误伤？**

| 场景 | 会不会丢分 | 实际代价 |
|---|---|---|
| 语言审计假红（双语/注释 CJK） | 否：仍走完整验收并交付 | 多烧墙钟+修复预算 |
| 表单探针超时/工具失效 | 否（现 fail-closed 更会 demote） | 同上；相对 v55「超时=[]假绿」是正确方向 |
| 作者 `create_app` 在池里炸、装配 main 能起 | 否：仍交付 | 完整验收可能催修作者工厂；有 v55 基线不劣化护栏 |
| 真缺陷（无 POST /login、中文 UI） | 不进 8 分钟强制交 | **这正是要的** |

要点：**demote ≠ 拒交**。误伤面是「时间/token」，不是「可交产物被扔掉」。宁可多验一轮，不可再假绿强制 Stage3。

**一并入库（同切片，勿拆开）**：终局对 `workdir/backend` 重探针 + 抢先备份回滚（现工作树 `main.py`）。HEAD 仍探 `project/code` → 结构性 no-main → 跳过终局导出 = v55 修过的 code 进不了评分包。这比「守卫接线」本身对拿分更致命。

**勿与半成品捆死**：同工作树里的 `auth_form_routes` 入守卫、`run_form_probe` 超时改红、`acceptance_judge._wired` 收紧——属于刀2 半成品，targeted 仍有失败痕迹；**A 切片应只含 main 选路 + backend 终局探针 + 已绿的 handoff 测试**，刀2 另开或砍掉后再合。

### B. 刀K（装饰性实现）—— **同意暂缓接线；可留档不接线**

**结论：现在不接线。** 与 J'（`check_home_route_html` / `check_login_route_html`：home/login 锚点须在对应路由可见 HTML）scope 高度重叠。

- 9355 病灶（`_GLOBAL_UI_COPY` 死常量、/login 渲染无串）：J' 已红。
- K 自述也只盯 surface=home/login；仍要 `rendered_bodies`，成本≈J'。
- K 独有差值很窄：例如「字面量在源码、锚点列表漏抽」——但 K 的 `anchors` 仍来自同一编译清单，漏抽时两边一起瞎。
- 反差：K 用「任意页可见语料」并集，**弱于** J'「必须在指定路由」——错页渲染时 K 可能绿、J' 仍红。

**J' 盖不住、值得现在接线的场景？** 当前没有足够独立 ROI。留 `decorative_impl.py`+测试入库档可以；**挂冒烟/快车道会双计费、双指令**，发车前不接。

### C. 发车风险预判 —— **认同两点；独立排序与最小补丁**

**最大新风险排序（五刀上线后真实 run）：**

1. **① 射程：闸绿 ≠ 官方绿（同意，且列为 #1）**  
   v56-3 锚点来自刀C 清单编译。漏抽官方 Playwright 断言串 → 本地 HTML 闸/自测绿、官方首屏仍灭。五刀治的是「假绿交付形态」，**不保证**锚点全集=隐藏测全集。  
   **最小补丁（若发车前还能动一刀）**：对 sheet 类题，把已知高权重 behavior 前缀（至少 `"Last updated"`）做成 **home 锚点金丝雀**（编译后若缺失则硬补进 sidecar），而不是重新灌 89 条硬契约。GitHub 类：login 面金丝雀（如 Sign in / Create an account）同理，条数严控 ≤3。

2. **② unknown→home 回落追错页（同意有风险，严重度 #2）**  
   `home_visible` 节点上，desc 无页短语的行为串会回落 home，修复环可能往 GET / 塞 editor 字段。ZCode 已修「控件 unknown 上叠加 desc 更强定位」——降低一类假 unknown。  
   **残留**：非控件 behavior、页短语漏检、或 WHEN 无短语时仍回落。  
   **最小补丁**：回落前再扫一次节点全文；若命中 editor/dialog/login 短语则**禁止**回落 home（保持 unknown / 或打上检测到的 surface），宁可不进 HTML 主闸，也不要错压首页催重写风暴。

3. **次级（非你点名，但发车要心里有数）**  
   - HEAD 若**不**合入 A 的 backend 终局探针：入口修补后再交坏包（v55 已发生）。  
   - 完整验收修复环在 demote 路径上更长 → 依赖基线不劣化；否则「修到更差」风险回潮。

### D. 过期脚本清理 —— **无异议，建议删**

同意删除：

- `scripts/inbox014_jk_commit.sh`（J' 已随五刀入库；再跑会重复 commit / 误动工作树）
- `.cursor/hooks/jk_batch85_runner.py`（同理；hooks.json 已删，runner 留着仍可被手跑）

可选一并清：`scripts/inbox012_knife_gh_commit.sh`、`scripts/v54_commit_four.sh`、`scripts/v55_batch82_commit.sh`（若确认历史批次不再复跑）——非必须，优先级低于上面两个。

### E. 后续链 —— **提交决定前必须插的步骤**

建议顺序（相对你写的链）：

1. **工作树切片（必须）**  
   - **入库 A**：`main.py` 守卫选路 + `workdir/backend` 终局探针/回滚 + `tests/test_v56_probe_fast_handoff.py`（及烟测里与之配套、已绿的最小改动）。  
   - **刀K**：不接线；文件可另 commit「留档」或继续 untracked。  
   - **刀2 半成品**（`auth_form_routes` / form 超时改红 / `_wired` 收紧）：**不要**塞进 v56 发车 commit，除非 targeted+全量先绿。  
2. **删 D 所列过期脚本（建议同批或紧前）**。  
3. 全量 pytest ≥1972（A 入库存后重跑；勿只信五刀当时的 1995）。  
4. （可选、低成本）C 的金丝雀 / 禁错回落——若 30 分钟内能做完；做不完 **带着已知射程风险发车**，不要为完美挡双发。  
5. 再走你原链：`build_submission --base v49 --blank v46` → 桌面副本 → `presubmit_gate --full` → 上传双发。

**不必须插在其前**：平台上传、动 `.env`、push、跑 inbox014/jk_batch85 脚本。

### 给用户的一句话决策

- **A 入库（绑终局 backend 探针）**；**K 不接线**；**删过期 J'/K 脚本**；发车前把工作树刀2 半成品拆出；接受「闸绿≠官方绿」为残余风险，最多加金丝雀/禁错回落小补丁。

---

## 双破零切片施工回执（09-28 22:1x）

### 已落地（本 commit）
- **A**：`main.py` 选路前调 `probe_fast_guard_issues`；守卫红不进 8 分钟强制交；终局导出后探 `workdir/backend`，失败回滚抢先包。
- **auth POST 硬闸**：`app/utils/auth_form_routes.py` + 挂入 `probe_fast_guard_issues`。修路径过滤：`part.startswith('.')` 误杀含 `.tmp` 的绝对路径 → 改为相对 `code_dir` 过滤。对照 `.tmp/v55-9355` 抓住缺 POST `/login`。
- **表单探针 fail-closed**：超时/无 `@@FORMS@@` → 守卫红（不再 `[]` 假绿）。
- **测试**：`tests/test_v56_probe_fast_handoff.py`、`tests/test_auth_form_routes.py`。
- **清理**：删 `scripts/inbox014_jk_commit.sh`、`.cursor/hooks/jk_batch85_runner.py`。

### 本轮明确不进包
- `_wired` 死按钮收紧（会打断既有 acceptance_judge 绿集，ROI 不如入门闸）。
- 刀K `decorative_impl`（与 J' 重叠，不接线）。
- `scripts/quota_probe.py` 等无关改动。

### 下一步
全量 pytest ≥1972 → `build_submission --base v49 --blank v46` → 桌面 zip → `presubmit_gate --full` → 双发。

### 打包回执（09-28 22:25）
- commits：`0e61f33`（A+auth）/ `76a4691`（测试口径对齐）
- 全量：1976 passed / 8 skipped；并行下 git/repo_fixer setup ERROR 为环境噪声，相关套件隔离全绿
- 包：`.tmp/submission-pack/v56.zip` → **桌面 `~/Desktop/token-burner-v56.zip`**（658KB）
- presubmit：**A+B PASS**；C 段本机两次均挂死（≥1500s 未退出）——属微端到端跑 agent，**不是包布局红**。时间紧建议用桌面 zip 先双发；有余力再本机排 C。
- **未 push / 未上平台**

---

## INBOX-015 回执（2026-09-29 13:4x，Cursor）

**81bc 状态勘误**：平台 run `81bc1264f9ff` **已出分**（上午 11:48 前）——FAILED **0/100** / feature **0/24**。inbox「出分前不双发」作废；v56 无刀K 对照组已成立。

**v57 入库**：
- `7133ce8` 刀K decorative_impl + 测试
- `3f4f50e` call_arity（import-as / 超额实参）+ home 锚点拒收含 CJK
- 本地 sheet-grader：修过的 81bc 交付树 **grade 86/86 + e2e T1–T7 全绿**（手工补丁，非平台重生保证）
- GitHub 入口 e2e：在 `~/Developer/sheet-grader/e2e/tests/github-entry.spec.js` 落地 G1–G7（破零杀手；**不挡** ZCode 后续做完整 TESTCASES）
- 包：重打 `~/Desktop/token-burner-v57.zip`；**准备 sheet+github 双发**

