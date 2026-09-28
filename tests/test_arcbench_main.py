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


def _patch_llm_paths(monkeypatch, result, verify=(True, "verify ok"),
                     tune=None):
    """屏蔽真实网关与真实验收，替换管线为假件。"""
    captured = {}

    def fake_load_settings(config_file=None, **kw):
        captured["config_file"] = str(config_file) if config_file else None
        s = Settings(models=["openai/glm-5.3"])
        if tune is not None:
            tune(s)
        captured["settings"] = s
        return s

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


def _events_text(out: Path) -> str:
    """事件流解码成可断言文本（jsonl 里的中文是 \\u 转义，裸 in 断言必假）。"""
    lines = (out / ".arc" / "runner-events.jsonl").read_text(
        encoding="utf-8").splitlines()
    return "\n".join(
        json.dumps(json.loads(line), ensure_ascii=False)
        for line in lines if line.strip())


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
    assert settings.llm_timeout_seconds == 600         # read timeout 对齐墙钟
    assert settings.discussion_max_minutes == 35       # 讨论阶段时间闸
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


def test_read_timeout_never_narrower_than_wall_clock(monkeypatch, tmp_path, req_dir):
    """shape-keep 彩排取证（9/23 整跑夭折）：零 config.json 形态下 read
    timeout 吃代码默认 120s，而对话补全是非流式——整段生成期间一个字节
    都没有，推理模型慢调用必被 httpx 斩断成 litellm.Timeout（讨论阶段
    4×120s 全灭 → rc=1 → 平台不评分）。runner 形态把两者对齐，墙钟成为
    唯一上界：慢但合法的生成放行，真挂死的仍按秒退出。
    """
    out = tmp_path / "ws-rt"
    _env(monkeypatch, out)
    _patch_llm_paths(monkeypatch, _team_result(tmp_path / "rt"))
    tuned = Settings(models=["openai/glm-5.3"], llm_wall_clock_seconds=1200,
                     llm_timeout_seconds=200)
    monkeypatch.setattr(entry, "load_settings", lambda **kw: tuned)
    assert entry.main([str(req_dir), "-o", str(out), "--type", "web",
                       "--mode", "auto"]) == 0
    assert tuned.llm_timeout_seconds == 1200, "read timeout 必须抬到墙钟同宽"


def test_wider_read_timeout_left_alone(monkeypatch, tmp_path, req_dir):
    """配置本就给了更宽 read timeout 时不得被拉窄（对齐是单向地板）。"""
    out = tmp_path / "ws-rt2"
    _env(monkeypatch, out)
    _patch_llm_paths(monkeypatch, _team_result(tmp_path / "rt2"))
    tuned = Settings(models=["openai/glm-5.3"], llm_wall_clock_seconds=600,
                     llm_timeout_seconds=900)
    monkeypatch.setattr(entry, "load_settings", lambda **kw: tuned)
    assert entry.main([str(req_dir), "-o", str(out), "--type", "web",
                       "--mode", "auto"]) == 0
    assert tuned.llm_timeout_seconds == 900


def test_discussion_minutes_env_override(monkeypatch, tmp_path, req_dir):
    """讨论时间闸 runner 缺省 35 分钟（24 分钟健康讨论实测之上），可覆盖含 0 关闭。"""
    out = tmp_path / "ws-dg"
    _env(monkeypatch, out)
    _patch_llm_paths(monkeypatch, _team_result(tmp_path / "dg"))
    tuned = Settings(models=["openai/glm-5.3", "openai/minimax-m3",
                             "openai/glm-4.6v"], discussion_max_minutes=0.0)
    monkeypatch.setattr(entry, "load_settings", lambda **kw: tuned)
    monkeypatch.setenv("DISCUSSION_MINUTES", "45")
    assert entry.main([str(req_dir), "-o", str(out), "--type", "web",
                       "--mode", "auto"]) == 0
    assert tuned.discussion_max_minutes == 45.0


def test_env_float_dirty_value_falls_back(monkeypatch, capsys):
    """批次#24：这两处读取在 pipeline.run 之前，裸 float() 遇
    `DISCUSSION_MINUTES=35min` 这类笔误直接抛 ValueError＝整跑零交付，
    而看门狗/讨论闸本身都是保命用的，不该成为最早的死因。"""
    monkeypatch.setenv("DISCUSSION_MINUTES", "35min")
    assert entry._env_float("DISCUSSION_MINUTES", "35") == 35.0
    assert "非数值" in capsys.readouterr().out
    # 空串＝显式关闭（原口径不变），合法值原样采信
    monkeypatch.setenv("DISCUSSION_MINUTES", "")
    assert entry._env_float("DISCUSSION_MINUTES", "35") == 0.0
    monkeypatch.setenv("WATCHDOG_MINUTES", "120")
    assert entry._env_float("WATCHDOG_MINUTES", "200") == 120.0


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
    # 隔离中转站补全通道：dotenv 残留（如本机 .env 指向官方网关）会
    # 让本用例误入编队自动补全分支（与 TestRunnerModelAutocomplete 同法）
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    entry._apply_runner_model(settings)
    assert settings.models == ["openai/glm-5.3"]
    assert settings.single_model_mode is True


def test_flag_off_keeps_strict_single_model(monkeypatch):
    """flag 关（缺省）：注入模型收敛单模型，行为与 r4 版本一致。"""
    settings = Settings(
        models=["openai/deepseek-v4-pro", "openai/qwen3.8-max"],
    )
    monkeypatch.setenv("MODEL", "glm-5.3")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
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

    def test_shipped_config_is_the_official_formation(self, monkeypatch):
        """v44 P0：随包 config.json 必须是正式档——帽关闭、specs 开、
        官方三腿。试跑档（1.6M 帽 / specs off / 便宜腿）不得再默默随包。"""
        import json
        from pathlib import Path

        from app.config import load_settings
        from app.pipeline import _model_triplet

        cfg = Path(entry.__file__).resolve().parent / "config.json"
        raw = json.loads(cfg.read_text(encoding="utf-8"))
        loaded = load_settings(config_file=cfg)
        assert int(raw.get("max_task_tokens_cap") or 0) == 0
        assert raw.get("selftest_specs_enabled", True) is True
        assert loaded.max_task_tokens_cap == 0
        assert loaded.selftest_specs_enabled is True
        s = self._apply(monkeypatch, "deepseek-v4-pro",
                        "https://api.arc-bench.com/v1",
                        True, raw["models"])
        assert set(_model_triplet(s.models)) == {
            "openai/deepseek-v4-pro", "openai/deepseek-v4-flash",
            "openai/qwen3.7-max"}
        assert s.models[0] == "openai/deepseek-v4-pro"
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


# ---- Linux 容器取证：官方题面曾被闲聊路由判 direct_answer 静默 rc=1 ----

class TestForcedRouteOnTreeEntry:
    def test_tree_entry_forces_team_flow_route(self, monkeypatch, tmp_path,
                                               req_dir):
        from app.orchestrator import Route

        out = tmp_path / "wsR"
        _env(monkeypatch, out)
        captured = _patch_llm_paths(
            monkeypatch, _team_result(tmp_path / "dr"))
        rc = entry.main([str(req_dir), "-o", str(out), "--type", "web",
                         "--mode", "auto"])
        assert rc == 0
        route = captured["run_kwargs"]["route"]
        assert route is not None
        assert route.route is Route.TEAM_FLOW
        assert route.task_type == "编程"
        assert not route.needs_user_confirm
        # 模块化判定输入：FOLDER 数 → estimated_files ≥ 阈值 6
        assert route.estimated_files >= 6

    def test_task_envelope_hard_cap_binds_at_the_entry_and_says_so(
            self, monkeypatch, tmp_path, req_dir, capsys):
        """v42-1 接线：cap 写进随包 config.json 就必须真能砍到这一跑的信封，
        并在 stdout 上留痕（官方容器只看得到日志；9ac543c41514 是精确烧满被
        抬起来的 486 万之后，死在免费自测闸之前）。"""
        out = tmp_path / "wsCap"
        _env(monkeypatch, out)
        captured = _patch_llm_paths(
            monkeypatch, _team_result(tmp_path / "dbCap"),
            tune=lambda s: setattr(s, "max_task_tokens_cap", 300_000))
        assert entry.main([str(req_dir), "-o", str(out), "--mode", "auto"]) == 0
        assert captured["run_kwargs"]["budget_override"] == 300_000
        printed = capsys.readouterr().out
        assert "硬帽 300,000 已砍" in printed, printed[-500:]

    def test_tree_entry_gets_size_aware_budget_envelope(
            self, monkeypatch, tmp_path, req_dir):
        """题面入口的信封按需求条数折算，而不是吃 config 里写死的数。

        官方容器不带 config.json → 生效值是代码缺省 200k（自动 ×2.5=500k），
        而 9/23 全真彩排里四需求的最小一道题实测就要 518k：预算低于最小可完成
        成本时先撞墙的是修复（三轮瞬时抛在同一行「预算已耗尽」上）。
        """
        from app.utils.budget import size_aware_budget

        out = tmp_path / "wsB"
        _env(monkeypatch, out)
        captured = _patch_llm_paths(
            monkeypatch, _team_result(tmp_path / "db"))
        assert entry.main([str(req_dir), "-o", str(out), "--mode", "auto"]) == 0
        # req_dir 夹具的树里 1 条 ATOMIC
        assert captured["run_kwargs"]["budget_override"] == size_aware_budget(1)

    def test_text_entry_leaves_budget_to_config(self, monkeypatch, tmp_path):
        """纯文本需求没有题面可量 → 不折算，仍走配置/代码缺省。"""
        out = tmp_path / "wsB2"
        _env(monkeypatch, out)
        captured = _patch_llm_paths(
            monkeypatch, _team_result(tmp_path / "db2"))
        assert entry.main(["做一个备忘录网页应用", "-o", str(out),
                           "--mode", "auto"]) == 0
        assert captured["run_kwargs"]["budget_override"] is None

    def test_text_entry_keeps_llm_router(self, monkeypatch, tmp_path):
        out = tmp_path / "wsT"
        _env(monkeypatch, out)
        captured = _patch_llm_paths(
            monkeypatch, _team_result(tmp_path / "dt"))
        rc = entry.main(["做一个备忘录网页应用", "-o", str(out),
                         "--mode", "auto"])
        assert rc == 0
        assert captured["run_kwargs"].get("route") is None

    def test_non_success_terminal_leaves_stdout_trace(
            self, monkeypatch, tmp_path, req_dir, capsys):
        from app.pipeline import PipelineResult

        out = tmp_path / "wsD"
        _env(monkeypatch, out)
        _patch_llm_paths(monkeypatch,
                         PipelineResult(kind="direct_answer", answer="x"))
        rc = entry.main([str(req_dir), "-o", str(out), "--mode", "auto"])
        assert rc == 1
        assert "管线非成功终态: kind=direct_answer" in (
            capsys.readouterr().out)


# ---- 启动/收尾两处「非致命故障曾被当成致命」的回归 ----

class TestNonFatalFailuresStayNonFatal:
    def test_broken_config_json_falls_back_and_runs(
            self, monkeypatch, tmp_path, req_dir, capsys):
        """config.json 坏掉 ≠ 整场 0 分：回退代码默认值继续跑完。

        取证：load_settings 对未知键/类型不符抛 ValueError，而它在
        管线之前被裸调用——一行 JSON 拼写错误即可让进程零输出崩穿，
        平台侧 exit 1（不评分）。
        """
        out = tmp_path / "wsCfg"
        _env(monkeypatch, out)
        _patch_llm_paths(monkeypatch, _team_result(tmp_path / "dcfg"))

        def boom(config_file=None, **kw):
            raise ValueError("配置文件包含未知字段: ['modelz']（请检查拼写）")

        monkeypatch.setattr(entry, "load_settings", boom)
        rc = entry.main([str(req_dir), "-o", str(out), "--type", "web",
                         "--mode", "auto"])
        assert rc == 0
        printed = capsys.readouterr().out
        assert "配置读取失败 → 回退代码默认值" in printed
        # 回退后仍走单模型注入 + 中转站补全，不是空编制
        assert "最终编制: models=['openai/glm-5.3'" in printed

    def test_verify_crash_does_not_eat_finished_project(
            self, monkeypatch, tmp_path, req_dir, capsys):
        """验收器崩溃时产物已齐备：exit 1 会把整个项目一起扔掉。"""
        out = tmp_path / "wsV"
        _env(monkeypatch, out)
        _patch_llm_paths(monkeypatch, _team_result(tmp_path / "dver"))

        def boom(*a, **kw):
            raise RuntimeError("selftest gate 内部炸了")

        monkeypatch.setattr("app.arcbench_smoke.verify_delivery", boom)
        rc = entry.main([str(req_dir), "-o", str(out), "--mode", "auto"])
        assert rc == 0
        printed = capsys.readouterr().out
        assert "验收器内部故障" in printed
        # v56：摘要标 FAIL 防监控假绿，但 exit 0 仍交卷（平台 exit1=不评分）
        assert "照常交付" in printed
        assert "completed" in _events_text(out)         # 终态仍是已交付


# ---- 网关预检：整场 0 分曾经的单点故障 ----

class TestGatewayPreflight:
    """旧实现只探编制首位且失败即崩穿（预检在管线 try 之外）：注入模型
    一次偶发超时 = exit 1 = 不评分，而同网关其余模型当时完全可用。"""

    class _MC:
        pinged: list[str] = []

        def __init__(self, settings):
            pass

        def chat(self, model, messages, **kw):
            type(self).pinged.append(model)
            if "dead" in model:
                raise RuntimeError("Connection error.")
            return "pong"

    def _run(self, monkeypatch, models):
        self._MC.pinged = []
        monkeypatch.setattr("app.utils.model_client.ModelClient", self._MC)
        s = Settings(models=list(models))
        entry._gateway_preflight(s)
        return s

    def test_alive_model_is_promoted_to_head(self, monkeypatch):
        s = self._run(monkeypatch, ["openai/dead-1", "openai/good-2",
                                    "openai/good-3"])
        assert s.models[0] == "openai/good-2"     # 管线主用已验证可用者
        assert "openai/dead-1" in s.models        # 偶发失败≠不可用：留作备胎
        assert self._MC.pinged == ["openai/dead-1", "openai/good-2"]  # 首位活即止

    def test_healthy_formation_pings_once(self, monkeypatch):
        s = self._run(monkeypatch, ["openai/good-1", "openai/good-2"])
        assert self._MC.pinged == ["openai/good-1"]
        assert s.models == ["openai/good-1", "openai/good-2"]   # 原序不动

    def test_all_dead_raises_with_per_model_reasons(self, monkeypatch):
        self._MC.pinged = []
        monkeypatch.setattr("app.utils.model_client.ModelClient", self._MC)
        with pytest.raises(RuntimeError) as ei:
            entry._gateway_preflight(
                Settings(models=["openai/dead-a", "openai/dead-b"]))
        msg = str(ei.value)
        assert "全灭" in msg and "dead-a" in msg and "Connection error" in msg

    def test_preflight_failure_reports_clean_terminal(
            self, monkeypatch, tmp_path, req_dir):
        """全灭仍快速失败：终态经桥接层报出（裸崩只剩一行 traceback），
        退出码换 0 + 保底骨架（批次#63B，用户拍板"交"）——exit 1 = 不评分，
        而两个任务都要有运行记录才有排名；骨架不含任何业务路由，也不冒充成功。
        """
        out = tmp_path / "wsP"
        _env(monkeypatch, out)
        _patch_llm_paths(monkeypatch, _team_result(tmp_path / "dp"))

        def boom(settings):
            raise RuntimeError("网关预检全灭（无一模型可通）: openai/dead-a")

        monkeypatch.setattr(entry, "_gateway_preflight", boom)
        assert entry.main([str(req_dir), "-o", str(out), "--mode", "auto"]) == 0
        assert "预检全灭" in _events_text(out), "终态仍要如实报失败，不许改口成功"
        assert (out / "backend" / "ARCBENCH_SKELETON.txt").is_file(), \
            "网关全灭这一档必须交出骨架换运行记录"
        assert not (out / "backend" / "app_main").exists()

    def test_task_banner_survives_dead_gateway(
            self, monkeypatch, tmp_path, req_dir, capsys):
        """题面横幅打在预检之前：网关全灭那次跑也要在日志里留下「读到了
        什么题面、给了多大信封」——官方容器只看得到 stdout，而上一行打印的
        budget= 是配置口径，不代表这一跑真正用的信封。"""
        from app.utils.budget import size_aware_budget

        out = tmp_path / "wsP2"
        _env(monkeypatch, out)
        _patch_llm_paths(monkeypatch, _team_result(tmp_path / "dp2"))
        monkeypatch.setattr(
            entry, "_gateway_preflight",
            lambda settings: (_ for _ in ()).throw(RuntimeError("全灭")))
        assert entry.main([str(req_dir), "-o", str(out), "--mode", "auto"]) == 0
        printed = capsys.readouterr().out
        assert f"任务信封={size_aware_budget(1):,}" in printed, printed[-400:]


# ---- 预算中止的手半成品：不导出 = 已经写出来的代码换 0 分 ----

class TestBudgetPartialDelivery:
    def _partial(self, tmp_path, name="partial"):
        proj = tmp_path / name
        (proj / "code").mkdir(parents=True)
        (proj / "code" / "app.py").write_text("print(1)\n", encoding="utf-8")
        return proj

    def test_budget_exceeded_exports_and_scores(self, monkeypatch, tmp_path,
                                                req_dir, capsys):
        from app.pipeline import PipelineResult

        out = tmp_path / "wsB"
        _env(monkeypatch, out)
        proj = self._partial(tmp_path)
        _patch_llm_paths(monkeypatch, PipelineResult(
            kind="budget_exceeded", project_dir=proj,
            deliverable_summary="预算中止：已完成 3/5 模块"))
        called = []
        monkeypatch.setattr(
            "app.platform_export.export_platform_layout",
            lambda workdir, pd, **_k: (called.append(str(pd))
                                 or {"backend_files": 3, "frontend_files": 0}))
        rc = entry.main([str(req_dir), "-o", str(out), "--mode", "auto"])
        assert rc == 0                                   # 换取被评分的机会
        assert called == [str(proj)]
        printed = capsys.readouterr().out
        assert "退出码 0 换取评分" in printed
        assert "半成品已按官方布局导出" in printed
        assert "未走验收" in _events_text(out)            # 摘要不冒充完成

    def test_export_failure_still_returns_1(self, monkeypatch, tmp_path,
                                            req_dir):
        from app.pipeline import PipelineResult

        out = tmp_path / "wsB2"
        _env(monkeypatch, out)
        _patch_llm_paths(monkeypatch, PipelineResult(
            kind="budget_exceeded", project_dir=self._partial(tmp_path, "p2")))

        def boom(workdir, pd, **_k):
            raise RuntimeError("布局导出炸了")

        monkeypatch.setattr("app.platform_export.export_platform_layout", boom)
        assert entry.main([str(req_dir), "-o", str(out), "--mode", "auto"]) == 1

    def test_interrupted_with_code_on_disk_also_ships(
            self, monkeypatch, tmp_path, req_dir):
        """9/23 交付路径审计取证：此前只有 budget_exceeded 走尽力交付，
        interrupted/declined 明明带着写完的模块回来，却因终态名不对 exit 1
        = 不评分。判分是 avg_pass_rate，半成品有分。"""
        from app.pipeline import PipelineResult

        out = tmp_path / "wsI"
        _env(monkeypatch, out)
        proj = self._partial(tmp_path, "interrupted_proj")
        _patch_llm_paths(monkeypatch, PipelineResult(
            kind="interrupted", project_dir=proj))
        called = []
        monkeypatch.setattr(
            "app.platform_export.export_platform_layout",
            lambda workdir, pd, **_k: (called.append(str(pd))
                                 or {"backend_files": 1, "frontend_files": 0}))
        assert entry.main([str(req_dir), "-o", str(out), "--mode", "auto"]) == 0
        assert called == [str(proj)]
        events = _events_text(out)
        assert "interrupted·部分交付" in events
        assert "未走验收" in events

    def test_stub_only_package_marker_does_not_ship(
            self, monkeypatch, tmp_path, req_dir):
        """盘上只剩包标记 __init__.py 不算交付物——仍按失败终态收口，
        否则「尽力交」会退化成「无论多空都报完成」。"""
        from app.pipeline import PipelineResult

        out = tmp_path / "wsS"
        _env(monkeypatch, out)
        proj = tmp_path / "stub_only"
        (proj / "code" / "notes").mkdir(parents=True)
        (proj / "code" / "notes" / "__init__.py").write_text("",
                                                             encoding="utf-8")
        _patch_llm_paths(monkeypatch, PipelineResult(
            kind="interrupted", project_dir=proj))
        called = []
        monkeypatch.setattr(
            "app.platform_export.export_platform_layout",
            lambda w, p, **_k: (called.append(str(p)) or {}))
        assert entry.main([str(req_dir), "-o", str(out), "--mode", "auto"]) == 1
        assert called == []


class TestCrashSalvage:
    """管线抛异常时的兜底交付（9/23 交付路径审计取证 P1-9）。"""

    def test_pipeline_crash_exports_code_on_disk(self, monkeypatch, tmp_path,
                                                 req_dir):
        out = tmp_path / "wsC"
        _env(monkeypatch, out)
        monkeypatch.setattr(
            entry, "load_settings",
            lambda config_file=None, **kw: Settings(models=["openai/glm-5.3"]))
        monkeypatch.setattr(entry, "_gateway_preflight", lambda settings: None)
        proj = out / "projects" / "arcbench-app_crash"
        (proj / "code" / "notes").mkdir(parents=True)
        (proj / "code" / "notes" / "notes.py").write_text("x = 1\n",
                                                          encoding="utf-8")

        class _Boom:
            def __init__(self, **kwargs):
                pass

            def run(self, *args, **kwargs):
                raise RuntimeError("管线炸在半路")

        monkeypatch.setattr(entry, "Pipeline", _Boom)
        called = []
        monkeypatch.setattr(
            "app.platform_export.export_platform_layout",
            lambda workdir, pd, **_k: (called.append(str(pd))
                                 or {"backend_files": 1, "frontend_files": 0}))
        assert entry.main([str(req_dir), "-o", str(out), "--mode", "auto"]) == 0
        assert called == [str(proj)], "兜底取工作区里最新的项目目录"
        events = _events_text(out)
        assert "管线异常·部分交付" in events and "RuntimeError" in events

    def test_crash_without_any_code_still_fails(self, monkeypatch, tmp_path,
                                                req_dir):
        out = tmp_path / "wsC2"
        _env(monkeypatch, out)
        monkeypatch.setattr(
            entry, "load_settings",
            lambda config_file=None, **kw: Settings(models=["openai/glm-5.3"]))
        monkeypatch.setattr(entry, "_gateway_preflight", lambda settings: None)
        (out / "projects" / "arcbench-app_empty").mkdir(parents=True)

        class _Boom:
            def __init__(self, **kwargs):
                pass

            def run(self, *args, **kwargs):
                raise RuntimeError("启动即炸")

        monkeypatch.setattr(entry, "Pipeline", _Boom)
        called = []
        monkeypatch.setattr(
            "app.platform_export.export_platform_layout",
            lambda w, p, **_k: (called.append(str(p)) or {}))
        assert entry.main([str(req_dir), "-o", str(out), "--mode", "auto"]) == 1
        assert called == []
        assert "管线异常" in _events_text(out)
        """没产物就没得交付：不误导平台，仍按失败终态收口。"""
        from app.pipeline import PipelineResult

        out = tmp_path / "wsB3"
        _env(monkeypatch, out)
        _patch_llm_paths(monkeypatch, PipelineResult(kind="declined"))
        called = []
        monkeypatch.setattr(
            "app.platform_export.export_platform_layout",
            lambda w, p, **_k: called.append(p) or {})
        assert entry.main([str(req_dir), "-o", str(out), "--mode", "auto"]) == 1
        assert called == []


def test_export_precedes_verify_so_a_kill_still_ships(monkeypatch, tmp_path,
                                                      req_dir):
    """抢先导出（9/23 结构漏洞）：验收段可以跑几个小时，而官方侧的超时/
    OOM/预算截断是 SIGKILL——Python 末尾那次导出根本不会执行，输出目录里
    只剩生成中间态，写完的代码等于没写。导出幂等，先落一份再按最终态覆盖。
    """
    out = tmp_path / "wsE"
    _env(monkeypatch, out)
    order: list[str] = []
    _patch_llm_paths(monkeypatch, _team_result(tmp_path / "deliveryE"))
    monkeypatch.setattr(
        "app.arcbench_smoke.verify_delivery",
        lambda *a, **k: (order.append("verify") or (True, "verify ok")))
    monkeypatch.setattr(
        "app.platform_export.export_platform_layout",
        lambda w, p, **_k: (order.append("export")
                      or {"backend_files": 1, "frontend_files": 1,
                          "export_probe": {"ok": False}}))
    rc = entry.main(
        [str(req_dir), "-o", str(out), "--type", "web", "--mode", "auto"])
    assert rc == 0
    assert order == ["export", "verify", "export"], \
        "验收前必须已经落一份可运行产物，验收后再按最终态覆盖"


class TestRingRequirementsDir:
    """编译自评分环（零 LLM 判分层）的题面来源：单文件输入不得让它静默缺席。

    批次#32 同族取证：这一层此前只在「位置参数是目录」时开工，官方侧若
    以下发单文件形态出现，判分红叶就少一整层——而本地全绿看不见。
    """

    def test_dir_input_resolves_to_absolute(self, req_dir):
        assert entry._ring_requirements_dir(req_dir) == req_dir.resolve()

    def test_file_input_lands_on_its_parent(self, req_dir):
        got = entry._ring_requirements_dir(req_dir / "requirements.yaml")
        assert got == req_dir.resolve()

    def test_missing_path_is_explicit_none(self, tmp_path):
        assert entry._ring_requirements_dir(tmp_path / "nope") is None

    def test_file_input_still_feeds_the_verify_ring(self, monkeypatch, tmp_path,
                                                   req_dir):
        out = tmp_path / "wsRing"
        _env(monkeypatch, out)
        seen = {}
        _patch_llm_paths(monkeypatch, _team_result(tmp_path / "deliveryRing"))
        monkeypatch.setattr(
            "app.arcbench_smoke.verify_delivery",
            lambda p, r, s, **kw: (seen.update(kw) or (True, "verify ok")))
        rc = entry.main([str(req_dir / "requirements.yaml"),
                         "-o", str(out), "--type", "web", "--mode", "auto"])
        assert rc == 0
        assert seen["requirements_dir"] == req_dir.resolve()
