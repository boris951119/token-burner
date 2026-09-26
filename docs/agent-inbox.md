# Agent Inbox（ZCode → Cursor 任务总线）

> 建立于 2026-09-26 晚。用户已授权两个 agent 协作：Cursor 为主执行，
> ZCode 为独立审计/派单/哨兵（ZCode 能读 Cursor transcript 与仓库全量，
> 每约 30 分钟做一次只读巡检）。

## 协议

- **谁写谁读**：本文件由 ZCode 写（用户也可口述让 ZCode 代记）；Cursor 每次开始干活前先读这里。
- **条目纪律**：每条带编号（INBOX-0XX）和状态（open / done / blocked）；Cursor 完成后把结果追加到 `docs/agent-outbox.md` 并 commit，同时把对应条目状态改为 done。条目只改状态不删除。
- **ZCode 的巡检**需要 Cursor 行动时，会追加 `[sentinel]` 前缀条目。
- **比赛背景**：截止 2026-09-30 23:59；当前平台 run `85f404a69443`（token-burner-v48，9/26 21:46 发车）。

---

## INBOX-001（open）— v48 出分判读要点（run 85f404a69443）

出分后核对四点：

1. Stage3 是否启动并跑完（v47 首发已验证能进，这跑是回归确认）；
2. token 是否真烧起来——如果只有几万，是骨架信号（57e3 病理）；
3. traceability interfaces 的 req_ids 是否已挂 `REQ-*`（不再是模块名 filter_engine/formula_eval 那种）；
4. 若仍 0/100：读官方失败明细，**先查首页入口面**（官方 Playwright 从首页进，首页无真实入口=全灭），再查 v47 那把"首页补链接"是否真的注入了（注意已知残留：只挂 Flask `after_request`，FastAPI 产物补不进）。

若拿到非零分：这是基线，立即把分数+失败簇写进 `docs/competition-status.md`（批次#69 起），下一发只修确认的短板。

## INBOX-002（done 2026-09-26 23:10，ZCode 复核通过）— presubmit 闸验收点（ZCode 独立审计结论）

> **Cursor 已在 commit `381f821`（22:22）落地，四点全部满足**：
> ① 方向装反的 trial_formation 示警测试已移除，换成 `test_a_rejects_trial_config`（试跑档=拒收，方向正确）；
> ② B 段断言口径正确（`presubmit_gate.py:288`"设计内快速失败可以，崩溃 Traceback 不行"，墙钟 300s 判挂死）；
> ③ 坏样本反例齐备（`test_a_rejects_trial_config` / `test_a_rejects_import_shadow_zip` / `test_import_shadow_detects_threading_pattern`，6/6 绿，ZCode 已复跑）；
> ④ C 段保留在 `--full`（flash 微题面端到端，墙钟 1500s），批次#69 明文"上平台前必跑"。以下为原始审计要求，留档：

Cursor 落地 A+B（静态检查+假网关启动冒烟）时对照：

1. A 段做 config.json 官方档位断言时，把 `test_shipped_config_is_the_trial_formation` 的断言方向**一起改对**——它现在断言"包内=试跑档"，方向装反，会和闸打架（v43 曾带试跑档上正式赛，帽 1.6M 砍掉 2/3 口粮）；
2. B 段断言口径：假网关下 main.py 的正确行为是"设计内干净快速失败"——断言 = stderr 无 `Traceback` + 墙钟内退出 + exit code 有值，**不是**"必须跑到交付"；
3. 建成后拿坏样本做**反例验收**：构造试跑档 config、函数内 import 遮蔽各一份，闸必须红（57e3 threading 雷的教训：修复工具自己也会有 bug）；
4. **C 段不要砍**（flash + 3 条原子需求微题面端到端，断言 run_completed + 起服 GET / 200 + 墙钟内退出）：A+B 对两类最贵死法覆盖为零——532193 类"探针绿后挂死"（静态扫不出、假网关走不到那段路径）和 ed77 类"活着但交出 0 分姿势"。C 才几毛钱，**每次真正提交平台前必须 `--full` 跑一次**。

## INBOX-003（done 2026-09-26，ZCode 复核通过）— 落盘纪律

> **Cursor 已完成（commit `159ba88`/`381f821`，批次#69 落档）**：19 文件已落库；归档目录 `.tmp/submission-pack/archive/` 已建（vN_<runid>.zip 约定）；判读已进 competition-status.md 批次#69。以下为原始要求，留档：

1. 今天的工作区先落一个 commit，注明对应 v48 包；
2. 提交包按 run id 归档：`.tmp/submission-pack/v4x.zip` 复制为 `v4x_<runid>.zip`，桌面不再覆盖同名 zip（ed77 那版 v47 已丢过一次，别再丢）；
3. 判读进 `docs/competition-status.md`，不要只留在对话里。

## INBOX-005（open，夜间安排 2026-09-27 00:10）— 用户睡觉期间的分工

用户已授权：闸绿即发（正式提交不逐次确认）、ZCode 负责平台上传（登录态已就绪）。夜间分工：

- **ZCode（在做）**：①哨兵每 30 分钟（平台 API 直查 v48 = run `85f404a69443`）；②**GitHub 题本地彩排 r1 已点火**——`python main.py /Users/liuboyu/Developer/arcbench-tasks/hackathon--github --output-dir .tmp/github-rehearsal-r1-0927 --type web --mode auto`（百炼私 key，用户桌面 .et 文件里的 = .env 现役 OPENAI_API_KEY，已 ping 通；日志 `.tmp/github-rehearsal-r1-0927/run.log`）。目的=新域泛化验证（47 原子/27 截图），本地无官方 specs 故只跑管线闸不跑官方判分；③v48 出分自动判读（INBOX-001）。
- **Cursor（等用户回来后）**：v49 准备 = 两个已知残留（FastAPI 首页补链、8 分钟修补线程与终局导出竞态）+ v48 尸检新发现，累积全集出包，硬闸 A+B+C（--full）全绿后通知 ZCode 上传。
- **题面资产**：两任务题面已解包 `/Users/liuboyu/Developer/arcbench-tasks/`（仓库外，避合规）。sheet yaml=官方 9/24 重写后版本（202,240B 与 v41+ 实跑吻合）。
- **预算红线**：余额 ¥417.17，sheet 上限 ¥120（v48 结算后剩 1-2 发）。

## INBOX-004（open）— 预算纪律 + GitHub 题情报（ZCode 9/27 0 点官网实测）

**预算（用户拍板）**：队伍余额实测 **¥417.17**（¥500 券已花 ~¥83）；用户规定 **sheet 任务累计花费上限 ~¥120**，余量留给 GitHub 题。v48 结算后 sheet 剩 1-2 发空间——**v50 起每一发都必须是累积全集 + 硬闸 A+B+C 全绿，禁止单刀发**。

**GitHub 题（TASK-011，/competitions/hackathon/tasks/hackathon--github）**：6 域 24 组，原子需求约 47 条——①身份与访问（注册/登录/找回/登出/改密）②组织与治理（org/team/成员/授权）③仓库资产管理（搜索/创建/fork/clone/可见性）④代码与版本控制（文件浏览/提交历史/分支）⑤Issue 管理（列表/创建/评论/指派/标签/里程碑/关闭）⑥PR 评审与合并（保护分支/PR 创建/评审/diff/合并）。规模与 bookstack(34)/keep(32) 同量级，域是 LLM 最熟悉的 CRUD+工作流，生成质量天花板预期**高于 sheet**（sheet 的公式引擎/透视/校验算法上更难）。同一个 agent 快照两个任务共用。等 sheet 拿到非零分后启动本地彩排（题面下载入口在任务页 "Download all requirements"）。

**补充（00:35 用户口述）**：平台上传不用填 API Key——勾"使用比赛额度评测"复选框即可（平台建临时 key、扣队伍 ¥500 额度、此类 run 才进榜）。ZCode 上传 v49 时照此操作。

## [sentinel] INBOX-006（open，2026-09-27 00:05）— 彩排实弹复现"修复升级链空转"（735dc 同款病理）

GitHub 彩排 r1（本地）日志出现：`修复升级 → deepseek-v4-pro（fix_attempts=3/4/5，已排除 [flash, pro, qwen3.7-max]）`——**三腿全在排除名单里却仍连续三轮升回 pro**，正是 735dc 死循环病理，v43-3 的排除补丁疑似挡不住"台账无货回落"路径。run 仍在推进（未到杀线：watchdog 200 分钟 + 2M token 闸兜底），暂不干预，留作取证。**请 Cursor 复核 `_fix_code` 台账回落分支：排除名单满员时是否应直接冻结该文件修复而非循环升级**（RepoFixer 已有"连败冻结"语义，dev_loop 侧对齐）。日志：`.tmp/github-rehearsal-r1-0927/run.log`。

## [sentinel] INBOX-007（open，2026-09-27 01:25）— v48 尸检定案：入口择优选中迷你 app + 合成首页保活 = 0/100 真凶

**证据链（官方日志 + File 页签取证）**：
1. run 85f404a69443 终态 FAILED 0/100、feature 0/24、1.04M token、Stage3 正常跑完（14 分钟）；
2. 评测期应用日志只有 `GET / 200 + favicon 404` 成对出现 ≈ 每条测试一次加载、零交互；
3. `template-app.stdout`：`npm start → python3 main.py`（端口 3000 正确）后紧跟 **`/ 缺失，已由启动入口补挂（评测首页保活）`+`首页缺少题面入口文案，已补可见链接`+`Serving Flask app 'worksheet_crud.worksheet_crud'`**——启动器选中了 worksheet_crud 模块级迷你 app（非组装真 webapp），无 `/` 路由 → 合成保活首页 + 注入 arcbench_entry.json 的种子串链接（Q3 Sales/East/North，entry_surface 从题面抽的是种子值不是导航控件）；
4. 导出探针只断言 health+home 200 → 合成页 PASS（假绿）；真 webapp（首页有 Q3 Sales 链接+完整导航+各功能页）从未服务。ed77 的 0/100 同因。
5. 对照组：GitHub 本地彩排入口=author 无此病 → **任务相关**：sheet 模块布局让 worksheet_crud 在择优池里赢了。

**v49 修复方向（外科级，三刀）**：
- 刀1 `platform_export.py` 入口择优：**有真实 `/` 路由的候选优先于无 `/` 者**（当前按路由数最多择优，worksheet_crud 路由多但无首页）；平局再比路由数；
- 刀2 **合成保活首页降级为最后手段**：仅当所有候选都无 `/` 时才允许补挂，且合成页必须渲染全部已知路由的真实链接清单（非题面种子串）；`arcbench_entry.json` 的锚点提取改为抽 WHEN 步骤的控件动词短语/页面名，种子值只作文本不作链接；
- 刀3 导出探针加**内容断言**：home 200 且 HTML 含 ≥1 个指向本站路由的 `<a href>`（合成占位/空壳判红）——把这次假绿堵死。
**验证**：本地用 sheet 真题面重跑生成（或直接对 v48 交付树起服）确认首页=真 webapp 页；pytest 全绿 + 闸 A+B 后出 v49。INBOX-001 判读完成，本条为 v49 施工图。
