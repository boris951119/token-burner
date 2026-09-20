# -*- coding: utf-8 -*-
"""模型绩效台账：record/recommend + 修复升级钩子。"""
import json

from app.utils import model_ledger as ml


def test_record_and_recommend_ranking(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    monkeypatch.setattr(ml, "LEDGER_PATH", path)
    # kimi: 3 战 3 胜；flash: 4 战 2 胜；glm: 1 战 1 胜（样本不足不上榜）
    for _ in range(3):
        ml.record("codegen", "kimi-code", True)
    for _ in range(2):
        ml.record("codegen", "flash", True)
    for _ in range(2):
        ml.record("codegen", "flash", False)
    ml.record("codegen", "glm", True)
    ranked = ml.recommend("codegen")
    assert ranked[0] == "kimi-code"
    assert "flash" in ranked
    assert "glm" not in ranked          # 样本不足不参与排名
    assert "kimi-code" not in ml.recommend("codegen", exclude=("kimi-code",))[:1]


def test_record_never_raises_and_survives(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    monkeypatch.setattr(ml, "LEDGER_PATH", path)
    ml.record("codegen", "flash", True, tokens=123)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["codegen"]["flash"][0] == {"ok": True, "tokens": 123,
                                           "ts": data["codegen"]["flash"][0]["ts"]}
    # 坏路径不抛异常（护栏失败静默降级）
    monkeypatch.setattr(ml, "LEDGER_PATH", tmp_path / "no_dir" / "l.json")
    ml.record("codegen", "flash", False)
