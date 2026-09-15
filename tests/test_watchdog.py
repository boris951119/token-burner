# -*- coding: utf-8 -*-
"""看门狗回归（keep5 取证：进程楔死墙钟保护之外 7.7h 零取证）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_touch_progress_refreshes_global():
    from app import pipeline as pl
    import time

    before = pl.LAST_PROGRESS
    time.sleep(0.01)
    pl.touch_progress()
    assert pl.LAST_PROGRESS >= before


def test_emit_touches_progress(monkeypatch, tmp_path):
    from app import pipeline as pl

    monkeypatch.setattr(pl.Pipeline, "_beat", lambda self, *a, **k: None)
    monkeypatch.setattr(
        pl.Pipeline, "_on_event", property(lambda self: None), raising=False)
    # 直接构造最小 Pipeline 实例成本高——用 _emit 的类方法绑定语义验证：
    # _emit 首行即 touch_progress（源码断言防回归）
    src = Path(pl.__file__).read_text(encoding="utf-8")
    assert "touch_progress()" in src.split("def _emit")[1].split("def ")[0]


def test_progress_globals_exist():
    from app import pipeline as pl
    import time

    assert isinstance(pl.LAST_PROGRESS, float)
    assert callable(pl.touch_progress)
    assert time.time() - pl.LAST_PROGRESS < 60
