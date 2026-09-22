# -*- coding: utf-8 -*-
"""节点级自测 specs 生成（9/22 keep-r0 取证：单次全量调用一烧即整闸报废）。"""
import json

import pytest

from app.utils import selftest_gate as sg

_REQ_TEXT = "\n".join([
    "开发一个完整可运行的 Web 应用：Demo。",
    "技术栈硬性要求：真实 HTTP 服务器。",
    "",
    "## 模块：M1 Notes",
    "依赖：无",
    "笔记管理模块。",
    "### REQ-1.1 Create（验收标准）",
    'Given home page, When click "Take a note", Then "Sprint goals" visible',
    "### REQ-1.2 List（验收标准）",
    'Given home page, Then "Groceries" visible',
    "",
    "## 模块：M2 Search",
    "依赖：M1",
    "搜索模块。",
    "### REQ-2.1 Search（验收标准）",
    'When type "Search" then results',
    "### REQ-2.2 Highlight（验收标准）",
    'Then "1 result" visible',
    "",
    "## 种子数据与测试夹具契约",
    '种子必须含精确字符串 "Sprint goals" 与 "Groceries"。',
    "",
    "共 2 个功能模块、4 条原子验收需求。",
])

_ALL_IDS = ("REQ-1.1", "REQ-1.2", "REQ-2.1", "REQ-2.2")


def _spec_payload(req_ids):
    tests = [{
        "req_id": rid,
        "name": f"t{rid}",
        "code": ("import { test, expect } from '@playwright/test';\n"
                 f"test('{rid} ok', async ({{ page }}) => {{ "
                 "await page.goto('/'); });"),
    } for rid in req_ids]
    return json.dumps({"tests": tests}, ensure_ascii=False)


class _Resp:
    def __init__(self, content):
        self.content = content


class FakeClient:
    """按 prompt 中出现的 REQ id 认批；fail_ids 命中的批前 fail_rounds
    次调用全灭（模拟腿接力也救不了的瞬断窗口）。"""

    def __init__(self, settings, fail_ids=(), fail_rounds=1):
        self.calls = []
        self._attempt = {}
        self.fail_ids = set(fail_ids)
        self.fail_rounds = fail_rounds

    def chat(self, model, messages):
        user = messages[-1]["content"]
        ids = tuple(t for t in _ALL_IDS if f"### {t}" in user)
        self.calls.append(ids)
        key = ids
        n = self._attempt[key] = self._attempt.get(key, 0) + 1
        if self.fail_ids & set(ids) and n <= self.fail_rounds:
            raise RuntimeError("LLM 调用失败: RateLimitError - quota exceeded")
        return _Resp(_spec_payload(ids or ["REQ-X"]))


class _Settings:
    models = ("openai/fake-a", "openai/fake-b")


@pytest.fixture
def gate(tmp_path, monkeypatch):
    monkeypatch.setattr(sg, "lint_specs", lambda *a, **k: 0)
    monkeypatch.setattr(sg, "_NODE_BATCH_MAX", 2)  # 4 节点 → 2 批
    return tmp_path


def _patch_client(monkeypatch, **kw):
    import app.utils.model_client as mcm
    holder = {}

    def factory(settings):
        holder["c"] = FakeClient(settings, **kw)
        return holder["c"]

    monkeypatch.setattr(mcm, "ModelClient", factory)
    return holder


def test_split_atomic_nodes_ids_and_context():
    nodes, gctx = sg._split_atomic_nodes(_REQ_TEXT)
    assert [nid for nid, _ in nodes] == list(_ALL_IDS)
    by_id = dict(nodes)
    assert by_id["REQ-1.2"].startswith("## 模块：M1 Notes")
    assert "笔记管理模块" in by_id["REQ-1.2"]
    assert by_id["REQ-2.1"].startswith("## 模块：M2 Search")
    assert "种子数据与测试夹具契约" in gctx
    assert "Sprint goals" in gctx


def test_batch_nodes_limits(monkeypatch):
    monkeypatch.setattr(sg, "_NODE_BATCH_MAX", 8)
    many = [(f"REQ-{i}", "x" * 900) for i in range(25)]
    batches = sg._batch_nodes(many)
    assert all(len(b) <= 8 for b in batches)
    assert sum(len(b) for b in batches) == 25
    huge = [("REQ-A", "y" * (sg._NODE_BATCH_CHARS + 100)), ("REQ-B", "z")]
    bs = sg._batch_nodes(huge)
    assert len(bs[0]) == 1  # 超大节点不截断、不与他节点合批


def test_batch_failure_retried_others_survive(gate, monkeypatch):
    holder = _patch_client(monkeypatch, fail_ids=["REQ-2.1"], fail_rounds=2)
    specs = sg.ensure_selftests(gate, _REQ_TEXT, _Settings())
    assert specs is not None
    names = {f.name for f in specs.glob("*.spec.ts")}
    assert any(n.startswith("REQ-1.1") for n in names)
    assert any(n.startswith("REQ-2.2") for n in names)
    # 失败批：首轮两腿全灭（attempt 1、2），收尾节点级重试轮成功（attempt 3）
    assert holder["c"]._attempt[("REQ-2.1", "REQ-2.2")] >= 3


def test_permanent_node_failure_partial_delivery(gate, monkeypatch):
    _patch_client(monkeypatch, fail_ids=["REQ-2.2"], fail_rounds=99)
    specs = sg.ensure_selftests(gate, _REQ_TEXT, _Settings())
    assert specs is not None  # 部分覆盖 > 零覆盖，整闸不报废
    names = {f.name for f in specs.glob("*.spec.ts")}
    assert not any(n.startswith("REQ-2.2") for n in names)
    assert any(n.startswith("REQ-1.1") for n in names)


def test_resume_skips_covered_nodes(gate, monkeypatch):
    _patch_client(monkeypatch)
    specs = sg.ensure_selftests(gate, _REQ_TEXT, _Settings())
    assert specs is not None
    first = sorted(f.name for f in specs.glob("*.spec.ts"))
    holder = _patch_client(monkeypatch)  # 新 fake：再进不应有任何调用
    specs2 = sg.ensure_selftests(gate, _REQ_TEXT, _Settings())
    assert specs2 == specs
    # 全节点已覆盖：早退路径，连 ModelClient 都不实例化（零 LLM 调用）
    assert holder.get("c") is None or holder["c"].calls == []
    assert sorted(f.name for f in specs2.glob("*.spec.ts")) == first


def test_no_structure_falls_back_single_shot(gate, monkeypatch):
    import app.utils.model_client as mcm
    holder = {}
    monkeypatch.setattr(mcm, "ModelClient",
                        lambda s: holder.setdefault("c", FakeClient(s)))
    specs = sg.ensure_selftests(gate, "纯文本题面，无 ### 结构。", _Settings())
    assert specs is not None
    assert len(holder["c"].calls) == 1
    assert any(f.name.startswith("REQ-X") for f in specs.glob("*.spec.ts"))


def test_all_batches_dead_returns_none(gate, monkeypatch):
    _patch_client(monkeypatch, fail_ids=list(_ALL_IDS), fail_rounds=99)
    assert sg.ensure_selftests(gate, _REQ_TEXT, _Settings()) is None


class TestGenSystemLocatorPolicy:
    """9/23 官方 helpers 取证：修复环优化的必须是可访问性通道。

    自测 specs 一旦用 CSS/testid 定位，修复轮就会把实现往「测试能过、
    评测看不见」的方向推——keep#3 的 1 passed/31 unexpected 形状。
    """

    def test_aria_channels_mandatory(self):
        for ch in ("getByRole", "getByLabel", "getByPlaceholder",
                   "'button'", "'link'", "'textbox'", "'searchbox'",
                   "'menuitem'", "'dialog'", "'status'", "'alert'"):
            assert ch in sg._GEN_SYSTEM, ch

    def test_non_aria_locators_banned(self):
        assert "data-testid" in sg._GEN_SYSTEM
        assert "禁止" in sg._GEN_SYSTEM and "locator('css')" in sg._GEN_SYSTEM
        # getByText 只留给非交互结果文本，不得用来点按钮
        assert "不得用它点按钮" in sg._GEN_SYSTEM

    def test_feedback_assertion_not_stricter_than_official(self):
        """官方 expectSuccessFeedback 是 alert→status→结果文本兜底；
        自测若只认实况区，会把官方能过的实现判红、白烧修复轮。"""
        i, j = (sg._GEN_SYSTEM.index(s) for s in ("4c. 操作反馈", "4d."))
        seg = sg._GEN_SYSTEM[i:j]
        assert "'alert'" in seg and "'status'" in seg
        assert "getByText" in seg and ".or()" in seg

    def test_landmark_roles_contracted(self):
        """官方 openTrash 之流按 getByRole('complementary') 硬取侧栏，
        没有文本兜底——需求点名的区域必须落到地标角色。"""
        for r in ("'complementary'", "'navigation'", "'article'"):
            assert r in sg._GEN_SYSTEM, r

    def test_fill_channel_matches_official_helpers(self):
        """官方 fillField 无 getByText 通道：输入框必须 label/placeholder 可达。"""
        i, j = (sg._GEN_SYSTEM.index(s) for s in ("4b. 填输入框", "4c."))
        seg = sg._GEN_SYSTEM[i:j]
        for ch in ("getByLabel", "getByPlaceholder", "'textbox'", "'searchbox'"):
            assert ch in seg, ch

    def test_prompt_carries_no_official_task_names(self):
        """合规红线：随包提示词不得含官方专名/原文文案。"""
        low = sg._GEN_SYSTEM.lower()
        for w in ("bookstack", "keep", "stackoverflow", "take a note",
                  "arc-bench", "agentic-requirement-compiler"):
            assert w not in low, w


class TestSpecRunWallClock:
    """一轮自测的墙钟预算直接决定修复环能跑几轮（9/23 实测 16 分钟/轮）。"""

    def test_action_timeout_is_set_for_selftest_runs(self, tmp_path):
        env = sg._spec_env(tmp_path, 3399, tmp_path / "tests" / "selftest")
        assert env["PLAYWRIGHT_ACTION_TIMEOUT"] == str(sg.SPEC_ACTION_TIMEOUT_MS)
        assert 0 < sg.SPEC_ACTION_TIMEOUT_MS < 60000
        assert env["TARGET_URL"].endswith(":3399")
        assert env["GRADE_REPORT"].endswith("selftest-report.json")

    def test_config_actually_reads_the_knob(self):
        """环境变量名一改，config 里的读取就静默失效——只有真跑才看得出来，
        故把名字一致性钉成静态断言。"""
        cfg = (sg.GRADE_DIR / "playwright.config.ts").read_text(encoding="utf-8")
        assert "PLAYWRIGHT_ACTION_TIMEOUT" in cfg
        assert "actionTimeout" in cfg
        # 官方判分复现不设该变量：默认 0 = 沿用 test 超时，口径不变
        assert "process.env.PLAYWRIGHT_ACTION_TIMEOUT || 0" in cfg
