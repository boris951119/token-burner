"""心跳落盘测试（factory26 r4：headless 长跑可观测性）。

锚点：项目目录就绪后 sessions/heartbeat.json 随事件刷新——
时间戳 + 当前阶段 + 最近事件 + 模块；事件回调失败不影响任务。
"""

from __future__ import annotations

import json

from tests.test_feedback_loop import _RUN_KWARGS, ScriptedFeedback, _team_pipeline
from tests.test_pipeline import team_scripts


def test_heartbeat_written_and_refreshed(tmp_path):
    from app.tools.file_manager import FileManager

    fm = FileManager(projects_root=tmp_path / "p")
    pipeline = _team_pipeline(fm, team_scripts(), ["SKIPPED"] * 3)
    feedback = ScriptedFeedback(["运行成功，输出符合预期"])
    result = pipeline.run(feedback_fn=feedback, **_RUN_KWARGS)
    assert result.kind == "team_flow"

    project_dir = fm.get_project(result.project_id).root
    hb = project_dir / "sessions" / "heartbeat.json"
    assert hb.is_file()
    payload = json.loads(hb.read_text(encoding="utf-8"))
    # 安全模式收尾是「反馈修复」stage 事件；断言链路活着即可
    assert payload["last_event"] in ("module_done", "stage")
    assert payload["timestamp"]
    assert payload["stage"]


def test_heartbeat_absent_before_project(tmp_path):
    """项目创建前（评估阶段）无心跳落点，事件静默跳过——不炸。"""
    from app.tools.file_manager import FileManager

    fm = FileManager(projects_root=tmp_path / "p")
    pipeline = _team_pipeline(fm, team_scripts(), ["SKIPPED"] * 3)
    pipeline._beat("stage", {"stage": "评估"})  # 不应抛异常
    assert not (tmp_path / "p" / "sessions" / "heartbeat.json").exists()
