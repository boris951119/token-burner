"""批次#58B：运行墙钟 + 终止信号接管（48h 硬杀不再等于 0 分）。

判分口径 avg_pass_rate、exit 1 = 不评分，所以「跑一半被打断」的正确终局
不是失败而是**按现状导出**。本文件锁住三段链条：
①墙钟起表（env 口径与脏值兜底）、②护栏在收尾窗口前主动收手（抛
TaskDeadlineError，且它是 TaskCancelledError 的子类 ⇒ 老的中止处理照旧
接得住）、③终止信号变出来的 KeyboardInterrupt 确实走到尽力交付。
"""

from __future__ import annotations

import inspect
import os
import signal
import time

import pytest

import main as entry
from app.config import Settings
from app.utils import budget as bg

_TREE = """\
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


@pytest.fixture
def req_dir(tmp_path):
    d = tmp_path / "requirements"
    d.mkdir()
    (d / "requirements.yaml").write_text(_TREE, encoding="utf-8")
    return d


def _env(monkeypatch, out_dir):
    monkeypatch.setenv("OPENAI_API_KEY", "ak_test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gw.test/v1")
    monkeypatch.setenv("MODEL", "glm-5.3")
    monkeypatch.delenv("ARCBENCH_OUTPUT_DIR", raising=False)


@pytest.fixture(autouse=True)
def _isolate_deadline():
    """模块级墙钟是全局态：进出各清一次，防跨文件污染。"""
    bg.clear_task_deadline()
    saved = {n: os.environ.get(n) for n in bg.TASK_TIME_ENV}
    for name in bg.TASK_TIME_ENV:
        os.environ.pop(name, None)
    yield
    bg.clear_task_deadline()
    for name, val in saved.items():
        if val is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = val


class TestArmTable:
    def test_default_is_48h_and_not_immediately_urgent(self):
        assert bg.arm_task_deadline() == 48 * 3600
        assert bg.task_seconds_remaining() == pytest.approx(48 * 3600, abs=5)
        assert bg.wind_down_pending() is False

    def test_env_var_wins_and_names_itself_in_the_brief(self, monkeypatch):
        monkeypatch.setenv("TASK_MAX_SECONDS", "3600")
        assert bg.arm_task_deadline() == 3600
        assert "TASK_MAX_SECONDS" in bg.deadline_brief()

    def test_first_env_in_order_wins(self, monkeypatch):
        monkeypatch.setenv("TASK_MAX_SECONDS", "3600")
        monkeypatch.setenv("TASK_TIMEOUT_SECONDS", "60")
        assert bg.arm_task_deadline() == 3600

    @pytest.mark.parametrize("dirty", ["48h", "", "   ", "-30", "0", "nan"])
    def test_dirty_env_falls_back_to_default_not_crash(self, monkeypatch, dirty):
        """起表在管线之前：一道保命闸不该成为最早的死因。"""
        monkeypatch.setenv("TASK_MAX_SECONDS", dirty)
        assert bg.arm_task_deadline() == 48 * 3600

    def test_dirty_explicit_argument_same_fallback(self):
        assert bg.arm_task_deadline("35min") == 48 * 3600
        assert bg.arm_task_deadline(None) == 48 * 3600
        assert bg.arm_task_deadline(-1) == 48 * 3600

    def test_rearm_replaces_previous_table(self):
        bg.arm_task_deadline(3600)
        assert bg.arm_task_deadline(7200) == 7200
        assert bg.task_seconds_remaining() == pytest.approx(7200, abs=5)

    def test_remaining_goes_negative_past_the_deadline(self):
        """过点如实报负：报假「还早」比报假「来不及」危险得多。"""
        bg.arm_task_deadline(3600)
        assert bg.task_seconds_remaining(now=time.monotonic() + 7200) == pytest.approx(
            -3600, abs=5)

    def test_unarmed_means_no_time_gate_anywhere(self):
        assert bg.task_deadline_armed() is False
        assert bg.task_seconds_remaining() is None
        assert bg.wind_down_pending() is False


class TestWindDownGate:
    def test_guard_stops_new_calls_inside_the_window(self):
        bg.arm_task_deadline(bg.DEFAULT_WIND_DOWN_SECONDS - 60)
        guard = bg.BudgetGuard(1_000_000)
        assert guard.wind_down_pending is True
        with pytest.raises(bg.TaskDeadlineError) as ei:
            guard.ensure_allowed()
        assert "按现状交付" in str(ei.value)

    def test_wind_down_sized_to_the_inflight_call_tail(self):
        """窗口必须盖住「已发出去的那次调用」的最坏尾巴（600s 墙钟 ×3 腿）：
        小于它等于收手指令下达时我已经出局。"""
        assert bg.DEFAULT_WIND_DOWN_SECONDS >= 3 * 600

    def test_outside_the_window_budget_still_rules(self):
        bg.arm_task_deadline(bg.DEFAULT_WIND_DOWN_SECONDS + 600)
        guard = bg.BudgetGuard(1_000_000)
        guard.record(999_999)
        assert guard.wind_down_pending is False
        guard.ensure_allowed()          # 还剩时间也还没花完 → 放行
        guard.record(2)
        with pytest.raises(bg.BudgetExceededError):
            guard.ensure_allowed()

    def test_deadline_error_is_a_cancel_error_for_old_handlers(self):
        """任何只认 TaskCancelledError 的既有中止分支都必须继续认它。"""
        assert issubclass(bg.TaskDeadlineError, bg.TaskCancelledError)

    def test_cancel_flag_still_wins_over_the_clock(self):
        bg.arm_task_deadline(1)
        guard = bg.BudgetGuard(1_000_000)
        guard.attach_cancel_check(lambda: True)
        with pytest.raises(bg.TaskCancelledError) as ei:
            guard.ensure_allowed()
        assert not isinstance(ei.value, bg.TaskDeadlineError)


class TestSignalTakeover:
    def test_handler_raises_keyboardinterrupt(self):
        with pytest.raises(KeyboardInterrupt) as ei:
            entry._termination_handler(signal.SIGTERM, None)
        assert "SIGTERM" in str(ei.value)

    def test_handler_yields_during_export_write(self, capsys):
        """导出是先清后写：正清完就被斩交出去的目录比不交还糟。"""
        entry._export_busy = True
        try:
            assert entry._termination_handler(signal.SIGTERM, None) is None
        finally:
            entry._export_busy = False
        assert "让路" in capsys.readouterr().out

    @pytest.mark.skipif(not hasattr(signal, "SIGTERM"), reason="无 SIGTERM")
    def test_installed_handler_actually_fires_on_real_signal(self):
        """端到端：真给自己发一个 SIGTERM，必须变成 KeyboardInterrupt。"""
        saved = signal.getsignal(signal.SIGTERM)
        assert "SIGTERM" in entry._install_death_signals()
        try:
            with pytest.raises(KeyboardInterrupt):
                os.kill(os.getpid(), signal.SIGTERM)
                time.sleep(0.2)  # 让信号在主线程边界上落地
        finally:
            signal.signal(signal.SIGTERM, saved)

    def test_install_never_raises_when_platform_lacks_a_signal(self, monkeypatch):
        monkeypatch.setattr(signal, "SIGTERM", None, raising=False)
        assert isinstance(entry._install_death_signals(), str)


class TestEntrySurvival:
    """入口链条：终止信号 → 尽力交付 → 退出码 0（换取一次评分机会）。"""

    def _patch_boom(self, monkeypatch, out, exc, proj_with_code=True):
        monkeypatch.setattr(
            entry, "load_settings",
            lambda config_file=None, **kw: Settings(models=["openai/glm-5.3"]))
        monkeypatch.setattr(entry, "_gateway_preflight", lambda settings: None)
        if proj_with_code:
            proj = out / "projects" / "arcbench-app_kill"
            (proj / "code" / "notes").mkdir(parents=True)
            (proj / "code" / "notes" / "notes.py").write_text(
                "x = 1\n", encoding="utf-8")

        class _Boom:
            def __init__(self, **kwargs):
                pass

            def run(self, *args, **kwargs):
                raise exc

        monkeypatch.setattr(entry, "Pipeline", _Boom)
        called = []
        monkeypatch.setattr(
            "app.platform_export.export_platform_layout",
            lambda workdir, pd, **_k: (called.append(str(pd))
                                 or {"backend_files": 1, "frontend_files": 0}))
        return called

    def test_keyboard_interrupt_salvages_and_scores(
            self, monkeypatch, tmp_path, req_dir):
        """用户定的成功判据：跑一半被 kill，导出目录里仍是一次可评分交付。"""
        out = tmp_path / "ws-kill"
        _env(monkeypatch, out)
        called = self._patch_boom(
            monkeypatch, out, KeyboardInterrupt("收到终止信号 SIGTERM"))
        assert entry.main([str(req_dir), "-o", str(out), "--mode", "auto"]) == 0
        assert called, "被中断也必须走兜底导出"

    def test_deadline_error_salvages_too(self, monkeypatch, tmp_path, req_dir):
        """墙钟收手抛的是异常子类：即使从未经过管线的中止分支，出口也得接住。"""
        out = tmp_path / "ws-deadline"
        _env(monkeypatch, out)
        bg.arm_task_deadline(60)
        called = self._patch_boom(
            monkeypatch, out, bg.TaskDeadlineError("运行墙钟见底"))
        assert entry.main([str(req_dir), "-o", str(out), "--mode", "auto"]) == 0
        assert called

    def test_emergency_salvage_ships_when_code_exists(self, monkeypatch, tmp_path):
        out = tmp_path / "ws-emu"
        proj = out / "projects" / "arcbench-app_x"
        (proj / "code" / "m").mkdir(parents=True)
        (proj / "code" / "m" / "m.py").write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(entry, "_SALVAGE_WORKDIR", out)
        monkeypatch.setattr(
            "app.platform_export.export_platform_layout",
            lambda workdir, pd, **_k: {"backend_files": 1, "frontend_files": 0})
        assert entry._emergency_salvage("测试") == 0

    def test_emergency_salvage_falls_to_honest_skeleton(
            self, monkeypatch, tmp_path):
        """批次#63B（用户拍板"交"）：盘上什么都没有也要换一次运行记录。

        官方 exit 1 = 不评分，而规则要求两个任务都有运行记录才有排名 ⇒
        「一次接近 0 的分」严格优于「那道题没有记录」。工作区完全无法解析的
        那一档仍然照实返回 1——骨架也不知道往哪写，不假装成功。
        """
        monkeypatch.delenv("ARCBENCH_OUTPUT_DIR", raising=False)
        monkeypatch.setattr(entry, "_SALVAGE_WORKDIR", None)
        assert entry._emergency_salvage("测试") == 1     # 工作区未知
        empty = tmp_path / "nope"
        monkeypatch.setattr(entry, "_SALVAGE_WORKDIR", empty)
        assert entry._emergency_salvage("测试") == 0     # 骨架换记录
        backend = empty / "backend"
        assert (backend / "main.py").is_file()
        assert "def create_app" not in (backend / "main.py").read_text(
            encoding="utf-8")
        assert (backend / "ARCBENCH_SKELETON.txt").is_file(), \
            "骨架必须自带尸检标记：分不清「产物活着」与「靠骨架活着」就是自欺"

    def test_skeleton_never_overwrites_a_real_delivery(self, tmp_path):
        from app.platform_export import export_skeleton_layout

        out = tmp_path / "ws"
        (out / "backend").mkdir(parents=True)
        (out / "backend" / "app.py").write_text("x = 1\n", encoding="utf-8")
        assert export_skeleton_layout(out, "不该覆盖真产物") is False
        assert (out / "backend" / "app.py").is_file(), "真产物被骨架抹掉了"
        assert not (out / "backend" / "main.py").exists()

    def test_emergency_salvage_reads_env_when_workdir_unparsed(
            self, monkeypatch, tmp_path):
        out = tmp_path / "ws-emu2"
        proj = out / "projects" / "arcbench-app_y"
        (proj / "code" / "m").mkdir(parents=True)
        (proj / "code" / "m" / "m.py").write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(entry, "_SALVAGE_WORKDIR", None)
        monkeypatch.setenv("ARCBENCH_OUTPUT_DIR", str(out))
        monkeypatch.setattr(
            "app.platform_export.export_platform_layout",
            lambda workdir, pd, **_k: {"backend_files": 1, "frontend_files": 0})
        assert entry._emergency_salvage("测试") == 0


class TestWiringStillThere:
    """防回归（本批次就踩过一次）：接管与兜底的接线不能被无声删掉。"""

    def test_pipeline_dispatches_deadline_to_the_interruption_exit(self):
        src = inspect.getsource(entry.Pipeline.run)
        assert "TaskDeadlineError" in src
        resume = inspect.getsource(entry.Pipeline.resume)
        assert "TaskDeadlineError" in resume

    def test_entry_catches_keyboardinterrupt_at_the_pipeline(self):
        src = inspect.getsource(entry.main)
        assert "except (Exception, KeyboardInterrupt)" in src

    def test_salvage_export_called_once_in_the_crash_branch(self):
        """重复块取证：兜底导出曾在同一个 except 里写了两遍（第二遍永不执行）。

        口径是「每个出口分支各一次」而不是「全函数一次」——看门狗分支
        也需要同样的兜底（os._exit 之前那唯一一次机会）。
        """
        src = inspect.getsource(entry.main)
        crash = src[src.index("except (Exception, KeyboardInterrupt)")
                    :src.index("if result.kind in _SUCCESS_KINDS")]
        assert crash.count("_salvage_export(workdir)") == 1
        assert src.count("_salvage_export(workdir)") == 2   # 崩溃分支 + 看门狗

    def test_watchdog_exports_before_it_hard_exits(self):
        """os._exit 跳过所有清理：兜底导出必须写在它前面（楔死那路唯一出口）。

        线程内 os._exit 的运行测试会把 pytest 进程一起带走，故只钉接线顺序。
        """
        src = inspect.getsource(entry.main)
        seg = src[src.index("def _watchdog"):
                  src.index("threading.Thread(target=_watchdog")]
        assert "_salvage_export(workdir)" in seg
        assert seg.index("_salvage_export") < seg.index("os._exit(75)")
