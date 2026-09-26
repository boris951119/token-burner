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

## INBOX-002（open）— presubmit 闸验收点（ZCode 独立审计结论）

Cursor 落地 A+B（静态检查+假网关启动冒烟）时对照：

1. A 段做 config.json 官方档位断言时，把 `test_shipped_config_is_the_trial_formation` 的断言方向**一起改对**——它现在断言"包内=试跑档"，方向装反，会和闸打架（v43 曾带试跑档上正式赛，帽 1.6M 砍掉 2/3 口粮）；
2. B 段断言口径：假网关下 main.py 的正确行为是"设计内干净快速失败"——断言 = stderr 无 `Traceback` + 墙钟内退出 + exit code 有值，**不是**"必须跑到交付"；
3. 建成后拿坏样本做**反例验收**：构造试跑档 config、函数内 import 遮蔽各一份，闸必须红（57e3 threading 雷的教训：修复工具自己也会有 bug）；
4. **C 段不要砍**（flash + 3 条原子需求微题面端到端，断言 run_completed + 起服 GET / 200 + 墙钟内退出）：A+B 对两类最贵死法覆盖为零——532193 类"探针绿后挂死"（静态扫不出、假网关走不到那段路径）和 ed77 类"活着但交出 0 分姿势"。C 才几毛钱，**每次真正提交平台前必须 `--full` 跑一次**。

## INBOX-003（open）— 落盘纪律（现状：19 文件 +1319 行未提交，判读只活在 transcript 里）

1. 今天的工作区先落一个 commit，注明对应 v48 包；
2. 提交包按 run id 归档：`.tmp/submission-pack/v4x.zip` 复制为 `v4x_<runid>.zip`，桌面不再覆盖同名 zip（ed77 那版 v47 已丢过一次，别再丢）；
3. 判读进 `docs/competition-status.md`，不要只留在对话里。
