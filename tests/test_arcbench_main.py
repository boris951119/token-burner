"""参赛入口 main.py 冒烟测试（headless 链路，LLM 全 mock）。

取证：墙钟兜底曾插在 load_settings 之前 → UnboundLocalError 启动即炸，
而 main.py 此前零测试覆盖。本文件锁住入口契约：
- 单模型下发 → settings.models=[m] + single_model_mode + 墙钟兜底 600；
- --output-dir 未配 ARCBENCH_OUTPUT_DIR 时 setdefault 对齐（事件落 workspace）；
- 交付成功 → verify_delivery 把关，PASS/FAIL 都交付（exit 0），
  FAIL 时失败详情进交付摘要（平台取证：exit 1 = 不评分 = 0 分）；
- 管线 declined → run_failed/返回 1。
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

import main as entry
from app.config import Settings


_TREE = dedent(
    """\
    name: Demo
    description: demo app
    children:
      - id: F1
        type: FOLDER
        name: Core
        description: core module
        dependencies: []
        children:
          - id: REQ-1
            type: ATOMIC
            name: Health
            description: health endpoint
            scenarios: []
    """
)


@pytest.fixture
def req_dir(tmp_path) -> Path:
    d = tmp_path / "requirements"
    d.mkdir()
    (d / "requirements.yaml").write_text(_TREE, encoding="utf-8")
    (d.parent / "tests").mkdir()
    (d.parent / "tests" / "helpers.ts").write_text("export const F = {}", encoding="utf-8")
    return d


class _FakePipeline:
    def __init__(self, result, captured=None, **kwargs):
        self._captured = captured
        self.result = result
        from app.tools.file_manager import FileManager

        self.file_manager = FileManager(
            projects_root=kwargs["file_manager"].projects_root
        )

    def run(self, *args, **kwargs):
        if self._captured is not None:
            self._captured["run_kwargs"] = kwargs
        return self.result


def _team_result(project_dir):
    from app.pipeline import PipelineResult

    # main.py 成功不变量（r10 取证）要求交付项目带 completed.json 终局标记
    (Path(project_dir) / "sessions").mkdir(parents=True, exist_ok=True)
    (Path(project_dir) / "sessions" / "completed.json").write_text(
        "{}", encoding="utf-8")
    return PipelineResult(
        kind="team_flow", project_dir=project_dir, deliverable_summary="交付完成"
    )


def _patch_llm_paths(monkeypatch, result, verify=(True, "verify ok")):
    """屏蔽真实网关与真实验收，替换管线为假件。"""
    captured = {}

    def fake_load_settings(config_file=None, **kw):
        captured["config_file"] = str(config_file) if config_file else None
        captured["settings"] = Settings(models=["openai/glm-5.3"])
        return captured["settings"]

    class _FakePipelineInstance(_FakePipeline):
        pass

    def make_pipeline(**kwargs):
        return _FakePipelineInstance(result, captured, **kwargs)

    monkeypatch.setattr(entry, "load_settings", fake_load_settings)
    monkeypatch.setattr(entry, "_gateway_preflight", lambda settings: None)
    monkeypatch.setattr(entry, "Pipeline", make_pipeline)
    monkeypatch.setattr(
        "app.arcbench_smoke.verify_delivery",
        lambda project_dir, requirement, settings, **kw: verify,
    )
    return captured


def _env(monkeypatch, out_dir, *, unset_arcbench_env=True):
    monkeypatch.setenv("OPENAI_API_KEY", "ak_test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gw.test/v1")
    monkeypatch.setenv("MODEL", "glm-5.3")
    if unset_arcbench_env:
        monkeypatch.delenv("ARCBENCH_OUTPUT_DIR", raising=False)
    return ["str(requirement)", "-o", str(out_dir)]


def test_success_path_entry_contract(monkeypatch, tmp_path, req_dir):
    out = tmp_path / "workspace"
    _env(monkeypatch, out)
    captured = _patch_llm_paths(
        monkeypatch, _team_result(tmp_path / "delivery")
    )
    rc = entry.main(
        [str(req_dir), "-o", str(out), "--type", "web", "--mode", "auto"]
    )
    assert rc == 0

    settings = captured["settings"]
    assert settings.models == ["openai/glm-5.3"]      # 单模型（非 [m,m,m]）
    assert settings.single_model_mode is True          # 互异校验放行
    assert settings.llm_wall_clock_seconds == 600      # 墙钟兜底
    assert settings.enable_git is False                # 双 git 污染防护

    # 管线拿到单模型（由 _model_triplet 同模补位为三元组）
    assert captured["run_kwargs"]["models"] == ("openai/glm-5.3",)

    # 事件流落在 workspace/.arc（setdefault 对齐）
    events = out / ".arc" / "runner-events.jsonl"
    assert events.is_file()
    kinds = [json.loads(ln)["type"] for ln in events.read_text(
        encoding="utf-8").strip().splitlines()]
    assert "runner_state" in kinds
    assert kinds[-1] in ("runner_state", "signal")


def test_verify_failure_still_delivers(monkeypatch, tmp_path, req_dir):
    """平台 v6-1 取证（¥47/5.7h 白扔）：exit 1 = 平台不评分 = 0 分。
    验收是教练不是评判者——FAIL 也交付（exit 0），失败详情进交付摘要。"""
    out = tmp_path / "ws2"
    _env(monkeypatch, out)
    _patch_llm_paths(
        monkeypatch, _team_result(tmp_path / "d2"), verify=(False, "旅程断言失败")
    )
    rc = entry.main([str(req_dir), "-o", str(out), "--mode", "auto"])
    assert rc == 0
    events = (out / ".arc" / "runner-events.jsonl").read_text(
        encoding="utf-8")
    parsed = " ".join(
        json.loads(line).get("message", "") + json.loads(line).get("reason", "")
        for line in events.splitlines() if line.strip()
    )
    assert "completed" in events
    assert "未通过" in parsed


def test_declined_terminal_returns_1(monkeypatch, tmp_path, req_dir):
    from app.pipeline import PipelineResult

    out = tmp_path / "ws3"
    _env(monkeypatch, out)
    _patch_llm_paths(
        monkeypatch,
        PipelineResult(kind="declined", declined_reply="需要明确需求"),
    )
    rc = entry.main([str(req_dir), "-o", str(out), "--mode", "auto"])
    assert rc == 1


def test_resume_flag_without_snapshot_returns_1(monkeypatch, tmp_path, req_dir):
    out = tmp_path / "ws4"
    _env(monkeypatch, out)
    captured = _patch_llm_paths(monkeypatch, _team_result(tmp_path / "d4"))
    rc = entry.main([str(req_dir), "-o", str(out), "--mode", "auto", "--resume"])
    assert rc == 1  # 无可恢复快照 → RuntimeError → run_failed
    assert "failed" in (out / ".arc" / "runner-events.jsonl").read_text(
        encoding="utf-8")


# ---- factory26 r6：中转站多模型组队（单 key 11 模型全通可并发） ----


def test_multi_model_flag_builds_distinct_triplet(monkeypatch):
    """flag 开：注入模型任主 LLM，开发/测试取预设互异者；互异校验不放行。"""
    settings = Settings(
        models=["openai/deepseek-v4-pro", "openai/qwen3.8-max", "openai/glm-5.2"],
        platform_multi_model=True,
    )
    monkeypatch.setenv("MODEL", "glm-5.3")
    entry._apply_runner_model(settings)
    assert settings.models == [
        "openai/glm-5.3", "openai/deepseek-v4-pro", "openai/qwen3.8-max",
    ]
    assert settings.single_model_mode is False  # 三模型互异，规格 3.3 校验生效


def test_multi_model_flag_excludes_injected_from_preset(monkeypatch):
    """注入模型即在预设中：预设剔除后依序补位，不出现重复项。"""
    settings = Settings(
        models=["openai/deepseek-v4-pro", "openai/qwen3.8-max", "openai/glm-5.2"],
        platform_multi_model=True,
    )
    monkeypatch.setenv("MODEL", "deepseek-v4-pro")
    entry._apply_runner_model(settings)
    assert settings.models == [
        "openai/deepseek-v4-pro", "openai/qwen3.8-max", "openai/glm-5.2",
    ]
    assert len(set(settings.models)) == 3
    assert settings.single_model_mode is False


def test_multi_model_flag_falls_back_to_single_when_preset_empty(monkeypatch):
    """预设为空/全同注入模型：自然回落单模型模式。"""
    settings = Settings(models=["openai/glm-5.3"], platform_multi_model=True)
    monkeypatch.setenv("MODEL", "glm-5.3")
    entry._apply_runner_model(settings)
    assert settings.models == ["openai/glm-5.3"]
    assert settings.single_model_mode is True


def test_flag_off_keeps_strict_single_model(monkeypatch):
    """flag 关（缺省）：注入模型收敛单模型，行为与 r4 版本一致。"""
    settings = Settings(
        models=["openai/deepseek-v4-pro", "openai/qwen3.8-max"],
    )
    monkeypatch.setenv("MODEL", "glm-5.3")
    entry._apply_runner_model(settings)
    assert settings.models == ["openai/glm-5.3"]
    assert settings.single_model_mode is True


class TestRunnerModelAutocomplete:
    """generation-5 取证：容器 CWD≠提交目录时 config.json 可能不生效，
    编制退化为注入单模型、备胎链为空——官方中转站上必须自动补全。"""

    def _apply(self, monkeypatch, model, base, platform_multi, models):
        from app.config import Settings
        import os

        monkeypatch.setenv("MODEL", model)
        monkeypatch.setenv("OPENAI_BASE_URL", base)
        monkeypatch.delenv("OPENAI_API_BASE", raising=False)
        settings = Settings(models=list(models),
                            platform_multi_model=platform_multi)
        from main import _apply_runner_model
        _apply_runner_model(settings)
        return settings

    def test_official_relay_single_model_autocompletes(self, monkeypatch):
        s = self._apply(monkeypatch, "deepseek-v4-pro",
                        "https://api.arc-bench.com/v1",
                        False, ["deepseek-v4-pro"])
        assert s.single_model_mode is False
        assert s.models == ["openai/deepseek-v4-pro", "openai/minimax-m3",
                            "openai/glm-5.3"]

    def test_non_official_relay_stays_single(self, monkeypatch):
        s = self._apply(monkeypatch, "deepseek-v4-pro",
                        "https://other-relay.example/v1",
                        False, ["deepseek-v4-pro"])
        assert s.single_model_mode is True
        assert s.models == ["openai/deepseek-v4-pro"]

    def test_platform_multi_path_unaffected(self, monkeypatch):
        s = self._apply(monkeypatch, "deepseek-v4-pro",
                        "https://api.arc-bench.com/v1",
                        True, ["openai/deepseek-v4-pro", "openai/minimax-m3",
                               "openai/glm-5.3"])
        assert s.single_model_mode is False
        assert s.models[0] == "openai/deepseek-v4-pro"
        assert len(s.models) == 3
