# -*- coding: utf-8 -*-
"""presubmit_gate 单元验收：A 段正例/反例（零 token）。"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from scripts.presubmit_gate import (
    find_import_shadows,
    check_config_in_zip,
    check_import_shadows_in_zip,
    check_layout,
    run_gate,
)


def test_import_shadow_detects_threading_pattern():
    src = (
        "import threading\n"
        "def main():\n"
        "    threading.Thread(target=lambda: None).start()\n"
        "    import threading\n"
        "    threading.Thread(target=lambda: None).start()\n"
    )
    hits = find_import_shadows(src, path="main.py")
    assert hits, hits
    assert "threading" in hits[0]


def test_import_shadow_clean_when_top_level_only():
    src = (
        "import threading\n"
        "def main():\n"
        "    threading.Thread(target=lambda: None).start()\n"
    )
    assert find_import_shadows(src) == []


def _write_min_zip(path: Path, *, config: dict, main_py: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("config.json", json.dumps(config))
        zf.writestr("main.py", main_py)
        zf.writestr("requirements.txt", "flask\n")
        zf.writestr("README.md", "x\n")
        zf.writestr("app/__init__.py", "")


_OFFICIAL_CFG = {
    "models": [
        "openai/deepseek-v4-pro",
        "openai/deepseek-v4-flash",
        "openai/qwen3.7-max",
    ],
    "max_task_tokens_cap": 0,
    "selftest_specs_enabled": True,
}

_TRIAL_CFG = {
    "models": [
        "openai/deepseek-v4-flash",
        "openai/qwen3.7-plus",
        "openai/glm-5.3-flash",
    ],
    "max_task_tokens_cap": 1600000,
    "selftest_specs_enabled": False,
}

_CLEAN_MAIN = "import threading\ndef main():\n    return 0\n"
_SHADOW_MAIN = (
    "import threading\n"
    "def main():\n"
    "    threading.Thread(target=lambda: None).start()\n"
    "    import threading\n"
)


def test_a_rejects_trial_config(tmp_path):
    z = tmp_path / "trial.zip"
    _write_min_zip(z, config=_TRIAL_CFG, main_py=_CLEAN_MAIN)
    with zipfile.ZipFile(z) as zf:
        c = check_config_in_zip(zf)
    assert c.ok is False
    assert "试跑" in c.detail or "cap" in c.detail.lower() or "specs" in c.detail


def test_a_rejects_import_shadow_zip(tmp_path):
    z = tmp_path / "shadow.zip"
    _write_min_zip(z, config=_OFFICIAL_CFG, main_py=_SHADOW_MAIN)
    with zipfile.ZipFile(z) as zf:
        c = check_import_shadows_in_zip(zf)
    assert c.ok is False
    assert "threading" in c.detail


def test_a_accepts_official_clean(tmp_path):
    z = tmp_path / "ok.zip"
    _write_min_zip(z, config=_OFFICIAL_CFG, main_py=_CLEAN_MAIN)
    with zipfile.ZipFile(z) as zf:
        assert check_config_in_zip(zf).ok
        assert check_import_shadows_in_zip(zf).ok
        assert check_layout(zf).ok


def test_v48_zip_passes_segment_a_if_present():
    z = Path(".tmp/submission-pack/v48.zip")
    if not z.is_file():
        return
    with zipfile.ZipFile(z) as zf:
        assert check_config_in_zip(zf).ok, check_config_in_zip(zf).detail
        assert check_import_shadows_in_zip(zf).ok
        assert check_layout(zf).ok
