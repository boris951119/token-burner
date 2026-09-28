"""刀 I：node_states 覆盖缺口闸（3 节点题面只报 2 → 红且名单精确）。"""

from __future__ import annotations

from app.agents.module_builder import ModulePlan
from app.utils.coverage_gap import (
    audit_node_states_gap,
    enforce_node_states_gap,
)


_REQ = """
## 模块：ui_home
### REQ-1-1-1 首页入口
描述：首页显示 "Create an account" 链接。
- 场景：进首页
  - GIVEN: 用户打开首页
  - WHEN: 用户看到 "Create an account"
  - THEN: 页面含 "Create an account"

### REQ-1-2-1 注册表单
描述：注册页有 "Username" 与 "Email"。
- 场景：打开注册
  - GIVEN: 用户在注册页
  - WHEN: 用户查看表单
  - THEN: 可见 "Username"

### REQ-2-1-1 仓库列表
描述：列表显示 "Repositories"。
- 场景：进列表
  - GIVEN: 用户已登录
  - WHEN: 打开仓库列表
  - THEN: 可见 "Repositories"
"""


class _FakeTrace:
    def __init__(self):
        self.reqs: list[str] = []

    def upsert_requirement(self, **kwargs):
        self.reqs.append(kwargs["req_id"])

    def list_node_states(self):
        return []


def test_audit_gap_exact_missing_one():
    """3 节点只报 2 → missing 精确为未报那一个。"""
    reported = ["REQ-1-1-1", "REQ-1-2-1"]
    rep = audit_node_states_gap(_REQ, reported)
    assert rep.ok is False
    assert set(rep.required) == {
        "REQ-1-1-1", "REQ-1-2-1", "REQ-2-1-1",
    }
    assert rep.missing == ["REQ-2-1-1"]


def test_enforce_gap_logs_injects_and_registers(tmp_path, capsys):
    """缺口红日志 + 清单注入最像模块 + requirements 补登记。"""
    plans = [
        ModulePlan(
            name="ui_home",
            responsibility="首页与注册 UI",
            dependencies=[],
            priority=1,
        ),
        ModulePlan(
            name="repo_list",
            responsibility="仓库列表 Repositories",
            dependencies=[],
            priority=2,
        ),
    ]
    fake = _FakeTrace()
    rep = enforce_node_states_gap(
        _REQ,
        plans,
        reported_ids=["REQ-1-1-1", "REQ-1-2-1"],
        project_root=tmp_path,
        traceability=fake,
        skip_if_no_sdk=False,
    )
    assert rep.missing == ["REQ-2-1-1"]
    out = capsys.readouterr().out
    assert "[coverage-gap]" in out
    assert "REQ-2-1-1" in out
    assert "缺 1 个节点上报" in out
    # v53.1 刀G 同口径：REQ-2-1-1 是 UI 流程（含控件锚点），补挂优先
    # 落在 ui/page/web/view 模块（ui_home 职责"首页与注册 UI"命中）
    assert rep.injected.get("REQ-2-1-1") == "ui_home"
    assert "REQ-2-1-1" in fake.reqs
    # 模块 md 已落盘且含逐字清单痕迹
    md = (tmp_path / "modules" / "repo_list.md").read_text(encoding="utf-8")
    assert "REQ-2-1-1" in md or "Repositories" in md or "验收" in md


def test_no_gap_when_all_reported():
    rep = audit_node_states_gap(
        _REQ, ["REQ-1-1-1", "REQ-1-2-1", "REQ-2-1-1"],
    )
    assert rep.ok is True
    assert rep.missing == []
