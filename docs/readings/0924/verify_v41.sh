#!/bin/sh
# v41 官方形态容器复验（tb-shape:runA-mini：py3.11 + 真实 Flask/FastAPI/httpx/pytest）
# 相比 v40 的变化面 = 批次#64（首跑 088dd22be41b 三条死因），打包实测只差 4 个文件：
#   main.py / app/utils/budget.py / app/arcbench_smoke.py / app/agents/repo_fixer.py
# 只读包与测试目录；不打印任何环境变量（密钥禁令）。
# 挂载：/pkg=解包后的 v41，/t=开发仓库 tests 子集
set -e
echo "== 1) 解释器"
python3 -V

echo "== 2) 包内 app/ 与 main.py 在 py3.11 下全量编译"
python3 -m compileall -q /pkg/app /pkg/main.py > /tmp/compile.log 2>&1 \
  && echo "COMPILE_OK $(find /pkg/app -name '*.py' | wc -l | tr -d ' ') 文件" \
  || { tail -20 /tmp/compile.log; exit 1; }

echo "== 3) 64A 信封只抬不砍：官方那一跑的用量在 v41 下不会断气"
python3 - <<'PY'
import sys
sys.path.insert(0, "/pkg")
from app.utils.budget import size_aware_budget, task_envelope

USED = 1_645_515                      # run 088dd22be41b 实测终态用量
sheet = size_aware_budget(24, 54_048)
assert sheet == 1_621_440 and USED > sheet, "复现死因失败：说明折算口径漂了"
assert task_envelope(24, 54_048, 2_000_000) == 2_000_000 > USED, \
    "配置托底没生效——同一跑在 v41 仍会死在验收段门口"
# 字数项更大时不得反向压价（github 题面）
assert task_envelope(47, 146_637, 2_000_000) == size_aware_budget(47, 146_637)
for bad in (0, None, -5, "abc", "2000000"):
    got = task_envelope(24, 54_048, bad)
    assert got == (2_000_000 if bad == "2000000" else sheet), bad
print("ENVELOPE_OK 只抬不砍 + 脏值按「没有托底」降级（数字字符串仍算托底）")
PY

echo "== 4) 64B 首页失败的修复优先级：只在真有首页失败时出口，且出在指令最前"
python3 - <<'PY'
import inspect, sys
sys.path.insert(0, "/pkg")
import app.arcbench_smoke as sm

assert sm._home_route_priority_note("") == ""
assert sm._home_route_priority_note("/api/health -> 500\nKeyError") == "", \
    "没有首页失败也塞优先指令＝给修复环加噪声"
note = sm._home_route_priority_note("entry <- app_main\nGET / -> 404（入口路由缺失？）")
assert note.startswith("【本轮唯一优先目标】") and "GET /" in note and "占位" in note
sig = inspect.signature(sm.auto_repair).parameters
assert "priority_note" in sig and sig["priority_note"].default == ""
src = inspect.getsource(sm.verify_delivery)
assert "priority_note=_home_route_priority_note" in src, "接线断了：算了优先指令没传进修环"
print("HOME_PRIORITY_OK 判据成对（有/无）+ auto_repair 形参 + 调用点已接线")
PY

echo "== 5) 64C 语法拒收冻结：整批草稿全被拒才收手，且不否决同批可改文件"
python3 - <<'PY'
import sys, tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, "/pkg")
import app.agents.repo_fixer as rfm

INVALID, VALID = "def broken(:\n    return 1\n", "def fixed(a):\n    return a\n"
FAIL = [sys.executable, "-c", "raise SystemExit(1)"]

def stub(plan, by_path):
    def call(system, user):
        if "仓库文件树" in user:
            import json
            return json.dumps(plan, ensure_ascii=False)
        for p in by_path:
            if f"## 目标文件\n{p}" in user:
                return by_path[p]
        return ""
    return call

with tempfile.TemporaryDirectory() as d:
    repo = Path(d)
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (repo / "helpers.py").write_text("X = 1\n", encoding="utf-8")
    calls = {"n": 0}
    def counting(inner):
        def call(s, u):
            calls["n"] += 1
            return inner(s, u)
        return call
    plan = {"analysis": "x", "files": [{"path": "calc.py", "change": "c"},
                                       {"path": "helpers.py", "change": "h"}]}
    fixer = rfm.RepoFixer(counting(stub(plan, {"calc.py": INVALID,
                                               "helpers.py": "X = 2\n"})),
                          repo, test_cmd=FAIL, max_rounds=2)
    rfm._FROZEN.add(f"{fixer.repo}::calc.py")
    r = fixer.fix("修两个文件")
    assert "冻结" not in r.error, "一个文件冻结不该把整批修复提前掐死"
    assert (repo / "helpers.py").read_text(encoding="utf-8").strip() == "X = 2"
    assert rfm._SYNTAX_FAILS[f"{fixer.repo}::calc.py"] == 2, rfm._SYNTAX_FAILS

    rfm._SYNTAX_FAILS.clear(); rfm._FROZEN.clear()
    calls["n"] = 0
    solo = {"analysis": "x", "files": [{"path": "calc.py", "change": "c"}]}
    fixer = rfm.RepoFixer(counting(stub(solo, {"calc.py": INVALID})),
                          repo, test_cmd=FAIL, max_rounds=3)
    r = fixer.fix("calc 语法非法")
    assert r.rounds == 2 and "冻结" in r.error, (r.rounds, r.error)
    assert calls["n"] == 3, f"第 3 轮还在发 LLM 调用：{calls['n']}"
    assert f"{fixer.repo}::calc.py" in rfm._FROZEN
print("SYNTAX_FREEZE_OK 按文件计数 + 整批被拒才收手 + 省掉第 3 轮调用")
PY

echo "== 6) 存活接线未退化（v39/v40 的改动仍在位）"
python3 - <<'PY'
import sys
sys.path.insert(0, "/pkg")
from app.utils.budget import DEFAULT_TASK_SECONDS, task_seconds_remaining
assert DEFAULT_TASK_SECONDS == 48 * 3600
assert task_seconds_remaining() is None, "容器外不该有起表的墙钟"
main = open("/pkg/main.py", encoding="utf-8").read()
for sym in ("_install_death_signals", "_emergency_salvage", "_skeleton_or_fail",
            "task_envelope", "抢先交付"):
    assert sym in main, f"入口缺 {sym}"
from app.platform_export import export_skeleton_layout
from app.utils.mechanical_assembly import probe_entries
print("SURVIVAL_OK 信号接管/骨架/抢先导出/导入探测 四条线都在包里")
PY

echo "== 7) 包内代码跑契约/纯度/编译/判分/墙钟/装配/导出/本轮三处修复测试"
mkdir -p /pkg/tests
# test_budget.py 从 tests.test_pipeline 借桩，单拷它会 ModuleNotFoundError（假红，
# 不是包的问题）——连同依赖一起拷。
cp /t/test_acceptance_compile.py /t/test_acceptance_judge.py \
   /t/test_prompt_purity.py /t/test_ui_manifest.py /t/test_task_deadline.py \
   /t/test_mechanical_assembly.py /t/test_platform_export.py \
   /t/test_budget.py /t/test_pipeline.py \
   /t/test_home_route_priority.py /t/test_syntax_freeze.py \
   /pkg/tests/
cd /pkg && PYTHONPATH=/pkg python3 -m pytest -q -p no:randomly \
  -p no:cacheprovider /pkg/tests/ 2>&1 | tail -4
echo "== 复验结束"
