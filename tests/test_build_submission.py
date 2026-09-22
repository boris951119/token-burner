# -*- coding: utf-8 -*-
"""提交包构建器：白名单形状 + 合规硬断言（手工攒包时代的收官测试）。

取证（2026-09-23）：v8 包靠手工攒出、仓库无打包脚本；首次脚本化时静默
丢 45 文件（skills/ 与 template/ 只在官方 Blank Template 里）。故本文件的
重点是「缩水必须响」与「禁令命中文件名 *和* 内容」。
"""
from __future__ import annotations

import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "build_submission",
    Path(__file__).resolve().parents[1] / "scripts" / "build_submission.py")
bs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bs)


def _mkzip(path: Path, members: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in members.items():
            zf.writestr(name, body)
    return path


# ---- 禁令表：顶层目录前缀 vs 任意位置子串 ----

@pytest.mark.parametrize("rel,denied", [
    ("release/token-burner.exe", True),        # 顶层产物目录
    ("projects/x/spec.md", True),
    ("logs/run.jsonl", True),
    ("app/utils/__pycache__/x.pyc", True),     # 任意位置子串
    ("arc-bench-repo/README.md", True),        # 合规红线
    ("app/.env", True),
    ("examples/logscan/tests/test_x.py", False),   # 随 example 交付的嵌套 tests
    ("examples/logscan/code/.env.example", False),
    ("app/pipeline.py", False),
    ("template/backend/main.py", False),
])
def test_denied_rules(rel, denied):
    got = bs._denied(rel)
    assert bool(got) is denied, f"{rel} → {got}"


def _fake_tree(root: Path) -> None:
    (root / "app").mkdir(parents=True)
    (root / "app" / "pipeline.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "app" / "new_module.py").write_text("x = 1\n", encoding="utf-8")
    (root / "main.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (root / "release").mkdir()
    (root / "release" / "token-burner.exe").write_bytes(b"MZ")


def test_build_shape_drop_is_fatal_until_allowed(tmp_path, capsys):
    tree = tmp_path / "repo"
    _fake_tree(tree)
    base = _mkzip(tmp_path / "v0.zip", {
        "app/pipeline.py": "old\n",
        "app/gone_module.py": "已在工作树删除\n",
        "template/backend/main.py": "print('模板')\n",   # 只存在于 Blank
    })
    blank = _mkzip(tmp_path / "blank.zip", {
        "template/backend/main.py": "print('模板')\n",
        "skills/write_code/SKILL.md": "# skill\n",
        "release/injected.exe": "MZ",                    # 模板也得过禁令
    })
    out = tmp_path / "out.zip"
    monkey = pytest.MonkeyPatch()
    monkey.setattr(bs, "ROOT", tree)
    try:
        rc = bs.build(out, base, blank)
    finally:
        monkey.undo()
    names = [n for n in zipfile.ZipFile(out).namelist() if not n.endswith("/")]
    assert rc == 1                                   # 静默缩水必须响
    assert "app/gone_module.py" in capsys.readouterr().out
    assert set(names) == {"app/pipeline.py", "app/new_module.py", "main.py",
                          "template/backend/main.py", "skills/write_code/SKILL.md"}
    assert "release/injected.exe" not in names       # Blank 侧同样过滤
    monkey2 = pytest.MonkeyPatch()
    monkey2.setattr(bs, "ROOT", tree)
    try:
        assert bs.build(out, base, blank, allow_drop=True) == 0
    finally:
        monkey2.undo()


def test_build_flags_real_secret_in_body(tmp_path, capsys):
    tree = tmp_path / "repo"
    _fake_tree(tree)
    (tree / "app" / "leak.py").write_text(
        'OPENAI_API_KEY = "sk-abcdef0123456789abcd"\n', encoding="utf-8")
    base = _mkzip(tmp_path / "v0.zip", {"app/pipeline.py": "x\n"})
    out = tmp_path / "out.zip"
    monkey = pytest.MonkeyPatch()
    monkey.setattr(bs, "ROOT", tree)
    try:
        rc = bs.build(out, base, tmp_path / "missing.zip")
    finally:
        monkey.undo()
    assert rc == 1
    assert "疑似真实密钥" in capsys.readouterr().out


@pytest.mark.parametrize("body", [
    'API_KEY = "your-api-key-here"',
    'export OPENAI_API_KEY="${OPENAI_API_KEY}"',
    '# 示例：<sk-xxxxxxxxxxxx>',
    "password = os.environ['PGPASSWORD']\n",
    '"api_key": mask_key(conn.get("api_key", "")),\n',   # 代码引用非密钥
    "def f(api_key=None):\n    return api_key\n",
])
def test_placeholders_are_not_leaks(tmp_path, body):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("app/x.py", body)
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
        assert bs._content_leaks(zf) == []


def test_official_task_material_in_body_is_flagged():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("app/notes.md", "抄自 https://github.com/code-philia/x")
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zf:
        assert any("官方素材" in m for m in bs._content_leaks(zf))
