# bench_v1 · M17-1 全量基准报告（2026-09-06）

> 依据：`v1.0-workplan.md` V3 批次「10 任务全量基准（auto），模块通过率 ≥60% 门槛」。
> 任务集：`scripts/bench_tasks.json` T1–T10（CLI 工具×2 / 数据处理×2 / 文件操作×2 /
> 第三方库调用×2 / 陌生技术栈×2），auto 模式，单任务预算闸门 500k，修复上限 5 轮。
> 模型（付费档，OpenAI 兼容网关，与服务端 `config.json` 同源）：
> PM=`openai/qwen3.6-flash` / dev=`openai/qwen3-coder-plus` / test=`openai/deepseek-v4-flash`。
> 跑批：`python scripts/bench_v1_run.py --ids T1,...,T10 --out logs/bench_v1/full`
> （2026-09-05 22:19 – 09-06 03:14，约 5 小时，服务进程 20:38 启动与 paid_pilot3 同源）。
> Docker 未装 → 进程执行器（文档化降级）。

## 一、结论

**未达 60% 发布门槛：模块通过率 26/55 = 47.3%（也未过 50% 准入线）。**
任务级韧性 100%（10/10 succeeded，零限流/网关中断）；超预算 1/10（T3 508k/500k，
超支率 10%，未满足 <10%）；总消耗 3,337,832 tokens。

对照（同代码栈、同任务集口径）：

| 批次 | 模型档位 | 模块通过率 | 任务级 |
| --- | --- | --- | --- |
| pilot r2–r5（V2.1–V2.8 修复期） | GLM 免费档 | 2/18 = 11% | 3/3 |
| paid_pilot3（V2.9/M15-7 后首测） | 付费档（同上三模型） | 10/16 = 62% | 3/3 |
| **本次 full（V2.9 口径全量）** | 付费档（同上） | **26/55 = 47.3%** | **10/10** |

判读：T1–T3 复跑 8/16 = 50%，低于 paid_pilot3 同任务 62%——**批次间方差显著**
（LLM 收敛残差的随机性 + 任务集难度分布：全量含 T4/T7 等高冻结任务）。
62% 是 3 任务小样本的有利抽样，47.3% 是 10 任务全量的更可靠估计。

## 二、逐任务结果

| 任务 | 类别 | 模块 | tokens | 超预算 | 冻结模块 |
| --- | --- | --- | --- | --- | --- |
| T1 passmint | CLI 工具 | 3/5 | 275,657 | | cli_router, evaluator_core |
| T2 salestat | 数据处理 | 3/5 | 278,190 | | analysis_engine, csv_stream |
| T3 stockpile | 陌生技术栈 | 2/6 | 508,585 | **ob** | stockpile_config/db/service/tests |
| T4 logscan | 文件操作 | 1/5 | 356,083 | | cli, models, reporter, scanner |
| T5 md2html | 文件操作 | 3/6 | 318,752 | | file_io_manager, md_lexer, test_suite |
| T6 profile_schemas | 第三方库 | 2/4 | 245,209 | | error_mapper, file_loader |
| T7 sysview | 第三方库 | 1/5 | 297,548 | | collector, entry, core_eval, ui_render |
| T8 logroll | 数据处理 | 3/6 | 304,749 | | cli_entry, log_loader, time_aggregator |
| T9 memcard | CLI 工具 | 4/6 | 335,844 | | cli_interface, ui_formatter |
| T10 dag_sim | 陌生技术栈 | 4/7 | 417,215 | | critical_path_analyzer, cycle_detector, simulator_engine |

## 三、冻结原因分类（29 模块，回炉点判定依据）

| 类别 | 数量 | 占比 | 回炉方向 |
| --- | --- | --- | --- |
| 执行失败·测试断言不收敛（exit 1） | 16 | 55% | 语义型 → 提示词迭代 |
| 接口门禁·契约未声明导出（[extra]） | 7 | 24% | 契约对齐型 → 写码轮「实现即导出」提示词（M15-8 候选） |
| 执行失败·测试收集错误（exit 2） | 4 | 14% | 语义型 → 修复轮对收集错误的定向修复指导 |
| 静态门禁·未声明跨模块依赖 | 1 | 3% | 契约对齐型（同上） |
| 静态门禁·语法错误 | 1 | 3% | 基座模型质量残差 |

**回炉点结论：语义型 20（69%）+ 契约对齐型 8（28%）**，与 v1.0-workplan 预案
「语义型→提示词迭代」一致；接口门禁 7 例全部是「代码实现了契约未声明的导出」
（处置提示已给但 5 轮内未执行）——M15-7 的契约同源思路需从命名对齐扩展到
**导出清单对齐**。机制层（执行/门禁/预算/审计）本轮零新缺陷。

## 四、判定与后续

1. **M17-1 验收：不通过**（47.3% < 60%）；按预案进入回炉（最多 2 轮），
   回炉点=提示词迭代（修复轮断言收敛 + 契约导出对齐）。
2. **v1.0.0 标签暂缓**——Done 定义要求全量 ≥60% 后打标触发 Actions。
3. 超支率 10%（1/10）贴线：T3 冻结 4 模块触发深修复链所致，回炉若降低
   冻结率，超支率同步下降。
4. 数据可复现：本目录 `*_task.json`（原始终态）/`*_bench.json`（基准数据）/
   `bench_report.json`（汇总）；各任务完整现场在 `projects/` 对应目录。
