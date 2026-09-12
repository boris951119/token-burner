"""pytest 路径引导：把 code/ 加入 sys.path，使测试可导入项目模块。"""
import sys
from pathlib import Path

_CODE_DIR = Path(__file__).resolve().parent / "code"
if _CODE_DIR.is_dir() and str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))
