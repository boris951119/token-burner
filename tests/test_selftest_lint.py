# -*- coding: utf-8 -*-
"""lint 门：坏 spec 隔离、好 spec 存活（首版正则误伤全量的回归）。"""
import shutil
from pathlib import Path

import pytest

from app.utils.selftest_gate import GRADE_DIR, lint_specs

GOOD = (
    "import { test, expect } from '@playwright/test';\n"
    "test('home shows title', async ({ page }) => {\n"
    "  await page.goto('/');\n"
    "  await expect(page.getByRole('heading')).toBeVisible();\n"
    "});\n"
)
BAD = "this is not typescript at all <<<>>>\n"


_NODE = bool(shutil.which("npx") and (GRADE_DIR / "package.json").is_file())


@pytest.mark.skipif(not _NODE, reason="playwright 运行环境未安装（无 npx）")
def test_lint_keeps_good_drops_bad(tmp_path):
    specs = tmp_path / "selftest"
    specs.mkdir(parents=True)
    (specs / "good.spec.ts").write_text(GOOD, encoding="utf-8")
    (specs / "bad.spec.ts").write_text(BAD, encoding="utf-8")
    survivors = lint_specs(specs, tmp_path)
    assert survivors == 1
    assert (specs / "good.spec.ts").is_file()
    assert not (specs / "bad.spec.ts").exists()
    assert (tmp_path / "selftest_rejected" / "bad.spec.ts").is_file()


def test_lint_without_node_keeps_everything(tmp_path, monkeypatch):
    """无 npx 环境（Linux 交付容器实证）：lint 不得抛错，更不得把
    判不了的 spec 当坏的删掉。"""
    import app.utils.selftest_gate as sg

    monkeypatch.setattr(sg.shutil, "which", lambda _name: None)
    specs = tmp_path / "selftest"
    specs.mkdir(parents=True)
    (specs / "good.spec.ts").write_text(GOOD, encoding="utf-8")
    (specs / "bad.spec.ts").write_text(BAD, encoding="utf-8")
    assert lint_specs(specs, tmp_path) == 2
    assert (specs / "bad.spec.ts").is_file()
    assert not (tmp_path / "selftest_rejected").exists()
