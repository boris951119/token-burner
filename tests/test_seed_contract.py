# -*- coding: utf-8 -*-
"""种子声明契约：提取 / 注入 / 审计（9/21 keep 取证回归）。"""
from pathlib import Path

from app.utils.seed_contract import (
    audit_seeds,
    extract_seed_declarations,
    inject_seed_contract,
    seed_names,
)

REQ = """
## REQ-2 Note Management

### REQ-2.1 Note Listing
description: 'Display the notes list. Seed data: pinned note "Sprint goals" and regular note "Groceries".'

### REQ-2.3.1 Delete
description: 'Delete a note. Seed data: deletable note "Delete me 2.3.1".'

### REQ-2.6.1 Change color
description: 'Seed data: regular note "Garden tasks existing" with a white background. Dropdown image: ![image](./reference/note_more_options_dropdown.png)'
"""


def test_extract_keeps_verbatim_names_grouped_by_req():
    decls = extract_seed_declarations(REQ)
    assert ("REQ-2.1 Note Listing", ["Sprint goals", "Groceries"]) in decls
    assert ("REQ-2.3.1 Delete", ["Delete me 2.3.1"]) in decls
    # 引用图片不是种子
    names = seed_names(REQ)
    assert "Sprint goals" in names and "note_more_options_dropdown" not in names


def test_inject_targets_data_layer_module():
    class P:
        def __init__(self, name, resp=""):
            self.name = name
            self.responsibility = resp

    plans = [P("home"), P("data_layer"), P("search")]
    target = inject_seed_contract(plans, REQ)
    assert target == "data_layer"
    assert "Sprint goals" in plans[1].responsibility
    assert "Sprint goals" not in plans[0].responsibility


def test_inject_noop_without_declarations():
    class P:
        name = "app"
        responsibility = ""

    plans = [P()]
    assert inject_seed_contract(plans, "无种子的需求") is None


def test_audit_flags_missing_seeds(tmp_path: Path):
    code = tmp_path / "code" / "data"
    code.mkdir(parents=True)
    (tmp_path / "code" / "data_layer.py").write_text(
        'SEED_NOTES = ["Call dentist existing", "st"]\n', encoding="utf-8")
    missing = audit_seeds(tmp_path / "code", REQ)
    joined = "\n".join(missing)
    assert "Sprint goals" in joined
    assert "Groceries" in joined
    # 声明外自编数据不是缺口
    assert "Call dentist" not in joined


def test_audit_silent_when_all_seeded(tmp_path: Path):
    (tmp_path / "code").mkdir(parents=True)
    (tmp_path / "code" / "seed.py").write_text(
        'SEED = ["Sprint goals", "Groceries", "Delete me 2.3.1",\n'
        '        "Garden tasks existing"]\n', encoding="utf-8")
    assert audit_seeds(tmp_path / "code", REQ) == []
