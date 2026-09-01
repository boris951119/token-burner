"""V2 测试落盘运行器（硬编码目标）。"""

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

TARGETS = sys.argv[1:] or ["tests/test_task_cancel.py"]

buf = io.StringIO()
real_stdout = sys.stdout
sys.stdout = buf
try:
    code = pytest.main(
        [*TARGETS, "-q", "--no-header", "--tb=short", f"--rootdir={ROOT}"]
    )
finally:
    sys.stdout = real_stdout

(ROOT / "pytest_v2.log").write_text(buf.getvalue() or "(no output)\n", encoding="utf-8")
print(f"exit={code}")
