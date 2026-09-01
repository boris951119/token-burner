"""pytest 内部环境诊断：TaskManager projects_root 与 glob 行为。"""

import io
import json
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
        ["tests/test_task_cancel.py::TestZombieSweep::test_running_state_marked_cancelled_on_startup",
         "-q", "--no-header", "--tb=short", "-s", f"--rootdir={ROOT}"]
    )
finally:
    sys.stdout = real

(ROOT / "zombie_internals.txt").write_text(
    buf.getvalue() or "(no output)\n", encoding="utf-8"
)
print(f"exit={code}")
