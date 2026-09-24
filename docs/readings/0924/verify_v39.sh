#!/bin/sh
# v39 官方形态容器复验（tb-shape:runA-mini：py3.11 + 真实 Flask/FastAPI/httpx/pytest）
# 相比 v38 的变化面 = 批次#58A（信封改文本感知）+ #58B（墙钟与信号接管）+ #60（契约八），
# 打包侧实测只有 4 个文件不同：main.py / app/pipeline.py / app/utils/budget.py /
# app/prompts/write_code_system.md。本脚本按这 4 个文件逐条读回。
# 只读包与测试目录；不打印任何环境变量（密钥禁令）。
# 挂载：/pkg=解包后的 v39，/t=开发仓库 tests 子集，/off=.tmp/arcbench-official 只读
set -e
echo "== 1) 解释器"
python3 -V

echo "== 2) 包内 app/ 与 main.py 在 py3.11 下全量编译"
python3 -m compileall -q /pkg/app /pkg/main.py > /tmp/compile.log 2>&1 \
  && echo "COMPILE_OK $(find /pkg/app -name '*.py' | wc -l | tr -d ' ') 文件" \
  || { tail -20 /tmp/compile.log; exit 1; }

echo "== 3) 契约八是否真的随包（批次#60 主读数）"
python3 - <<'PY'
from pathlib import Path
txt = Path("/pkg/app/prompts/write_code_system.md").read_text(encoding="utf-8")
assert "【页面族与存储硬规则" in txt, "契约八段没随包"
probes = ("GET 路由", "就地展开不算", "只回 JSON", "从首页就能点到的真实控件",
          "深链永不被访问", "跨表聚合查询", "一个应用只有一张真库",
          "路径解析表达式在全项目必须唯一")
missing = [p for p in probes if p not in txt.replace("\n", "")]
assert not missing, f"契约八缺条款：{missing}"
print(f"CONTRACT8_OK {len(probes)}/{len(probes)} 条款在包内，提示词 {len(txt)} 字符")
# 反 #46：随包提示词零题目专名
nouns = ("Take a note", "Sprint goals", "Reminders", "BookStack", "PrestaShop",
         "StackOverflow", "12306", "携程", "Create a page")
low = txt.lower()
hits = [n for n in nouns if n.lower() in low]
assert not hits, f"提示词含题目专名: {hits}"
print("PURITY_OK 契约八段零题目专名")
PY

echo "== 4) 存活闸接线是否在包内（批次#58B）"
python3 - <<'PY'
import re
from pathlib import Path
main = Path("/pkg/main.py").read_text(encoding="utf-8")
for sym in ("_install_death_signals", "_termination_handler", "_export_busy",
            "_emergency_salvage", "arm_task_deadline", "deadline_brief"):
    assert sym in main, f"入口缺 {sym}"
seg = main[main.index("def _watchdog"):main.index("threading.Thread(target=_watchdog")]
assert "_salvage_export" in seg and seg.index("_salvage_export") < seg.index("os._exit(75)"), \
    "看门狗裸退没补导出（#58B 第④处接线漂了）"
bud = Path("/pkg/app/utils/budget.py").read_text(encoding="utf-8")
for sym in ("class TaskDeadlineError", "def arm_task_deadline", "wind_down_seconds",
            "TASK_TIME_ENV", "DEFAULT_TASK_SECONDS"):
    assert sym in bud, f"预算层缺 {sym}"
assert "TaskCancelledError" in bud.split("class TaskDeadlineError")[1][:200], \
    "TaskDeadlineError 不再是取消类的子类"
pipe = Path("/pkg/app/pipeline.py").read_text(encoding="utf-8")
assert pipe.count("except TaskDeadlineError as exc") == 2, \
    f"管线两处墙钟分支应为 2，实测 {pipe.count('except TaskDeadlineError as exc')}"
print("WIRING_OK 入口/预算/管线三处接线齐（run+resume 各一分支）")
PY

echo "== 5) 信封在 py3.11 里复算：初赛六道数值一字不变 + 正式赛两题按字数抬"
python3 - <<'PY'
import sys
sys.path.insert(0, "/pkg")
from app.utils.budget import size_aware_budget, DEFAULT_TASK_SECONDS

practice = {32: (17_797, 1_440_000), 34: (19_096, 1_480_000),
            66: (44_275, 2_120_000), 86: (40_235, 2_520_000),
            117: (86_237, 3_140_000), 125: (58_223, 3_300_000)}
for n, (chars, expect) in practice.items():
    got = size_aware_budget(n, chars)
    assert got == expect, f"{n} 条/{chars} 字: {got} != {expect}"
formal = {24: (54_048, 1_621_440), 47: (146_637, 4_399_110)}
for n, (chars, expect) in formal.items():
    got = size_aware_budget(n, chars)
    assert got == expect, f"正式赛 {n} 条: {got} != {expect}"
    assert got > size_aware_budget(n), "字数项没起作用（还是按条数发钱）"
assert DEFAULT_TASK_SECONDS == 48 * 3600
print("ENVELOPE_OK 初赛 6/6 不变 · 正式赛 2/2 由字数项决定 · 墙钟缺省 48h")
PY

echo "== 6) 包内编译器在官方题面上的种子通道未退化（批次#48 读数）"
python3 - <<'PY'
import sys
sys.path.insert(0, "/pkg")
from pathlib import Path
from app.acceptance_compile import compile_checklists
total = 0
for task in ("12306", "bookstack", "ctrip", "keep", "prestashop", "stackoverflow"):
    y = Path("/off/arc-bench/webapp") / task / "requirements/requirements.yaml"
    if not y.exists():
        print(f"   {task}: 题面不在容器里（跳过）")
        continue
    cl = compile_checklists(y)
    total += sum(len(c.seed_entities) for c in cl)
print("SEED_TOTAL", total)
assert total > 40, "官方题面种子通道退化——包内代码不是改过的版本"
PY

echo "== 7) 包内代码跑契约/纯度/编译/判分/墙钟测试"
mkdir -p /pkg/tests
cp /t/test_acceptance_compile.py /t/test_acceptance_judge.py \
   /t/test_prompt_purity.py /t/test_ui_manifest.py /t/test_task_deadline.py \
   /pkg/tests/
cd /pkg && PYTHONPATH=/pkg python3 -m pytest -q -p no:randomly \
  -p no:cacheprovider /pkg/tests/ 2>&1 | tail -4
echo "== 复验结束"
