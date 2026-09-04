"""集中配置管理（规格文档第 17 章第一阶段任务）。

职责：
1. 从 .env 读取模型 API 密钥（第 5 章安全性：密钥不硬编码、仅走环境变量）；
2. 集中管理全部可调参数，避免多处独立数值造成矛盾：
   - 第 11 章六层成本护栏（11.6 护栏总表默认值）；
   - 3.2 节任务路由阈值（simple_threshold 与模块化阈值同一难度尺度，见「阈值统一」）；
   - 3.6 节执行模式默认值；15.5 节 JSON 解析容错参数；4.4 Researcher 预算（Beta 预留）。
3. 支持用户通过 config.json 添加模型、覆盖默认值（3.3 节「用户可通过配置文件添加更多」）。

优先级：config.json 覆盖 > 代码默认值；API 密钥仅来自环境变量，不参与文件覆盖。

config.json 示例::

    {
      "models": ["gpt-4o", "claude-3-5-sonnet", "deepseek-chat", "qwen-max"],
      "max_task_tokens": 300000
    }
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_origin, get_type_hints

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 常量（3.3 节：预设模型列表）
# ---------------------------------------------------------------------------

DEFAULT_MODELS: tuple[str, ...] = (
    "gpt-4o",
    "claude-3-5-sonnet",
    "deepseek-chat",
    "gemini-1.5-pro",
)

# 模型名称前缀 -> 环境变量名（litellm 供应商惯例命名）
MODEL_ENV_KEYS: tuple[tuple[str, str], ...] = (
    ("gpt-", "OPENAI_API_KEY"),
    ("claude-", "ANTHROPIC_API_KEY"),
    ("deepseek-", "DEEPSEEK_API_KEY"),
    ("gemini-", "GEMINI_API_KEY"),
)

VALID_EXECUTION_MODES: tuple[str, ...] = ("safe", "auto")

# M14-3/M14-4：交付目标平台（提示词约束 + 危险扫描平台黑名单同源）
VALID_TARGET_PLATFORMS: tuple[str, ...] = ("windows", "linux", "macos", "any")

# M15-3：契约风格三态（门禁风格约束与 auto 回写共用）
VALID_CONTRACT_STYLES: tuple[str, ...] = ("function", "class", "auto")


@dataclass
class Settings:
    """系统全部可调参数的唯一收敛点。"""

    # ---- 模型（3.3 节）----
    models: list[str] = field(default_factory=lambda: list(DEFAULT_MODELS))

    # ---- 第 11 章 六层成本护栏（11.6 默认值）----
    max_task_tokens: int = 200_000            # 第 0 层：单任务 token 总预算（总闸）
    budget_throttle_threshold: float = 0.9     # 11.0：≥90% 进入省 token 模式
    auto_mode_budget_multiplier: float = 2.5   # 11.0/3.6.3：自动模式预算倍数（×2~3）
    max_discussion_rounds: int = 3             # 第 1 层：讨论轮数上限
    max_response_tokens: int = 8_000           # 第 2 层：单轮对话输出上限
    # 11.2：截断（finish_reason=length）分块续写次数上限；耗尽仍截断则标记 truncated
    max_output_continuations: int = 2
    similarity_threshold: float = 0.85         # 第 3 层：embedding 语义相似度阈值
    jaccard_threshold: float = 0.9             # 第 3 层：文本相似度首道拦截阈值
    # 11.3/9 章：embedding 第二道检测（经 model_client 封装；关闭则仅 Jaccard 首道）
    enable_embedding_check: bool = True
    embedding_model: str = "text-embedding-3-small"
    loop_repeat_limit: int = 3                 # 第 3 层：同一论点重复次数上限 N
    max_fix_rounds: int = 5                    # 第 4 层：修复循环上限
    max_spec_confirm_rounds: int = 3           # 第 5 层：spec 确认收敛上限

    # ---- 3.2 节 任务路由阈值（阈值统一：与难度分同一尺度）----
    simple_threshold: int = 3                  # 简单编程节流：难度 ≤3 主 LLM 直出
    modular_difficulty_threshold: int = 5      # 模块化启用：难度 ≥5（12.2 节）
    modular_file_count_threshold: int = 6      # 模块化启用：预估文件数 ≥6（12.2 节）

    # ---- 3.6 节 双模执行 ----
    default_execution_mode: str = "safe"       # MVP 默认安全审阅模式
    sandbox_timeout_seconds: int = 30          # 3.6.3：沙箱 30s 超时熔断（Alpha v0.4）

    # ---- M14-3/M14-4 交付目标平台（v1.0：平台可移植性）----
    # windows=本机交付环境（v0.5 实测教训：生成代码含 Unix-only fcntl 直接 ImportError）
    target_platform: str = "windows"           # windows | linux | macos | any

    # ---- M15-3 契约风格（v1.0：门禁风格约束可配置）----
    # function=顶层可调用导出（M15-1 缺省，与 v0.5 后行为一致）；
    # class=顶层公开类；auto=首轮实现后按实际代码顶层符号一次性回写契约
    # （确定性反推 + 审计落盘 sessions/style_adaptation.jsonl）
    contract_style: str = "function"           # function | class | auto

    # ---- M14-7 safe 模式 LLM 逻辑审查（规格 3.6.2 三件套补全）----
    # 契约函数级审查（test_model）：verdict=fail → 进修复循环；
    # LLM 调用/解析失败 → 降级放行（增强非硬门禁）。auto 模式不审查
    # （有真实执行反馈，避免冗余调用）。缺省开 = safe 模式名实相符。
    logic_review_enabled: bool = True

    # ---- 产出目录（CLI / 服务端 / 桌面端三端统一）----
    # 空 = 缺省「启动命令时所在目录 / projects」；配置绝对路径后
    # 全部产出（projects/、断点快照、成本报告）落到指定目录
    projects_root: str = ""

    # ---- M2 Docker 沙箱（auto 模式可选容器级隔离）----
    # 缺省 False：auto 模式沿用进程级 LocalExecutor（行为与 v0.3.1 一致）
    docker_executor_enabled: bool = False
    docker_image: str = "python:3.11-slim"     # 单 Python 基础镜像（多语言属 M2-5）
    docker_network_enabled: bool = False       # 缺省无网络（M2-3 安全策略）

    # ---- M2-4 资源配额（容器 CPU/内存/磁盘/进程数）----
    # 超限由内核直接终止（OOM kill / pids 限制），exit 137 → FAILED 语义；
    # 配额缺省开启（安全姿态宁严勿松），工厂构造容器执行器时透传
    docker_mem_limit: str = "512m"             # --memory（--memory-swap 同值禁 swap）
    docker_cpus: float = 1.0                   # --cpus
    docker_pids_limit: int = 128               # --pids-limit（防 fork 炸弹）
    docker_tmpfs_size: str = "64m"             # /tmp 可写上限（唯一可写目录=磁盘配额）
    docker_node_image: str = "node:20-slim"    # M2-5：Node.js 镜像（TS 支持预热）

    # ---- M3 智能模型路由（三档分层，缺省关闭）----
    # 路由规则（v0.4.md M3-1）：难度 1-3 全轻量、4-6 主力+轻量混合、7-10 全旗舰；
    # 档位为空时向上回退（轻量→主力→旗舰）。开启时三档必须都是
    # models 的子集（确定性校验，尽早失败）。
    model_routing_enabled: bool = False
    model_tier_flagship: list[str] = field(
        default_factory=lambda: ["gpt-4o", "gemini-1.5-pro"]
    )
    model_tier_main: list[str] = field(
        default_factory=lambda: ["claude-3-5-sonnet", "deepseek-chat"]
    )
    model_tier_light: list[str] = field(default_factory=list)
    # M12-6：分档阈值可配置（原 orchestrator 硬编码 7/4，行为默认不变）
    route_flagship_threshold: int = 7   # 难度 ≥ 此值 → 全旗舰
    route_main_threshold: int = 4       # 难度 ≥ 此值 → 主力+轻量混合（< → 全轻量）
    # M12-9：模型单价表（$/Mtok，input/output 双价，近似值仅供参考，
    # 用户可按实际供应商计费在 config.json 覆盖；未登记的模型不计入成本对比）
    model_prices: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
        "deepseek-chat": {"input": 0.27, "output": 1.10},
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    })

    # ---- M4 上下文缓存（M4-1 Embedding 缓存，缺省关闭）----
    embedding_cache_enabled: bool = False
    embedding_cache_path: str = ".embedding_cache.db"
    embedding_cache_ttl_days: int = 7          # 按时间过期（默认 7 天）

    # ---- M4-2 论点库持久化（缺省关闭）----
    # 跨任务复用论点指纹与向量：新任务遇到历史论点零 embed 成本入库。
    # 语义决策（评审定版）：**冻结计数不跨任务累计**——预载论点在本任务
    # 首次复现视为首次入库（计数归零），冻结行为与不预载完全一致，
    # 规避「跨项目相似论点误冻结」风险；加速只体现在第二道 embedding
    # 比对（向量直接命中）。隐私注意：库文件含讨论论点文本（opt-in）。
    loop_library_enabled: bool = False
    loop_library_path: str = ".loop_arguments.json"
    loop_library_max_entries: int = 500        # 上限（保留最新）

    # ---- M8-5 全局 LLM 限流器（令牌桶按供应商，缺省关闭）----
    # 关闭时零行为变化；开启后超限排队而非报错，
    # 429 退避仍走 9 章重试（两层互补：排队控节奏，重试救失败）
    llm_rate_limit_enabled: bool = False
    llm_rate_limit_rps: float = 1.0            # 每供应商令牌回填速率（枚/秒）
    llm_rate_limit_burst: int = 3              # 桶容量（允许的瞬时并发）

    # ---- M9 双模式意图识别（System-1 快判 / System-2 全量评估）----
    # 缺省关闭：关闭时路由行为与 v0.3.1 完全一致（M9-2 回归保证）
    fast_triage_enabled: bool = False
    fast_triage_model: str = "deepseek-chat"   # 预设列表中的轻量档（与 M3-1 分层对齐）
    fast_triage_confidence_threshold: float = 0.8  # 低于阈值升级 System-2（宁升勿误）

    # ---- 9 章 LLM 调用韧性（超时与瞬态错误重试）----
    llm_timeout_seconds: int = 120             # 单次调用超时（litellm timeout 参数）
    llm_max_retries: int = 3                   # 瞬态错误（超时/429/连接/5xx）重试上限
    retry_backoff_base: float = 1.0            # 指数退避基数：sleep = base * 2**attempt（秒）

    # ---- 15.5 节 JSON 解析容错 ----
    max_parse_retries: int = 3                 # 单次调用最大重试次数
    strict_json_response: bool = True          # 请求携带 response_format=json_object
    programmatic_json_repair: bool = True      # 第 3 级程序容错修复（零 token）
    llm_json_repair: bool = False              # 15.2 LLM 辅助修复（默认关闭）

    # ---- M10 Researcher（规格第 4 章，v0.5 Beta；缺省关闭）----
    # 4.4：独立预算（独立于任务总预算之外，经 call_log 计入全局消耗日志）；
    # 4.6 降级版：用户粘贴资料 → 结构化摘要注入；联网调研独立开关后续灰度
    researcher_enabled: bool = False
    research_budget_tokens: int = 20_000
    research_cache_enabled: bool = True        # 三元组+资料哈希键，SQLite 单文件
    research_cache_path: str = ".research_cache.db"
    research_cache_ttl_days: int = 7
    # M10-5 联网调研（缺省关闭；失败自动回退资料注入模式）
    researcher_web_enabled: bool = False
    research_web_provider: str = ""            # duckduckgo（免 key）| tavily（需 TAVILY_API_KEY）
    research_web_max_results: int = 5          # 搜索结果拼接条数
    research_web_timeout: int = 15             # 请求超时（秒）

    # ---- 14 章 生成项目本地 git 版本管理 ----
    enable_git: bool = True                      # 阶段性本地提交（免推送）

    # ------------------------------------------------------------------
    # 校验（总则 D.1：确定性校验由程序承担）
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not self.models:
            raise ValueError("模型列表不能为空")
        if len(set(self.models)) != len(self.models):
            raise ValueError(f"模型列表存在重复项: {self.models}")

        positive_ints = (
            "max_task_tokens",
            "max_discussion_rounds",
            "max_response_tokens",
            "loop_repeat_limit",
            "max_fix_rounds",
            "max_spec_confirm_rounds",
            "max_parse_retries",
            "simple_threshold",
            "modular_difficulty_threshold",
            "modular_file_count_threshold",
            "sandbox_timeout_seconds",
            "research_budget_tokens",
            "llm_timeout_seconds",
            "llm_max_retries",
            "embedding_cache_ttl_days",
        )
        for name in positive_ints:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} 必须为正整数，当前值: {value!r}")

        for name in (
            "similarity_threshold",
            "jaccard_threshold",
            "budget_throttle_threshold",
            "fast_triage_confidence_threshold",
        ):
            value = getattr(self, name)
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} 必须落在 (0, 1] 区间，当前值: {value!r}")

        # M9：快判开启时模型必须在预设列表（调用前确定性校验，尽早失败）
        if self.fast_triage_enabled and self.fast_triage_model not in self.models:
            raise ValueError(
                f"fast_triage_model「{self.fast_triage_model}」不在预设模型列表中: "
                f"{self.models}"
            )

        # M3：路由开启时三档必须是预设列表的子集（档位指向未登记模型
        # 只会在运行时才暴露，提前失败）
        if self.model_routing_enabled:
            tiers = (
                set(self.model_tier_flagship)
                | set(self.model_tier_main)
                | set(self.model_tier_light)
            )
            unknown = tiers - set(self.models)
            if unknown:
                raise ValueError(
                    f"模型档位包含未登记模型: {sorted(unknown)}"
                    "（请同步 model_tier_* 与 models 列表）"
                )

        # M12-6：路由分档阈值校验（旗舰阈值必须大于主力阈值，且在难度域内）
        if not (0 <= self.route_main_threshold < self.route_flagship_threshold <= 10):
            raise ValueError(
                "路由阈值需满足 0 ≤ route_main_threshold < "
                "route_flagship_threshold ≤ 10，当前: "
                f"main={self.route_main_threshold}, "
                f"flagship={self.route_flagship_threshold}"
            )

        # M12-9：价格表结构校验（尽早失败：model → {input, output} 非负数值）
        for model, price in self.model_prices.items():
            if not isinstance(price, dict) or not {"input", "output"} <= set(price):
                raise ValueError(
                    f"model_prices[{model!r}] 须含 input/output 两个单价键"
                )
            for side in ("input", "output"):
                v = price[side]
                if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                    raise ValueError(
                        f"model_prices[{model!r}][{side!r}] 须为非负数值: {v!r}"
                    )

        # M10-5：联网调研供应商白名单（开启才要求配置，避免拼写错误静默回退）
        if self.researcher_web_enabled:
            if self.research_web_provider not in ("duckduckgo", "tavily"):
                raise ValueError(
                    "research_web_provider 须为 'duckduckgo' 或 'tavily'，"
                    f"当前值: {self.research_web_provider!r}"
                )
        if not (1 <= self.research_web_max_results <= 20):
            raise ValueError(
                "research_web_max_results 须在 1-20 之间，"
                f"当前值: {self.research_web_max_results!r}"
            )

        if self.retry_backoff_base < 0:
            raise ValueError(
                f"retry_backoff_base 必须非负，当前值: {self.retry_backoff_base!r}"
            )

        # M8-5：限流参数校验（开启才细查；关闭时维持缺省即可）
        if self.llm_rate_limit_enabled:
            if self.llm_rate_limit_rps <= 0:
                raise ValueError(
                    "llm_rate_limit_rps 必须为正数，当前值: "
                    f"{self.llm_rate_limit_rps!r}"
                )
            if self.llm_rate_limit_burst < 1:
                raise ValueError(
                    "llm_rate_limit_burst 必须 >= 1，当前值: "
                    f"{self.llm_rate_limit_burst!r}"
                )

        # M2-4：资源配额校验（尽早失败）
        import re as _re

        for name in ("docker_mem_limit", "docker_tmpfs_size"):
            value = getattr(self, name)
            if not _re.fullmatch(r"\d+(b|k|m|g)", str(value).lower()):
                raise ValueError(
                    f"{name} 须为 docker 大小格式（如 512m、1g），当前值: {value!r}"
                )
        if self.docker_cpus <= 0:
            raise ValueError(
                f"docker_cpus 必须为正数，当前值: {self.docker_cpus!r}"
            )
        if self.docker_pids_limit < 16:
            raise ValueError(
                f"docker_pids_limit 须 >= 16（pytest 自身需要数十进程余量），"
                f"当前值: {self.docker_pids_limit!r}"
            )

        if not 2.0 <= self.auto_mode_budget_multiplier <= 3.0:
            raise ValueError(
                "自动模式预算倍数必须落在 ×2~3（3.6.3 节），"
                f"当前值: {self.auto_mode_budget_multiplier!r}"
            )

        if self.target_platform not in VALID_TARGET_PLATFORMS:
            raise ValueError(
                f"target_platform 必须为 {VALID_TARGET_PLATFORMS} 之一，"
                f"当前值: {self.target_platform!r}"
            )

        # M15-3：契约风格三态（function 缺省 = M15-1 行为不变）
        if self.contract_style not in VALID_CONTRACT_STYLES:
            raise ValueError(
                f"contract_style 必须为 {VALID_CONTRACT_STYLES} 之一，"
                f"当前值: {self.contract_style!r}"
            )

        if self.default_execution_mode not in VALID_EXECUTION_MODES:
            raise ValueError(
                f"execution_mode 必须为 {VALID_EXECUTION_MODES} 之一，"
                f"当前值: {self.default_execution_mode!r}"
            )

        # 3.2「阈值统一」：节流阈值必须小于模块化阈值，
        # 否则出现「既不节流也不模块化」的自相矛盾配置
        if self.simple_threshold >= self.modular_difficulty_threshold:
            raise ValueError(
                f"simple_threshold({self.simple_threshold}) 必须小于 "
                f"modular_difficulty_threshold({self.modular_difficulty_threshold})，"
                "两者取自同一难度尺度（3.2 节阈值统一）"
            )

    # ------------------------------------------------------------------
    # 业务辅助
    # ------------------------------------------------------------------

    def task_token_budget(self, mode: str) -> int:
        """按执行模式返回任务总预算（11.0：自动模式 × 倍数）。"""
        if mode == "auto":
            return int(self.max_task_tokens * self.auto_mode_budget_multiplier)
        return self.max_task_tokens

    def get_api_key(self, model: str) -> str | None:
        """按模型名称前缀返回对应供应商的环境变量密钥；未配置返回 None。"""
        for prefix, env_name in MODEL_ENV_KEYS:
            if model.startswith(prefix):
                value = os.environ.get(env_name)
                return value if value else None
        return None


# ---------------------------------------------------------------------------
# 加载入口
# ---------------------------------------------------------------------------

# get_type_hints 解析字符串注解（因 from __future__ import annotations），
# 得到字段名 -> 真实类型的映射，供 config.json 类型核验使用
_SETTINGS_FIELDS: dict[str, Any] = get_type_hints(Settings)


def load_settings(
    env_file: str | Path | None = None,
    config_file: str | Path | None = None,
) -> Settings:
    """加载配置并构造 Settings。

    Args:
        env_file: .env 文件路径；缺省时自动发现（load_dotenv 默认行为）。
        config_file: 用户配置文件路径；缺省时尝试当前目录 config.json，
            文件不存在则直接使用代码默认值。

    Raises:
        ValueError: config.json 结构非法、含未知键或键值类型不符时
            （确定性校验，尽早失败，避免拼写错误静默失效）。
    """
    if env_file is not None:
        load_dotenv(env_file, override=False)
    else:
        load_dotenv(override=False)

    path = Path(config_file) if config_file is not None else Path("config.json")
    overrides = _read_config_overrides(path)
    return Settings(**overrides)


def _read_config_overrides(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件 JSON 解析失败（{path}）: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"配置文件必须是 JSON 对象（键值对），当前类型: {type(raw).__name__}")

    unknown = set(raw) - set(_SETTINGS_FIELDS)
    if unknown:
        raise ValueError(f"配置文件包含未知字段: {sorted(unknown)}（请检查拼写）")

    checked: dict[str, Any] = {}
    for name, value in raw.items():
        checked[name] = _check_type(name, value, _SETTINGS_FIELDS[name])
    return checked


def _check_type(name: str, value: Any, expected_type: Any) -> Any:
    """对 config.json 的键值做确定性类型核验（int 不接受 bool/str 等）。"""
    origin = get_origin(expected_type)
    if origin is list:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"{name} 必须为字符串列表，当前值: {value!r}")
        return value
    if expected_type is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{name} 必须为布尔值，当前值: {value!r}")
        return value
    if expected_type is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{name} 必须为整数，当前值: {value!r}")
        return value
    if expected_type is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} 必须为数值，当前值: {value!r}")
        return value
    if expected_type is str:
        if not isinstance(value, str):
            raise ValueError(f"{name} 必须为字符串，当前值: {value!r}")
        return value
    # 其余类型（未来扩展）直接透传，交给 Settings.__post_init__ 校验
    return value
