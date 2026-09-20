# -*- coding: utf-8 -*-
"""lint 门：坏 spec 隔离、好 spec 存活（首版正则误伤全量的回归）。"""
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


@pytest.mark.skipif(not (GRADE_DIR / "package.json").is_file(),
                    reason="playwright 运行环境未安装")
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
