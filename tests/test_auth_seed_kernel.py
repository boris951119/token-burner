# -*- coding: utf-8 -*-
"""auth_seed kernel + 种子登录探测闸回归（50d1f62e8860 官方 0/30 尸检）。

死链：官方登录场景用题面 pre-provisioned 账号（alice-dev）直接登录，而
生成代码把种子分裂在业务模块各自的 ensure_seed——登录入口只装了
nora-demo → 401 → 30 场景全灭。三层防线：
①抽取器：题面 pre-provisioned 反引号三元组 → [(u,e,p)]；
②kernel：题面账号确定性落盘 _shared/seed_accounts.py（只增不改，sheet 零行为）；
③探测闸：judge_requirements 起服后 POST 常见登录端点，401 判红进修复指令。
"""
from __future__ import annotations

from pathlib import Path

from app.utils.auth_seed_kernel import ensure_seed_accounts
from app.utils.seed_accounts import extract_seed_accounts

_GIVEN = '''
REQ-1-1-2:
  scenarios:
    - name: s1
      steps:
        - keyword: GIVEN
          content: 'The system has pre-provisioned a verified and available
            account with username `alice-dev`, email
            `alice.dev@example.test`, and password `Valid-password-123!`.'
'''


def test_extract_preprovisioned_accounts():
    accounts = extract_seed_accounts(_GIVEN)
    assert accounts == [("alice-dev", "alice.dev@example.test",
                         "Valid-password-123!")]


def test_extract_empty_for_sheet_style():
    assert extract_seed_accounts(
        'Seed data: note "Sprint goals" must be visible.') == []


def test_kernel_writes_seed_accounts_py(tmp_path):
    written = ensure_seed_accounts(tmp_path, _GIVEN)
    assert written == ["_shared/seed_accounts.py"]
    mod = tmp_path / "_shared" / "seed_accounts.py"
    src = mod.read_text(encoding="utf-8")
    assert "alice-dev" in src and "register_all" in src
    # 落盘代码可独立执行且幂等
    ns: dict = {}
    exec(compile(src, "seed_accounts", "exec"), ns)
    class _Store:
        users: dict = {}
        def register(self, u, e, p):
            self.users[u] = (e, p)
    store = _Store()
    assert ns["register_all"](store) == 1
    assert ns["register_all"](store) == 0, "幂等：二调零新增"


def test_kernel_noop_without_accounts(tmp_path):
    assert ensure_seed_accounts(tmp_path, "no seeds here") == []
    assert not (tmp_path / "_shared" / "seed_accounts.py").exists()


def test_kernel_author_file_kept_official_appended(tmp_path):
    shared = tmp_path / "_shared"
    shared.mkdir()
    (shared / "seed_accounts.py").write_text(
        "SEED_ACCOUNTS = []\n", encoding="utf-8")
    written = ensure_seed_accounts(tmp_path, _GIVEN)
    assert written == ["_shared/seed_accounts_official.py(官方清单追加)"]
    assert "alice-dev" in (shared / "seed_accounts_official.py").read_text(
        encoding="utf-8")


class _Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_seed_login_probe_flags_401(tmp_path, monkeypatch):
    import app.utils.acceptance_judge as aj

    (tmp_path / "requirements.yaml").write_text(_GIVEN, encoding="utf-8")
    out: dict = {"failures": [], "failed": 0, "total": 0}

    def fake_urlopen(req, timeout=6.0):
        # /api/auth/login 返回 401（模拟种子未装载）
        import urllib.error
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized",
                                     hdrs=None, fp=None)

    monkeypatch.setattr(aj.urllib.request, "urlopen", fake_urlopen)
    aj._seed_login_probe(tmp_path, "http://x", 1.0, out)
    assert out["failed"] == 1
    joined = "\n".join(out["failures"])
    assert "[seed]" in joined and "alice-dev" in joined
    assert "register_all" in joined


def test_seed_login_probe_silent_when_endpoint_absent(tmp_path, monkeypatch):
    import app.utils.acceptance_judge as aj

    (tmp_path / "requirements.yaml").write_text(_GIVEN, encoding="utf-8")
    out: dict = {"failures": [], "failed": 0, "total": 0}

    def fake_urlopen(req, timeout=6.0):
        import urllib.error
        raise urllib.error.HTTPError(req.full_url, 404, "NF", hdrs=None,
                                     fp=None)

    monkeypatch.setattr(aj.urllib.request, "urlopen", fake_urlopen)
    aj._seed_login_probe(tmp_path, "http://x", 1.0, out)
    assert out["failed"] == 0, "端点全 404=登录机制未知，射程外不判红"


def test_seed_login_probe_skips_sheet(tmp_path):
    import app.utils.acceptance_judge as aj

    (tmp_path / "requirements.yaml").write_text(
        'GIVEN: note "Sprint goals"\n', encoding="utf-8")
    out: dict = {"failures": [], "failed": 0, "total": 0}
    aj._seed_login_probe(tmp_path, "http://x", 1.0, out)
    assert out["failed"] == 0 and not out["failures"]
