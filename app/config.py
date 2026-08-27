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


@dataclass
class Settings:
    """系统全部可调参数的唯一收敛点。"""

    # ---- 模型（3.3 节）----
    models: list[str] = field(default_factory=lambda: list(DEFAULT_MODELS))

    # ---- 第 11 章 六层成本护栏（11.6 默认值）----
    max_task_tokens: int = 200_000            # 第 0 层：单任务 token 总预算（总闸）
    auto_mode_budget_multiplier: float = 2.5   # 11.0/3.6.3：自动模式预算倍数（×2~3）
    max_discussion_rounds: int = 3             # 第 1 层：讨论轮数上限
    max_response_tokens: int = 8_000           # 第 2 层：单轮对话输出上限
    similarity_threshold: float = 0.85         # 第 3 层：embedding 语义相似度阈值
    jaccard_threshold: float = 0.9             # 第 3 层：文本相似度首道拦截阈值
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

    # ---- 15.5 节 JSON 解析容错 ----
    max_parse_retries: int = 3                 # 单次调用最大重试次数
    strict_json_response: bool = True          # 请求携带 response_format=json_object
    programmatic_json_repair: bool = True      # 第 3 级程序容错修复（零 token）
    llm_json_repair: bool = False              # 15.2 LLM 辅助修复（默认关闭）

    # ---- 4.4 Researcher（Beta v0.5，仅预留配置）----
    research_budget_tokens: int = 20_000

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
        )
        for name in positive_ints:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} 必须为正整数，当前值: {value!r}")

        for name in ("similarity_threshold", "jaccard_threshold"):
            value = getattr(self, name)
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} 必须落在 (0, 1] 区间，当前值: {value!r}")

        if not 2.0 <= self.auto_mode_budget_multiplier <= 3.0:
            raise ValueError(
                "自动模式预算倍数必须落在 ×2~3（3.6.3 节），"
                f"当前值: {self.auto_mode_budget_multiplier!r}"
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
