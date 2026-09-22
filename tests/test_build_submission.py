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


# ---- 解释器天花板：包里跑的容器只有 python:3.11-slim ---------------------
# 开发机是 3.12、容器是 3.11。产品代码里出现 3.12 才有的语法或标准库符号，
# 导入期即崩——那是整跑 exit 1（不评分），下游任何验收闸都救不回来。
# 9/23 实测口径：ast 的 feature_version 能挡 PEP 695（type 语句/泛型参数
# 列表），但挡不住 PEP 701 的 f-string 放宽；新增符号因此走 AST 属性/导入
# 判定——按文本判会把提示词里的禁令本身误当代码（第一版就是这么炸的）。

_FROM_312 = {                       # from <mod> import <name>
    "itertools": {"batched"},
    "datetime": {"UTC"},
    "typing": {"override"},
}
_ATTR_312 = {                       # <mod>.<attr>
    "itertools": {"batched"},
    "datetime": {"UTC"},
    "sys": {"monitoring"},
    "typing": {"override"},
    "pathlib": {"Path"},
}
_PATH_NAMES = {"Path", "PurePath", "pathlib"}


def _py312_hits(src: str) -> list[str]:
    """只认代码结构：字符串与注释里的同名词不算（题面提示词自带禁令）。"""
    import ast

    hits: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return hits                     # 语法段由 feature_version 检查负责
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            for a in node.names:
                if a.name in _FROM_312.get(mod, set()):
                    hits.append(f"from {mod} import {a.name}")
        elif isinstance(node, ast.Attribute):
            base = node.value
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Call):
                base = base.func
            if not isinstance(base, ast.Name):
                continue
            if base.id in _ATTR_312 and node.attr in _ATTR_312[base.id]:
                hits.append(f"{base.id}.{node.attr}")
            elif node.attr == "walk" and base.id in _PATH_NAMES:
                hits.append(f"{base.id}.walk")
    return hits


def test_py311_guard_itself_detects():
    """守卫不得是安慰剂：真写法必须命中，散文与 innocuous 同名属性不得命中。"""
    assert _py312_hits("from itertools import batched\n")
    assert _py312_hits("now = datetime.UTC.now()\n")
    assert _py312_hits("for root, ds, fs in Path('.').walk():\n    pass\n")
    assert _py312_hits("from datetime import UTC\n")
    # os.walk 与 pathlib 无关；题面里的禁令是字符串，不是代码
    assert not _py312_hits("for r in os.walk('.'):\n    pass\n")
    assert not _py312_hits(
        "RULE = '禁止 itertools.batched、datetime.UTC、Path.walk（3.12 起）'\n")
    # 语法腿同样要真的在挡（9/23 实测 feature_version 只挡 PEP 695）
    import ast

    with pytest.raises(SyntaxError):
        ast.parse("type X = int\n", feature_version=(3, 11))
    with pytest.raises(SyntaxError):
        ast.parse("def f[T](x: T) -> T:\n    return x\n",
                  feature_version=(3, 11))


def test_shipped_product_code_parses_and_runs_on_py311():
    import ast

    root = Path(__file__).resolve().parents[1]
    files = [root / "main.py",
             *[p for p in sorted((root / "app").rglob("*.py"))
               if "__pycache__" not in p.parts]]
    assert len(files) > 40, "扫描集不得为空：路径变了要跟着改"
    bad: list[str] = []
    for py in files:
        rel = str(py.relative_to(root))
        src = py.read_text(encoding="utf-8", errors="replace")
        try:
            ast.parse(src, filename=rel, feature_version=(3, 11))
        except SyntaxError as exc:
            bad.append(f"{rel}: 3.11 无法解析（{exc.msg}）")
            continue
        bad += [f"{rel}: 3.12 专属符号 {h}" for h in _py312_hits(src)]
    assert not bad, "官方容器解释器是 3.11，崩在导入期=整跑不评分：\n" \
        + "\n".join(bad)
