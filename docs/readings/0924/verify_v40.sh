#!/bin/sh
# v40 官方形态容器复验（tb-shape:runA-mini：py3.11 + 真实 Flask/FastAPI/httpx/pytest）
# 相比 v39 的变化面 = 批次#63（入口保底改导入探测 + 保底壳逐条 import 容错 +
# walk-abort + 零代码诚实骨架），打包实测只差 3 个文件：
#   main.py / app/utils/mechanical_assembly.py / app/platform_export.py
# 只读包与测试目录；不打印任何环境变量（密钥禁令）。
# 挂载：/pkg=解包后的 v40，/t=开发仓库 tests 子集
set -e
echo "== 1) 解释器"
python3 -V

echo "== 2) 包内 app/ 与 main.py 在 py3.11 下全量编译"
python3 -m compileall -q /pkg/app /pkg/main.py > /tmp/compile.log 2>&1 \
  && echo "COMPILE_OK $(find /pkg/app -name '*.py' | wc -l | tr -d ' ') 文件" \
  || { tail -20 /tmp/compile.log; exit 1; }

echo "== 3) 入口保底改「导入探测」口径（批次#63 第①条，主读数）"
python3 - <<'PY'
import sys, tempfile, pathlib
sys.path.insert(0, "/pkg")
from app.utils.mechanical_assembly import ensure_entry, probe_entries

def tree(root, src):
    pkg = root / "code" / "notes"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "notes.py").write_text(src, encoding="utf-8")
    return root / "code"

LIVE = ("from flask import Flask\n\n"
        "def create_app():\n    return Flask(__name__)\n")
DEAD = "def create_app():\n    pass\n"          # 文字在场、跑起来等于没入口

with tempfile.TemporaryDirectory() as d:
    root = pathlib.Path(d)
    code = tree(root, LIVE)
    assert ensure_entry(code) is None, "作者入口活着却被打扰——会旁路修复成果"
    p = probe_entries(code)
    assert p and p["live"], f"探测没认出活入口: {p}"
with tempfile.TemporaryDirectory() as d:
    root = pathlib.Path(d)
    code = tree(root, DEAD)
    assert not probe_entries(code)["live"], "死工厂不该被探测认成活入口（这是改判的前提）"
    fix = ensure_entry(code)
    assert fix and (code / "app_main" / "app_main.py").is_file(), \
        "跑不起来的作者入口必须触发保底装配（旧文本口径在这里放行 → exit 1）"
    after = probe_entries(code)
    assert any("app_main" in x for x in after["live"]), \
        f"装配完仍然探不到活入口，白兜一趟: {after}"
    shell = (code / "app_main" / "app_main.py").read_text(encoding="utf-8")
    assert "__arcbench_assembled__ = True" in shell, "壳必须带让位标记"
print("ENTRY_FLOOR_OK 三态判定正确（活入口让位 / 死工厂装配兜底 / 兜完探得到壳）")
PY

echo "== 4) 保底壳自身抗坏包 + 启动器不再 walk-abort（第②③④条）"
python3 - <<'PY'
import re, sys
from pathlib import Path
sys.path.insert(0, "/pkg")
from app.utils.mechanical_assembly import ModuleSurface, generate_app_main
from app.platform_export import _BACKEND_MAIN

surfaces = [
    ModuleSurface(name="home.sub", blueprints=[("web", "bp")], routers=[],
                  inits=[], path=None),
    ModuleSurface(name="ghost", blueprints=[("x", "bp")], routers=[],
                  inits=[], path=None),
]
shell = generate_app_main(surfaces)
compile(shell, "app_main_generated", "exec")   # 带点的包名不得生成非法标识符
assert "re.sub" not in shell
assert "_bp_home_sub_web" in shell, "别名没做 sanitize（嵌套包会生成非法名字）"
assert shell.count("try:") >= 2, "壳的 import 不是逐条容错"
assert "pkgutil.walk_packages(" not in _BACKEND_MAIN, \
    "启动器又用回 walk_packages：坏包能在迭代器内部炸穿整棵树的入口发现"
assert "pkgutil.iter_modules(" in _BACKEND_MAIN
print("SHELL_OK 别名合法 + 逐条 try + 启动器自己走目录树")
PY

echo "== 5) 零代码诚实骨架：只在没产物时落地，且绝不含业务路由（63B）"
python3 - <<'PY'
import sys, tempfile
from pathlib import Path
sys.path.insert(0, "/pkg")
from app.platform_export import export_skeleton_layout, _SKELETON_MAIN

with tempfile.TemporaryDirectory() as d:
    out = Path(d)
    assert export_skeleton_layout(out, "容器复验") is True
    be = out / "backend"
    assert (be / "main.py").is_file() and (be / "requirements.txt").is_file()
    assert (be / "ARCBENCH_SKELETON.txt").is_file(), "骨架必须自带尸检标记"
    txt = (be / "main.py").read_text(encoding="utf-8")
    assert "/api/health" in txt and "No application was generated" in txt
    for banned in ("def create_app", "render_template", "register_blueprint",
                   "sqlite3"):
        assert banned not in txt, f"骨架里出现了业务实现痕迹: {banned}"
    assert txt.count("@app.route") == 2, "骨架只许 health + 一个说明页"
    # 已有真产物时一律不覆盖
    (be / "real_app.py").write_text("x = 1\n", encoding="utf-8")
    (be / "ARCBENCH_SKELETON.txt").unlink()
    assert export_skeleton_layout(out, "不该覆盖真产物") is False
    assert (be / "real_app.py").is_file()
print("SKELETON_OK 落地/标记/零业务路由/不覆盖真产物 四项通过")
PY

echo "== 6) 信封与墙钟未退化（v39 的两批改动仍在位）"
python3 - <<'PY'
import sys
sys.path.insert(0, "/pkg")
from app.utils.budget import size_aware_budget, DEFAULT_TASK_SECONDS
practice = {32: (17_797, 1_440_000), 34: (19_096, 1_480_000),
            66: (44_275, 2_120_000), 86: (40_235, 2_520_000),
            117: (86_237, 3_140_000), 125: (58_223, 3_300_000)}
for n, (chars, expect) in practice.items():
    assert size_aware_budget(n, chars) == expect, n
for n, chars, expect in ((24, 54_048, 1_621_440), (47, 146_637, 4_399_110)):
    assert size_aware_budget(n, chars) == expect, n
assert DEFAULT_TASK_SECONDS == 48 * 3600
main = open("/pkg/main.py", encoding="utf-8").read()
for sym in ("_install_death_signals", "_emergency_salvage", "_skeleton_or_fail"):
    assert sym in main, f"入口缺 {sym}"
print("ENVELOPE_OK 初赛 6/6 不变 · 正式赛 2/2 字数项 · 48h 缺省 · 存活接线齐")
PY

echo "== 7) 包内代码跑契约/纯度/编译/判分/墙钟/装配/导出测试"
mkdir -p /pkg/tests
cp /t/test_acceptance_compile.py /t/test_acceptance_judge.py \
   /t/test_prompt_purity.py /t/test_ui_manifest.py /t/test_task_deadline.py \
   /t/test_mechanical_assembly.py /t/test_platform_export.py /pkg/tests/
cd /pkg && PYTHONPATH=/pkg python3 -m pytest -q -p no:randomly \
  -p no:cacheprovider /pkg/tests/ 2>&1 | tail -4
echo "== 复验结束"
