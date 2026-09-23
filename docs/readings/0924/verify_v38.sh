#!/bin/sh
# v38 官方形态容器复验（tb-shape:runA-mini：py3.11 + 真实 Flask/FastAPI/httpx/pytest）
# 唯一变量 = app/prompts/write_code_system.md（批次#54：页面渲染硬规则进逐模块共见的提示词）。
# 只读包与测试目录；不打印任何环境变量（密钥禁令）。
# 挂载：/pkg=解包后的 v38，/t=开发仓库 tests 子集，/off=.tmp/arcbench-official 只读
set -e
echo "== 1) 解释器"
python3 -V

echo "== 2) 包内 app/ 在 py3.11 下全量编译"
python3 -m compileall -q /pkg/app > /tmp/compile.log 2>&1 \
  && echo "COMPILE_OK $(find /pkg/app -name '*.py' | wc -l | tr -d ' ') 文件" \
  || { tail -20 /tmp/compile.log; exit 1; }

echo "== 3) 本批次主读数：写码系统提示词是否真的装进硬规则块（v37 里没有）"
python3 - <<'PY'
from pathlib import Path
txt = Path("/pkg/app/prompts/write_code_system.md").read_text(encoding="utf-8")
assert "【页面渲染硬规则" in txt, "硬规则块没随包"
probes = ("渲染层必须从库里读", "语义标签承载", "点下去有变化",
          "不得出现同名", "种子初始化", "与模块名无关")
missing = [p for p in probes if p not in txt]
assert not missing, f"硬规则块缺条款：{missing}"
print(f"PROMPT_OK 6/6 条款在包内，提示词 {len(txt)} 字符")
PY

echo "== 4) 射程：硬规则块必须被逐模块共见的写码提示词读到，而非只进注入文案"
python3 - <<'PY'
import sys
sys.path.insert(0, "/pkg")
from app.agents.module_builder import ModulePlan, inject_ui_manifest
# responsibility 必须是真实形态的中文整句：_UI_TARGET_KEYS 九词全落空时注入器直接
# return None（CLI 题的设计意图），拿合成文案探针会读到假的「命中 0 个」。
mods = (("home", "渲染首页与导航，组装页面静态资源"),
        ("books", "书籍条目的列表页与详情页视图"),
        ("shelves", "书架管理页面与表单"),
        ("search", "搜索接口与结果页"))
plans = [ModulePlan(name=n, responsibility=r, dependencies=[], priority=i)
         for i, (n, r) in enumerate(mods)]
inject_ui_manifest(plans, '需求：首页含 "Search" 输入框，点击 Create Shelf 后保存。')
rule = "渲染层必须从库里读"
hits = [p.name for p in plans if rule in p.responsibility]
print(f"注入射程: {hits} —— 单目标 max(_score)，其余 {len(plans)-len(hits)} 个模块零字")
assert len(hits) == 1, "注入侧本应只覆盖 1 个模块，变了就说明口径漂了"
from pathlib import Path
glob = Path("/pkg/app/prompts/write_code_system.md").read_text(encoding="utf-8")
assert rule in glob, "共见提示词里没有该条款 ⇒ 收口失败"
print("共见射程: write_code_system.md 含该条款，四模块的 system 提示词都会带上")
PY

echo "== 5) 批次#52 主读数：包内生成器契约是否带上五条 L1 语义条款"
python3 - <<'PY'
import sys
sys.path.insert(0, "/pkg")
from app.agents.module_builder import ModulePlan, inject_ui_manifest
plans = [ModulePlan(name="view", responsibility="组装页面与静态资源",
                    dependencies=[], priority=1)]
assert inject_ui_manifest(plans, '需求：首页含 "Search" 输入框。') == "view"
r = plans[0].responsibility
for probe in ("渲染层必须从库里读", "子串", "两张同名卡片", ".first()",
              "必须幂等", "常驻 DOM"):
    assert probe in r, f"包内契约缺条款：{probe}"
print("CONTRACT_OK 5/5 条已随包，注入文本", len(r), "字符")
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

echo "== 7) 包内代码跑 UI 契约 + 纯度 + 编译 + 判分测试"
mkdir -p /pkg/tests
cp /t/test_acceptance_compile.py /t/test_acceptance_judge.py \
   /t/test_prompt_purity.py /t/test_ui_manifest.py /pkg/tests/
# cwd 必须在 /pkg（或 PYTHONPATH=/pkg）：/tmp 下 `import app` 必炸，
# 那是复验脚本的坑不是包的缺陷（9/23 首跑误报 2 个 collection error）。
cd /pkg && PYTHONPATH=/pkg python3 -m pytest -q -p no:randomly \
  -p no:cacheprovider /pkg/tests/ 2>&1 | tail -4
echo "== 复验结束"
