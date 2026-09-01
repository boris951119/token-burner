"""仅跑 TestZombieSweep，完整 traceback 落盘。"""

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

buf = io.StringIO()
real = sys.stdout
sys.stdout = buf
try:
    code = pytest.main(
        ["tests/test_task_cancel.py::TestZombieSweep", "-q", "--no-header",
         "--tb=long", f"--rootdir={ROOT}"]
    )
finally:
    sys.stdout = real

(ROOT / "zombie_tb.txt").write_text(buf.getvalue() or "(no output)\n", encoding="utf-8")
print(f"exit={code}")
