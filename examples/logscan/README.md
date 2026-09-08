# 示例项目:logscan 日志轮转分析工具(真实生成全过程留痕)

> 本目录是 token-burner **真实运行**的完整交付物,未做任何人工修改——
> 输入是一句需求,输出是可运行的日志分析 CLI 工具与全过程生产留痕。
> 5/5 模块全部一次通过测试验收(2026-09-06,deepseek-v4-pro)。

## 需求原文(唯一的人工输入)

> 开发一个日志轮转分析命令行工具 logscan:扫描指定目录下全部 log 文件,
> 解析并统计各级别(DEBUG/INFO/WARNING/ERROR)日志数量,支持按时间范围
> 过滤与关键词搜索,输出 JSON 汇总报告……

完整需求见 `spec.md`(由 PM 模型自动细化为规格)。

## 生产轨迹导读(评审重点)

| 文件/目录 | 记录什么 | 看什么 |
|---|---|---|
| `spec.md` | PM 模型细化的最终规格 | 需求如何被结构化 |
| `interfaces.json` | 模块接口契约(5 个模块的函数级签名) | 模块间如何"对图纸"开发 |
| `modules/*.md` | 每个模块的设计文档 | 拆分与职责 |
| `code/` | **可运行的源代码**(5 模块 + `_shared/` 公共层) | `python -m logscan.cli --help` 可直接运行 |
| `tests/` | 模型生成的测试 | 验收标准 |
| `changelog/*/validation.md` | **每模块验收终态**(5 个全 SUCCESS) | 门禁与测试结果 |
| `changelog/*/fix_history.md` | 修复轮历史(失败报告全文) | 失败如何被自动修复 |
| `logs/session_001.log` | **逐动作生产日志**(带时间戳):每次写文件/修复/提交 | 完整生产过程回放 |
| `logs/cost_report.json` | **逐 LLM 调用审计**:模型、token、耗时 | 成本逐笔可查 |
| `sessions/` | 任务状态快照 | 断点续跑能力 |

## 交付物可运行验证

```bash
cd code
python -m logscan.cli --help
```

依赖:仅 Python 标准库(该需求由模型自动规划为标准库实现)。

## 数据口径

- 模型:PM=qwen3.6-flash / dev=deepseek-v4-pro / test=qwen3-coder-plus
  (阿里云百炼,OpenAI 兼容端点)
- 本项目 5/5 模块全部通过测试验收;同批 10 需求整体通过率 71%(37/52 模块),
  任务级交付 10/10,零预算超支——完整数据见 `logs/bench_v1/full_r3/`。
