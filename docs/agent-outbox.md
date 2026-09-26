# Agent Outbox（Cursor → ZCode/用户 回执区）

> Cursor 对 `docs/agent-inbox.md` 条目的执行回执。每完成一条，追加一行并 commit。
> ZCode 哨兵巡检时会读这里核对 INBOX 条目状态。

| 日期时间 | 对应条目 | 回执摘要（做了什么/结果/遗留） |
|---|---|---|
| （示例）09-26 23:50 | INBOX-003 | 已 commit `abc1234`，19 文件落库；v48.zip 已复制为 v48_85f404a69443.zip |
