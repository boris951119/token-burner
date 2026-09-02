# -*- coding: utf-8 -*-
"""v1.0 V0 批次端到端取证：v0.5 断裂场景（validate_isbn 丢失）双重防线验证。

重放 v0.5 真实事故链路：
  1. 第一模块写入 _shared/utils.py（含 validate_isbn/validate_date）
  2. book_validator 模块代码 import 这两个符号并落盘
  3. 后续模块 LLM 输出的 _shared 标记块只含格式化函数（丢校验函数）

验证双重防线：
  防线一（M14-1 合并守卫）：write_shared_file 落盘自动保留丢失符号
  防线二（M14-2 链接门禁）：即使守卫被绕过（直接写盘），门禁确定性拦截
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from app.tools.file_manager import FileManager  # noqa: E402
from app.utils.link_check import check_links, format_link_issues  # noqa: E402

OLD_SHARED = '''\
"""共享工具：校验函数。"""


def validate_isbn(isbn: str) -> bool:
    return len(isbn.replace("-", "")) == 13


def validate_date(date: str) -> bool:
    return len(date) == 10
'''

# 后续模块的 LLM 输出（v0.5 事故形态：只知道自己上下文的函数）
LOST_SHARED = '''\
"""共享工具：格式化函数。"""


def format_title(t: str) -> str:
    return t.strip().title()
'''

VALIDATOR_CODE = (
    "from _shared.utils import validate_isbn, validate_date\n\n"
    "def check_book(isbn, date):\n"
    "    return validate_isbn(isbn) and validate_date(date)\n"
)

print("=== v0.5 断裂场景端到端取证 ===\n")
tmp = Path(tempfile.mkdtemp())
fm = FileManager(projects_root=tmp / "projects")
pid = fm.create_project("book-cli").project_id

# 事故链路搭建
fm.write_shared_file(pid, "utils.py", OLD_SHARED)
fm.write_code_file(pid, "book_validator", "book_validator.py", VALIDATOR_CODE)
handle = fm.get_project(pid)
code_root = handle.root / "code"

print("[步骤1] 基线：断裂前全链接检查")
r0 = check_links(code_root)
print(f"  结果: {'PASS' if r0.passed else 'FAIL'}（应为 PASS）")
assert r0.passed

print("\n[防线一] M14-1 合并守卫：LLM 输出丢函数，write_shared_file 落盘")
fm.write_shared_file(pid, "utils.py", LOST_SHARED)
on_disk = (code_root / "_shared" / "utils.py").read_text(encoding="utf-8")
kept = "validate_isbn" in on_disk and "validate_date" in on_disk
print(f"  落盘内容保留 validate_isbn/validate_date: {'✓ 是' if kept else '✗ 否'}")
print(f"  新函数 format_title 也在: {'✓' if 'format_title' in on_disk else '✗'}")
print(f"  全链路链接检查: {'PASS' if check_links(code_root).passed else 'FAIL'}")
assert kept, "合并守卫未生效"
assert check_links(code_root).passed, "守卫补救后链接应完整"

print("\n[防线二] M14-2 链接门禁：绕过守卫直接写盘（模拟守卫失效）")
(code_root / "_shared" / "utils.py").write_text(LOST_SHARED, encoding="utf-8")
r2 = check_links(
    code_root,
    pending_module="ui_formatter",
    pending_code="def render():\n    return 'ui'\n",
)
print(f"  门禁结果: {'拦截 ✓' if not r2.passed else '放行 ✗（防线失效！）'}")
report = format_link_issues(r2.issues)
for line in report.splitlines():
    print(f"  | {line}")
assert not r2.passed, "链接门禁未拦截断裂"
assert "validate_isbn" in report and "validate_date" in report

print("\n=== 取证结论 ===")
print("v0.5 的 validate_isbn 断裂场景已被双重防线覆盖：")
print("  防线一（根因修复）：合并守卫使覆盖写入不再丢符号（落盘即补救）")
print("  防线二（确定性兜底）：即使守卫失效，链接门禁在任何新模块开发时")
print("  确定性拦截并输出精确缺失清单（含 FROZEN 模块的断裂）")
print("\n全部断言通过 ✓")
