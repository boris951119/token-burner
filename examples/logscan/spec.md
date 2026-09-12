# logscan 最终技术规范 (spec.md)

## 一、 项目目标
开发一款基于 Python 标准库的命令行日志轮转分析工具 `logscan`。核心目标是解决多节点、大体积、格式混杂的日志文件统计与异常溯源痛点。工具需满足：
1. **零依赖交付**：仅使用 Python 3.9+ 标准库，无需外部包管理。
2. **流式处理**：采用惰性生成器流水线，支持 GB 级日志内存恒定扫描。
3. **鲁棒解析**：兼容常见日志格式（RFC3164/5424、JSON Lines、自定义时间戳格式），内置编码降级与异常行隔离机制。
4. **安全遍历**：自动防软硬链接死循环、深度限制、透明支持 `.gz/.bz2` 压缩轮转文件。
5. **标准化输出**：聚合各文件 ERROR/WARN/INFO 行数，提取全局按时间排序的 ERROR 时间线，渲染为结构化 Markdown 报告。
6. **完整质量保障**：提供覆盖核心逻辑分支 ≥90% 的单元测试套件，具备可重复执行的 CI 友好性。

## 二、 用户故事
1. **作为运维工程师**，我希望通过 `logscan -d /app/logs/ -o report.md` 一键扫描整个日志目录，获得一份包含健康度统计与关键错误时间轴的 Markdown 报告，用于快速定位故障根因。
2. **作为后端开发者**，我希望工具能自动容错处理乱码文件、损坏的 JSON 日志或非标准时间戳行，避免进程崩溃，确保扫描任务持续完成。
3. **作为合规审计员**，我需要统计结果具备确定性（相同的输入产生相同的排序与计数），且工具不修改源文件、不保留敏感会话令牌，符合生产环境安全规范。
4. **作为维护者**，我希望代码结构清晰、接口契约明确、测试覆盖率量化达标，便于后续接入监控平台或扩展新的报表格式（如 CSV）。

## 三、 架构设计
采用 **“输入-过滤-解析-分析-渲染” 单向流水线架构**，全链路基于生成器 (`yield`) 实现惰性求值，数据单向流动，无状态中转。

| 层级 | 职责 | 核心机制 |
| :--- | :--- | :--- |
| **CLI 层** | 参数校验、权限预判、生命周期管理 | `argparse` 解析；默认单线程生成器模式，可选 `--workers` 开启 I/O 密集型文件扫描并发 |
| **遍历层** | 安全路径发现与文件流暴露 | `pathlib` 递归；深度阈值控制；`st_dev + st_ino` 集合去重防环；后缀白名单匹配；`gzip/zlib` 透明解压 |
| **解析层** | 文本清洗与结构化切分 | 预编译正则优先级链；UTF-8 → GBK/Latin-1 → `replace` 降级策略；失败行记录至 `logging` 并跳过；返回标准化字典 |
| **分析层** | 聚合统计与全局时序构建 | 线程安全累加器；`(timestamp -> 全局单调序列号 -> 文件哈希)` 确定性排序；缺失时间戳降级为物理顺序追加 |
| **渲染层** | 抽象模板注入与格式化输出 | `BaseRenderer` 协议接口；默认 Markdown 模板引擎；预留 CSV/JSON 适配器槽位 |

**技术栈约束**：严格限定于 `sys`, `os`, `pathlib`, `argparse`, `re`, `datetime`, `zoneinfo`, `collections`, `hashlib`, `logging`, `concurrent.futures` (仅IO), `io`, `unittest`, `tempfile`, `gzip`。

## 四、 接口定义

### 4.1 CLI 入口契约
```bash
python -m logscan [OPTIONS]
  -d, --target-dir TEXT       指定扫描根目录（必填）
  -o, --report TEXT           输出 Markdown 报告路径（可选，默认 stdout）
  -s, --suffixes SEQUENCE     日志后缀列表，逗号分隔（默认 .log,.log.[0-9]*,.log.gz,.log.bz2）
  -D, --max-depth INTEGER     最大递归深度（默认 10）
  -j, --workers INTEGER       并发工作线程数，仅用于文件I/O分发（默认 1）
  -v, --verbose               开启 DEBUG 级别诊断日志输出至 stderr
```

### 4.2 内部模块签名
```python
# src/logscan/traverser.py
def find_log_files(root: Path, suffixes: Sequence[str], max_depth: int = 10) -> Iterator[Path]:
    """惰性生成器：产出合法日志文件路径，自动跳过硬/软环路与非目标后缀"""

# src/logscan/parser.py
def parse_lines(path: Path, encoding_fallback: bool = True) -> Iterator[Dict]:
    """逐行迭代：尝试 UTF-8，失败则回退；命中正则则 emit LogEntry，未命中 emit ParseFailure"""

# src/logscan/analyzer.py
def aggregate_analysis(line_gen: Iterator[Dict]) -> Tuple[Dict[str, FileStats], List[Dict]]:
    """消费解析流：返回 {file_path: FileStats} 映射与排好序的 [ErrorTimelineEntry] 列表"""

# src/logscan/renderer.py
def render_markdown(stats_map: Dict, timeline: List, target_dir: Path, gen_time: datetime) -> str:
    """将结构化数据注入 Markdown 模板，返回完整报告字符串"""
```

## 五、 数据模型

### 5.1 核心数据结构
```python
from typing import Optional, Any
from datetime import datetime
from pathlib import Path

class LogEntry:
    ts: Optional[datetime]      # 解析到的时间戳，ISO8601 归一化；缺失则为 None
    level: str                  # 枚举: 'ERROR', 'WARN', 'INFO', 'UNKNOWN'
    msg: str                    # 清理后的消息正文（去除前后空白）
    src_file: Path              # 原始日志文件路径
    seq_idx: int                # 全局单调递增序列号，用于消除并发/跨文件的时序歧义

class FileStats:
    path: Path
    total_lines: int
    info_count: int
    warn_count: int
    error_count: int

class ReportPayload:
    generated_at: datetime
    target_dir: Path
    files_scanned: int
    total_lines_processed: int
    file_statistics: list[dict]   # 扁平化列表供 Markdown 表格渲染
    error_timeline: list[dict]    # 按 ts 升序排序的关键事件
    warnings_count: int           # 跳过/解码失败的行总数
```

### 5.2 序列化策略
- 运行期全程保持原生对象引用。
- 渲染前统一转换为 `list[dict]` 与标量类型，剔除不可序列化字段（如 `Path` 转为 `str`）。
- Markdown 输出采用 ASCII 兼容字符集，表格列宽自适应对齐。

## 六、 任务拆分

| 阶段 | 任务编号 | 任务描述 | 交付物 | 关联模块 |
|:---:|:---:|:---|:---|:---|
| **P1** | T1 | 工程脚手架与 CLI 基础对接 | `__main__.py`, `pyproject.toml`, 参数解析验证 | CLI 层 |
| **P2** | T2 | 安全遍历器实现 | 深度控制、Inode 去重、后缀匹配、GZIP/BZ2 透明读入口 | traverser |
| **P3** | T3 | 多格式正则解析引擎 | 优先级链、编码降级、`LogEntry` 构造、失败行隔离日志 | parser |
| **P4** | T4 | 流式分析与时序构建 | 分组计数器、确定性排序算法、无时间戳降级策略 | analyzer |
| **P5** | T5 | Markdown 渲染器实现 | 模板加载、占位符替换、表格/时间轴排版逻辑 | renderer |
| **P6** | T6 | 单元测试套件开发 | 虚拟文件系统(`tempfile`)、Mock I/O、边界用例(空目录/软环/乱码/超大文件模拟)、`coverage` 配置 | tests/ |
| **P7** | T7 | 端到端集成与文档 | 自动化脚本封装、README 使用说明、CI 流程适配清单 | docs/ |

## 七、 验收标准

### 7.1 功能验收
- [ ] 正确识别并扫描目标目录下所有匹配后缀的日志文件（含嵌套子目录）。
- [ ] ERROR/WARN/INFO 行数统计与实际手动核对误差为 0。
- [ ] 提取的 ERROR 时间线按时间戳严格升序排列；时间戳缺失的行按物理读取顺序自然衔接。
- [ ] 生成的 Markdown 报告格式合法，包含摘要统计表、错误时间轴、扫描元数据。

### 7.2 性能与资源验收
- [ ] 连续处理单条 ≥1GB 日志文件时，常驻内存峰值不超过 128MB（生成器流式保障）。
- [ ] 启用 `--workers=4` 时，纯 I/O 密集目录扫描耗时较单线程下降 ≥60%。
- [ ] 软链接自环、极深目录（>50层）、符号链接交叉引用场景下，遍历不陷入死循环或抛出 `RecursionError`。

### 7.3 鲁棒性与安全性验收
- [ ] 遇到二进制文件、损坏归档、非法 UTF-8 字节序列时，触发降级策略而非 `UnicodeDecodeError`/`EOFError` 终止程序。
- [ ] 缺失读权限的目录/文件被静默跳过，并在 `stderr` 输出结构化警告，退出码始终为 0（除非致命参数错误）。
- [ ] 不缓存、不持久化任何用户输入数据或日志内容到磁盘/网络。

### 7.4 代码质量与测试验收
- [ ] 代码库完全脱离第三方依赖，Python 版本锁定 `>=3.9`。
- [ ] 核心模块 (`parser.py`, `analyzer.py`) 分支覆盖率经 `coverage.py` 检测 ≥90%。
- [ ] 提供以下专项测试用例集并通过全部断言：
  1. 空目录与零字节文件
  2. 混合时间格式与缺失时间戳行
  3. GBK/Shift_JIS 混编乱码流
  4. 含大量非结构化文本的脏数据文件
  5. `subprocess.run()` 模拟完整 CLI 生命周期，断言输出文件存在且头部结构正确。
- [ ] 遵循 PEP 8 规范，公开接口附带 Type Hints 与 Docstring。