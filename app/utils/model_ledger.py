# -*- coding: utf-8 -*-
"""模型绩效台账：任务类型 × 模型 的历史战绩，驱动路由与升级。

2026-09-20 设计（v8 模型联动 B 件）：
- record：每次生成/修复的结果回写（自测闸/smoke 结果就是裁判）
- recommend：按通过率排序给出该任务类型的模型榜（样本 < min_attempts
  的模型不参与排名——防单样本过拟合）
- 台账是全局跨项目资产（logs/model_ledger.json），旧数据按条数自然
  滚动衰减；任何异常都不许影响主流程（护栏失败静默降级）。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = ROOT / "logs" / "model_ledger.json"
_MAX_ENTRIES_PER_BUCKET = 50   # 滚动衰减：每桶最多保留条数
_MIN_ATTEMPTS = 2              # 至少这么多样本才参与排名

_lock = threading.Lock()


def _load() -> dict:
    try:
        return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = LEDGER_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(LEDGER_PATH)
    except Exception:
        pass


def record(task_type: str, model: str, ok: bool, tokens: int = 0) -> None:
    """回写一次尝试结果。任何异常静默（台账绝不弄垮主流程）。"""
    try:
        with _lock:
            data = _load()
            bucket = data.setdefault(task_type, {}).setdefault(model, [])
            bucket.append({"ok": bool(ok), "tokens": int(tokens),
                           "ts": time.time()})
            del bucket[:-_MAX_ENTRIES_PER_BUCKET]
            _save(data)
    except Exception:
        pass


def recommend(task_type: str, exclude: tuple[str, ...] = (),
              min_attempts: int = _MIN_ATTEMPTS) -> list[str]:
    """该任务类型的模型榜（战绩最好在前）。样本不足的模型不上榜。"""
    try:
        with _lock:
            data = _load()
        bucket = data.get(task_type) or {}
        scored = []
        for model, entries in bucket.items():
            if model in exclude or len(entries) < min_attempts:
                continue
            passes = sum(1 for e in entries if e.get("ok"))
            scored.append((passes / len(entries), -len(entries), model))
        scored.sort(reverse=True)
        return [m for _rate, _neg, m in scored]
    except Exception:
        return []
