# 交接（9/24 凌晨 ~01:20）

## 一句话状态
批次#54 已落包并出 **v38.zip**（容器七读复验过、全量 1785 passed/2 skipped、commit `0e72665`）；
bookstack 第二域 L1 测量收完（3/34→5/34→**22/34**）；**冷启动卡在凭证，不是卡在代码**。

## 阻塞项（只有用户能解）
`.env` 里唯一的一条 token（三槽位同值，len=116 / sha8=70db6ebf，值从不回显）三条通道实测：

| 通道 | 回包 | 判定 |
|---|---|---|
| `api.arc-bench.com/v1` | `unauthorized` ×3 模型 | 不是平台 key |
| `dashscope.aliyuncs.com/compatible-mode/v1` | `Incorrect API key provided` | 不是百炼普通 API Key |
| `coding.dashscope.aliyuncs.com/v1` | `invalid access token or token expired` | **格式对、令牌过期/未激活** |

全仓扫过 `*.env`/`.shape.env`/`*.key`（只比哈希）⇒ 本地没有第二条 key，旧平台 key 不可恢复。
**取新 key 的路**：`https://meter.arc-bench.com/user`（用 API key 进入）。
换 key 后**先跑** `./.venv/bin/python scripts/quota_probe.py`（必须走 `.venv`，系统 python3 无 dotenv），
再看新账户水位决定这轮烧多少——独立账户，别按旧 key 的量假设。

## 发车就绪（key 一通就照这条跑，无需再确认）
```
cd ~/Developer/token-burner && export PATH=/opt/homebrew/bin:$PATH
./.venv/bin/python scripts/quota_probe.py
./.venv/bin/python scripts/local_loop.py \
  --requirement .tmp/arcbench-official/arc-bench/webapp/bookstack/requirements \
  --task bookstack --output-dir .tmp/coldstart-v38-bookstack
```
（keep 域换 `webapp/keep/requirements --task keep`；信封现为 `max_task_tokens=2000000`，
前两次彩排死在 880k 修环预算上，这次给足。）

**归因边界**：`config.json` 的 `models` 是平台三模型腿。若改用百炼腿跑，那读数是"生成器能不能跑通"，
**不能单独充当"传 v37 还是 v38"的证据**——#52~#55 全是提示词侧改动，只有平台模型上的新生成才算证明。

## 上传位（守住"每次上传只改一件事"）
- **v37.zip** ＝ #52/#52b/#52c（五条 L1 语义契约，注入侧）
- **v38.zip** ＝ v37 + #54 射程收口，与 v37 差异**只有一个文件** `app/prompts/write_code_system.md`
- **v39 待做** ＝ #55 三条（导航按钮口径 / 可编辑组行内保存 / Close 即落库）
- **#65 待拍板** ＝ 批次#56 量出的契约（八）：本域 12 红里 11 题、对照集 11/40 常态 ⇒ 唯一按
  「暴露面无条件」立即收口的一条，但它和 #55 抢同一个上传位，先等冷启动读数。

## 环境坑（本窗口踩过）
- cwd 每条命令后重置回 `/Volumes/新加卷/token-burner` ⇒ 每条都 `cd ~/Developer/token-burner`
- `export PATH=/opt/homebrew/bin:$PATH` 否则 docker/node 测试自我跳过、套数会骗人
- zsh 无 `timeout`；BSD grep 的 `\x{...}` 静默失败（用 `rg`）
- 判分跑着的时候不许起 pytest / 第二个服务（500ms 可见性探测会被饿成假红）
