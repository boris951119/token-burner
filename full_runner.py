"""全量回归 runner（detached 调用；结果落盘 pytest_v2.log / pytest_v2.exit）。"""

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

buf = io.StringIO()
real_stdout = sys.stdout
sys.stdout = buf
try:
    code = pytest.main(
        [str(ROOT / "tests"), "-q", "--no-header", "--tb=short",
         f"--rootdir={ROOT}"]
    )
finally:
    sys.stdout = real_stdout

(ROOT / "pytest_v2.log").write_text(buf.getvalue() or "(no output)\n", encoding="utf-8")
(ROOT / "pytest_v2.exit").write_text(str(code), encoding="utf-8")
print(f"pytest exit={code}")
