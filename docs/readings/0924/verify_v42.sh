#!/bin/sh
# v42 官方形态容器复验（tb-shape:runA-mini：py3.11 + 真实 Flask/FastAPI/httpx/pytest）
# 相比 v41 的变化面 = 批次#67 v42 四条，打包实测恰 7 个文件：
#   app/arcbench_smoke.py app/config.py app/utils/budget.py app/utils/selftest_gate.py
#   app/prompts/write_code_system.md config.json main.py
# 只读包与测试目录；不打印任何环境变量（密钥禁令）。
# 挂载：/pkg=解包后的 v42，/t=开发仓库 tests 子集
set -e
echo "== 1) 解释器"
python3 -V

echo "== 2) 包内 app/ 与 main.py 在 py3.11 下全量编译"
python3 -m compileall -q /pkg/app /pkg/main.py > /tmp/compile.log 2>&1 \
  && echo "COMPILE_OK $(find /pkg/app -name '*.py' | wc -l | tr -d ' ') 文件" \
  || { tail -20 /tmp/compile.log; exit 1; }

echo "== 3) v42-1 信封硬帽：官方档位（cap=0）行为与 v41 一字不变，试跑档位真能砍"
python3 - <<'PY'
import sys
sys.path.insert(0, "/pkg")
from app.utils.budget import size_aware_budget, task_envelope

USED = 1_645_515                      # run 088dd22be41b 实测终态用量
sheet = size_aware_budget(24, 54_048)
assert sheet == 1_621_440 and USED > sheet, "复现死因失败：说明折算口径漂了"
assert task_envelope(24, 54_048, 2_000_000) == 2_000_000 > USED, \
    "①段（只抬不砍）退化：官方那一跑在 v42 仍会死在验收段门口"
assert task_envelope(24, 54_048, 2_000_000, 0) == task_envelope(
    24, 54_048, 2_000_000), "cap=0 必须与不传 cap 完全等价"
# ②段：帽能把托底也砍下来（私有 key 试跑唯一的控成本手段）
assert task_envelope(24, 54_048, 2_000_000, 1_600_000) == 1_600_000
assert task_envelope(47, 146_637, 0, 1_600_000) == 1_600_000
assert task_envelope(24, 54_048, 2_000_000, 9_000_000) == 2_000_000
# 失效方向：脏帽值一律按「没加帽」，绝不允许换成一个 token
for bad in (None, "abc", -1, True, 1.5, 1_500.5, 0):
    assert task_envelope(24, 54_048, 0, bad) == sheet, bad
print("ENVELOPE_OK 只抬不砍仍在 + 硬帽能砍下来 + 脏帽值不掐死任务")
PY

echo "== 4) v42-1 接线：随包 config.json 的帽真能到入口，并在日志上留痕"
python3 - <<'PY'
import json, sys
sys.path.insert(0, "/pkg")
from app.config import load_settings

s = load_settings(config_file="/pkg/config.json")
raw = json.loads(open("/pkg/config.json", encoding="utf-8").read())
assert s.max_task_tokens_cap == raw["max_task_tokens_cap"] > 0, "新键没落地"
assert s.selftest_specs_enabled is False
main = open("/pkg/main.py", encoding="utf-8").read()
assert "max_task_tokens_cap" in main and "硬帽" in main, "入口没读帽＝帽是装饰品"
for bad in (-1, "abc", True, 1.5):
    try:
        s.__class__(max_task_tokens_cap=bad)
    except ValueError:
        continue
    raise AssertionError(f"脏帽值 {bad!r} 没被启动期校验拦下")
print("WIRING_OK 随包档位生效 + 入口读帽 + 脏值在启动期就炸出来")
PY

echo "== 5) v42-2 首页硬契约进了逐模块共见的那份提示词（且零题目专名）"
python3 - <<'PY'
p = open("/pkg/app/prompts/write_code_system.md", encoding="utf-8").read()
assert "【首页硬契约" in p, "首页契约不在逐模块共见的提示词里"
for frag in ("业务主页面", "项目自述页", "只有一句欢迎语的空壳页"):
    assert frag in p, f"缺一条禁止形态: {frag}"
# 逐模块共见＝每次开发调用的固定开销，长度必须有界（成本是产品结论）
assert len(p) < 4_200, f"提示词膨胀到 {len(p)} 字符"
print(f"HOME_CONTRACT_OK 首页契约在场（全文 {len(p)} 字符）")
PY

echo "== 6) v42-3 体检前移：Phase 0 用 node-free 段、红字搭现有修复轮的车"
python3 - <<'PY'
import inspect, sys
sys.path.insert(0, "/pkg")
import app.arcbench_smoke as sm

src = inspect.getsource(sm.verify_delivery)
assert "Phase 0" in src and "run_selftests" in src, "前置体检没接进验收"
assert "project_dir, None, port_hint=" in src, \
    "必须复用 node-free 判分段（specs_dir=None），否则前置体检要先烧 token"
assert src.index("Phase 0") < src.index("for verify_round"), \
    "体检排在循环之后＝又是那道没轮到的免费闸"
assert src.count("+ pre_txt") == 2, "红字只搭上一处修环＝另一条通道还是瞎的"
assert "零信号" in src and "异常降级" in src, "0/0 记全绿或体检自身能带走验收"
sig = inspect.signature(
    __import__("app.utils.selftest_gate", fromlist=["x"]).run_selftests).parameters
assert sig["specs_dir"].default is inspect.Parameter.empty, \
    "specs_dir 变成有默认值＝传 None 走不到 node-free 分支"
assert sig["port_hint"].default == 3411 and sig["requirements_dir"].default is None
print("PRECHECK_OK 循环前跑 / node-free 口径 / 两处修环搭车 / 不虚绿不虚红")
PY

echo "== 7) v42-4 specs 开关：关掉付费生成腿，node-free 判分段照跑"
python3 - <<'PY'
import sys
sys.path.insert(0, "/pkg")
import app.utils.selftest_gate as sg

src = __import__("inspect").getsource(sg.selftest_gate)
assert "selftest_specs_enabled" in src, "开关没进自测闸"
assert src.index("selftest_specs_enabled") < src.index("ensure_selftests"), \
    "开关判断晚于生成调用＝关不掉"
print("SPECS_SWITCH_OK 开关在生成调用之前")
PY

echo "== 8) 存活接线未退化（v39/v40/v41 的改动仍在位）"
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
sm = __import__("app.arcbench_smoke", fromlist=["x"])
assert sm._home_route_priority_note("") == ""
assert sm._home_route_priority_note("GET / -> 404").startswith("【本轮唯一优先目标】")
print("SURVIVAL_OK 信号接管/骨架/抢先导出/导入探测/首页优先指令 全在包里")
PY

echo "== 9) 包内代码跑契约/纯度/编译/判分/墙钟/装配/导出/本轮四处修复测试"
mkdir -p /pkg/tests
# test_budget.py 从 tests.test_pipeline 借桩，单拷它会 ModuleNotFoundError（假红，
# 不是包的问题）——连同依赖一起拷。
cp /t/test_acceptance_compile.py /t/test_acceptance_judge.py \
   /t/test_prompt_purity.py /t/test_ui_manifest.py /t/test_task_deadline.py \
   /t/test_mechanical_assembly.py /t/test_platform_export.py \
   /t/test_budget.py /t/test_pipeline.py \
   /t/test_home_route_priority.py /t/test_syntax_freeze.py \
   /t/test_verify_resilience.py /t/test_selftest_env_degradation.py \
   /t/test_arcbench_main.py /pkg/tests/
cd /pkg && PYTHONPATH=/pkg python3 -m pytest -q -p no:randomly \
  -p no:cacheprovider /pkg/tests/ 2>&1 | tail -4
echo "== 复验结束"
