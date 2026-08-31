"""config.py 单元测试（TDD 先行）。

依据：规格文档 v0.3.1
- 3.3 节：预设模型列表，用户可通过配置文件添加更多；
- 3.2 节：阈值统一（simple_threshold 与模块化阈值同源管理，避免空白带矛盾）；
- 11.6 节：六层护栏总表默认值；
- 15.5 节：解析容错参数（重试 3 次、LLM 辅助修复默认关闭）；
- 3.6 节：执行模式默认安全审阅；11.0：自动模式预算倍数默认 2.5；
- 第 5 章：API 密钥从环境变量读取，不硬编码。
"""

from __future__ import annotations

import json

import pytest

from app.config import DEFAULT_MODELS, Settings, load_settings


class TestGuardrailDefaults:
    """11.6 护栏总表：六层默认值必须与规格一致。"""

    def test_layer0_task_budget(self):
        assert Settings().max_task_tokens == 200_000

    def test_auto_mode_budget_multiplier(self):
        # 11.0 / 3.6.3：自动模式预算 ×2~3，默认 ×2.5
        assert Settings().auto_mode_budget_multiplier == 2.5

    def test_layer1_discussion_rounds(self):
        assert Settings().max_discussion_rounds == 3

    def test_layer2_response_tokens(self):
        assert Settings().max_response_tokens == 8_000

    def test_layer3_similarity_threshold(self):
        assert Settings().similarity_threshold == 0.85

    def test_layer3_jaccard_threshold(self):
        assert Settings().jaccard_threshold == 0.9

    def test_layer3_loop_repeat_limit(self):
        assert Settings().loop_repeat_limit == 3

    def test_layer4_fix_rounds(self):
        assert Settings().max_fix_rounds == 5

    def test_layer5_spec_confirm_rounds(self):
        assert Settings().max_spec_confirm_rounds == 3


class TestRoutingThresholds:
    """3.2 节：简单编程节流 ≤3、模块化启用 ≥5，同一难度尺度集中管理。"""

    def test_simple_threshold(self):
        assert Settings().simple_threshold == 3

    def test_modular_difficulty_threshold(self):
        assert Settings().modular_difficulty_threshold == 5

    def test_modular_file_count_threshold(self):
        # 12.2 节：预估产出文件数 ≥6 也可触发模块化
        assert Settings().modular_file_count_threshold == 6

    def test_threshold_consistency_enforced(self):
        # 阈值统一：simple_threshold 必须小于模块化阈值，否则出现矛盾空白带
        with pytest.raises(ValueError, match="simple_threshold"):
            Settings(simple_threshold=5, modular_difficulty_threshold=5)


class TestModels:
    """3.3 节：预设模型列表。"""

    def test_default_models_match_spec(self):
        assert DEFAULT_MODELS == (
            "gpt-4o",
            "claude-3-5-sonnet",
            "deepseek-chat",
            "gemini-1.5-pro",
        )

    def test_settings_models_default(self):
        assert list(Settings().models) == list(DEFAULT_MODELS)

    def test_projects_root_default_empty(self):
        # 产出目录配置：缺省空串 → 各入口回落「启动目录/projects」
        assert Settings().projects_root == ""


class TestExecutionMode:
    """3.6 节：MVP 默认安全审阅模式。"""

    def test_default_mode_is_safe(self):
        assert Settings().default_execution_mode == "safe"

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValueError, match="execution_mode"):
            Settings(default_execution_mode="danger")

    def test_task_token_budget_safe_mode(self):
        s = Settings()
        assert s.task_token_budget("safe") == s.max_task_tokens

    def test_task_token_budget_auto_mode(self):
        s = Settings(max_task_tokens=200_000, auto_mode_budget_multiplier=2.5)
        assert s.task_token_budget("auto") == 500_000


class TestParseSettings:
    """15.5 节：解析容错参数。"""

    def test_max_parse_retries(self):
        assert Settings().max_parse_retries == 3

    def test_llm_assisted_repair_disabled_by_default(self):
        # 15.2：LLM 辅助修复默认关闭
        assert Settings().llm_json_repair is False

    def test_programmatic_repair_enabled_by_default(self):
        assert Settings().programmatic_json_repair is True

    def test_strict_json_response_enabled(self):
        assert Settings().strict_json_response is True


class TestApiKeys:
    """第 5 章安全性：API 密钥仅从环境变量读取。"""

    def test_get_api_key_openai(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert Settings().get_api_key("gpt-4o") == "sk-test"

    def test_get_api_key_anthropic(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-test")
        assert Settings().get_api_key("claude-3-5-sonnet") == "ak-test"

    def test_get_api_key_deepseek(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "dk-test")
        assert Settings().get_api_key("deepseek-chat") == "dk-test"

    def test_get_api_key_gemini(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")
        assert Settings().get_api_key("gemini-1.5-pro") == "gk-test"

    def test_get_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert Settings().get_api_key("gpt-4o") is None

    def test_get_api_key_unknown_provider(self):
        assert Settings().get_api_key("unknown-model") is None

    def test_load_settings_reads_env_file(self, tmp_path, monkeypatch):
        # .env 文件中的密钥应被加载
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("OPENAI_API_KEY=sk-from-file\n", encoding="utf-8")
        s = load_settings(
            env_file=env_file,
            config_file=tmp_path / "missing.json",
        )
        assert s.get_api_key("gpt-4o") == "sk-from-file"


class TestConfigFileOverride:
    """3.3 节：用户可通过 config.json 添加模型并覆盖默认参数。"""

    def test_override_models_and_threshold(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text(
            json.dumps(
                {
                    "models": ["gpt-4o", "qwen-max"],
                    "max_task_tokens": 300_000,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        s = load_settings(config_file=config)
        assert s.models == ["gpt-4o", "qwen-max"]
        assert s.max_task_tokens == 300_000

    def test_unknown_key_rejected(self, tmp_path):
        # 未知键直接报错（确定性校验），避免拼写错误静默失效
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"max_task_token": 1}), encoding="utf-8")
        with pytest.raises(ValueError, match="max_task_token"):
            load_settings(config_file=config)

    def test_type_mismatch_rejected(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"max_task_tokens": "200k"}), encoding="utf-8")
        with pytest.raises(ValueError, match="max_task_tokens"):
            load_settings(config_file=config)

    def test_bool_type_not_confused_with_int(self, tmp_path):
        # JSON 中 true 不能被当作 int 接受
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"max_task_tokens": True}), encoding="utf-8")
        with pytest.raises(ValueError, match="max_task_tokens"):
            load_settings(config_file=config)

    def test_non_dict_config_rejected(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text(json.dumps(["gpt-4o"]), encoding="utf-8")
        with pytest.raises(ValueError, match="配置"):
            load_settings(config_file=config)

    def test_missing_config_file_uses_defaults(self, tmp_path):
        s = load_settings(config_file=tmp_path / "missing.json")
        assert s.models == list(DEFAULT_MODELS)
        assert s.max_task_tokens == 200_000


class TestSettingsValidation:
    """参数合法性：确定性校验，程序兜底（总则 D.1）。"""

    @pytest.mark.parametrize("multiplier", [1.0, 3.5, -1])
    def test_budget_multiplier_out_of_range(self, multiplier):
        # 3.6.3：自动模式预算倍数必须落在 ×2~3
        with pytest.raises(ValueError, match="倍数"):
            Settings(auto_mode_budget_multiplier=multiplier)

    @pytest.mark.parametrize(
        "field_name",
        [
            "max_task_tokens",
            "max_discussion_rounds",
            "max_response_tokens",
            "max_fix_rounds",
            "max_spec_confirm_rounds",
            "loop_repeat_limit",
            "max_parse_retries",
        ],
    )
    def test_positive_int_fields(self, field_name):
        with pytest.raises(ValueError, match=field_name):
            Settings(**{field_name: 0})

    @pytest.mark.parametrize(
        "field_name",
        ["similarity_threshold", "jaccard_threshold"],
    )
    def test_similarity_in_unit_range(self, field_name):
        with pytest.raises(ValueError, match=field_name):
            Settings(**{field_name: 1.5})

    def test_models_must_not_be_empty(self):
        with pytest.raises(ValueError, match="模型"):
            Settings(models=[])

    def test_models_must_be_unique(self):
        with pytest.raises(ValueError, match="重复"):
            Settings(models=["gpt-4o", "gpt-4o"])

    def test_research_budget_default(self):
        # 4.4：Researcher 独立预算默认 20k（Beta 预留）
        assert Settings().research_budget_tokens == 20_000

    def test_sandbox_timeout_default(self):
        # 3.6.3：沙箱 30s 超时熔断（Alpha v0.4 使用，MVP 仅预留）
        assert Settings().sandbox_timeout_seconds == 30
