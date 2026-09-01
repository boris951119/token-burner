"""V2 全量回归：detached 运行 full_runner.py。"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

subprocess.Popen(
    [sys.executable, str(ROOT / "full_runner.py")],
    cwd=ROOT,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
print("launched")
