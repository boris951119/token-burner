"""M11-3 模式智能推荐测试（确定性统计，无 LLM）。

规格：按历史项目（sessions/ 成功率与 token 成本）统计相似需求，
输出 {mode, budget_tokens, reason}；推荐理由引用数据；可覆盖。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.recommender import recommend
from app.server import create_app
from app.tools.file_manager import FileManager

REQ = "开发一个用户管理系统，支持注册登录与数据持久化"


def _make_history(
    root: Path,
    requirement: str,
    mode: str,
    *,
    completed: bool = True,
    tokens: int = 5000,
) -> None:
    """构造一个历史项目样本（需求文本 / 模式 / 成本 / 完成标记）。

    需求文本附加唯一标记：project_id 时间戳仅到秒，同秒两次创建会
    因目录同名冲突——标记不影响相似度词袋的主体构成。
    """
    marker = uuid.uuid4().hex[:6]
    fm = FileManager(projects_root=root)
    pid = fm.create_project(f"{requirement}（样本{marker}）").project_id
    proot = fm.get_project(pid).root
    (proot / "sessions" / "pipeline_state.json").write_text(
        json.dumps({"mode": mode, "order": ["user"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    if completed:
        (proot / "logs").mkdir(exist_ok=True)
        (proot / "logs" / "cost_report.json").write_text(
            json.dumps({"total_tokens": tokens}, ensure_ascii=False),
            encoding="utf-8",
        )
    else:
        (proot / "sessions" / "interruption.md").write_text(
            "# 中断现场\n", encoding="utf-8"
        )


class TestRecommend:
    def test_no_history_defaults_to_safe(self, tmp_path):
        r = recommend(REQ, tmp_path / "projects", Settings())
        assert r["mode"] == "safe"
        assert r["budget_tokens"] == Settings().task_token_budget("safe")
        assert r["history_size"] == 0
        assert "无相似历史项目" in r["reason"]

    def test_similar_history_prefers_successful_mode(self, tmp_path):
        root = tmp_path / "projects"
        _make_history(root, REQ, "safe", completed=True, tokens=4000)
        _make_history(root, REQ, "auto", completed=False)
        r = recommend(REQ, root, Settings())
        assert r["mode"] == "safe"
        assert r["history_size"] == 2
        assert "2 个相似历史项目" in r["reason"]
        assert "成功 1/1" in r["reason"]   # safe 模式口径：1 个样本成功 1 个
        # 预算 = 成功样本平均 4000 × 1.2 → 取整千位 4800 → 5000
        assert r["budget_tokens"] == 5000

    def test_higher_success_rate_mode_wins(self, tmp_path):
        root = tmp_path / "projects"
        _make_history(root, REQ, "safe", completed=False)
        _make_history(root, REQ, "auto", completed=True, tokens=8000)
        r = recommend(REQ, root, Settings())
        assert r["mode"] == "auto"
        assert r["budget_tokens"] == 10000   # 8000 × 1.2 → 9600 → 10000

    def test_tie_prefers_cheaper_avg(self, tmp_path):
        root = tmp_path / "projects"
        _make_history(root, REQ, "safe", completed=True, tokens=2000)
        _make_history(root, REQ, "auto", completed=True, tokens=9000)
        r = recommend(REQ, root, Settings())
        assert r["mode"] == "safe"

    def test_unrelated_requirement_falls_back_to_default(self, tmp_path):
        root = tmp_path / "projects"
        _make_history(root, REQ, "auto", completed=True, tokens=9000)
        r = recommend("machine learning model training pipeline", root, Settings())
        assert r["history_size"] == 0
        assert r["mode"] == "safe"


class TestRecommendApi:
    def test_recommend_endpoint(self, tmp_path):
        root = tmp_path / "projects"
        _make_history(root, REQ, "safe", completed=True, tokens=4000)
        app = create_app(
            settings=Settings(),
            projects_root=root,
            llm_factory=None,
            executor=None,
        )
        tc = TestClient(app)
        resp = tc.get("/api/recommend", params={"requirement": REQ})
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "safe"
        assert data["budget_tokens"] > 0
        assert "相似历史项目" in data["reason"]

    def test_recommend_endpoint_requires_requirement(self, tmp_path):
        app = create_app(
            settings=Settings(),
            projects_root=tmp_path / "projects",
            llm_factory=None,
            executor=None,
        )
        tc = TestClient(app)
        resp = tc.get("/api/recommend", params={"requirement": "  "})
        assert resp.status_code == 400


class TestClientRecommendContract:
    _ROOT = Path(__file__).resolve().parent.parent

    def test_client_renders_recommendation(self):
        html = (self._ROOT / "client.html").read_text(encoding="utf-8")
        assert "fillRecommend" in html
        assert "/api/recommend" in html
