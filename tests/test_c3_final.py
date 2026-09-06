"""C3 收官批测试:冻结原因透传 / 自定义交付目录名 / 根目录热切换。

依据:v1.1-workplan C3 用户追加项——
- 冻结原因前置展示:module_done 事件携带截尾 message,工作台直读;
- 交付目录可配置:POST /api/settings/projects-root 热切换 + 每任务
  自定义目录名(清洗+时间戳,缺省自动命名不变)。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.server import create_app
from app.tools.file_manager import FileManager


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        connections_path=str(tmp_path / "secrets.local.json"),
        projects_root=str(tmp_path / "projects"),
    )
    app = create_app(settings=settings)
    from app.utils import connections as conn_mod
    conn_mod.set_store(tmp_path / "secrets.local.json")
    with TestClient(app) as c:
        yield c, tmp_path


def _token(c):
    return c.get("/api/session").json()["token"]


class TestProjectDirname:
    def test_custom_dirname_sanitized(self, tmp_path):
        fm = FileManager(projects_root=tmp_path / "p")
        h = fm.create_project("随便什么需求", dirname="我的 项目<v1>")
        assert "我的_项目_v1" in h.root.name  # 非法字符清洗
        assert h.root.exists()

    def test_empty_dirname_falls_back_to_requirement(self, tmp_path):
        fm = FileManager(projects_root=tmp_path / "p")
        h = fm.create_project("开发用户系统", dirname="   ")
        assert "开发用户系统" in h.root.name

    def test_dirname_collision_gets_timestamp(self, tmp_path):
        fm = FileManager(projects_root=tmp_path / "p")
        h1 = fm.create_project("需求X", dirname="同名")
        h2 = fm.create_project("需求Y", dirname="同名")
        assert h1.root.name != h2.root.name  # 时间戳后缀保障唯一


class TestProjectsRootEndpoint:
    def test_switch_root_and_config_reflects(self, client, tmp_path):
        c, tmp = client
        new_root = tmp / "outputs"
        r = c.post("/api/settings/projects-root", headers={"X-Session-Token": _token(c)},
                   json={"new_root": str(new_root)})
        assert r.status_code == 200
        assert r.json()["projects_root"] == str(new_root)
        assert new_root.exists()
        assert c.get("/api/config").json()["projects_root"] == str(new_root)

    def test_requires_session_token(self, client, tmp_path):
        c, _ = client
        r = c.post("/api/settings/projects-root",
                   json={"new_root": str(tmp_path / "x")})
        assert r.status_code == 403

    def test_empty_path_400(self, client):
        c, _ = client
        r = c.post("/api/settings/projects-root",
                   headers={"X-Session-Token": _token(c)}, json={"new_root": ""})
        assert r.status_code == 422  # Pydantic min_length 拦截空串


class TestFreezeMessagePassthrough:
    def test_module_done_event_carries_message(self, tmp_path):
        """管线冻结模块时,module_done 事件携带截尾原因(工作台直读)。"""
        from tests.test_feedback_loop import (
            _AUTH_FIX, _RUN_KWARGS, _SIMPLE_FIX, _team_pipeline, ScriptedFeedback,
        )
        from tests.test_pipeline import team_scripts

        received = []
        scripts = team_scripts() + [_SIMPLE_FIX, _SIMPLE_FIX, _AUTH_FIX]
        settings = Settings(max_fix_rounds=1)
        fm = FileManager(projects_root=tmp_path / "p")
        pipeline = _team_pipeline(fm, scripts, ["SKIPPED"] * 9,
                                  settings=settings)
        pipeline._on_event = lambda kind, data: received.append((kind, dict(data)))
        feedback = ScriptedFeedback(["报错：NameError", "还是报错"])
        result = pipeline.run(feedback_fn=feedback, **_RUN_KWARGS)
        assert result.kind == "team_flow"
        done_events = [d for k, d in received if k == "module_done"]
        assert done_events, "应存在 module_done 事件"
        # v1.1 C3 后：所有 module_done 一律携带 message（工作台冻结展示的数据源）
        assert all("message" in d for d in done_events)
        # safe 模式：AWAITING_FEEDBACK 引导语非空；冻结态的原因摘要同样经此字段
        assert any(d.get("message") for d in done_events)
