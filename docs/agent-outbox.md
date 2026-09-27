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
