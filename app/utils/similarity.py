"""讨论循环检测（规格文档 11.3 节、第 17 章第三阶段任务）。

设计原则（11.3）：由程序负责判定，LLM 不自我判断。

双层检测（先廉后贵）：
1) 文本相似度首道拦截（零依赖）：论点分词 Jaccard 重合度 > 阈值 → 字面重复；
2) embedding 语义拦截（第二道）：首道未命中时余弦相似度 > 阈值 → 语义重复。
   MVP 采用 A 案（零依赖文本相似度），embedding 经 set_embedder 注入，
   统一走同一套检测接口（6.1 节：两案共用同一模块接口）。

检测粒度：按「关键论点」切分（编号列表 / 分号 / 句号），
仅对「这一轮新出现的论点」做检测（增量比对，历史不重复计算）。

判定与打断：同一论点重复计数 < N 仅记录；≥ N 次冻结副 LLM 发言权
（verdict.frozen = True），由主 LLM 收权做最终裁决。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Protocol

from app.config import Settings

# 论点切分：编号列表项、分号、句号
_BULLET = re.compile(r"^\s*(?:\d+[\.、)]|[-*•]|[一二三四五六七八九十]+[、.])\s*")

# 噪声论点过滤：过短或纯应答词（11.3「过碎不比」）
_NOISE = re.compile(r"^\s*(同意|不同意|好的|好|是|否|明白|了解|[\.、,，;；!！?？\s]*)\s*$")

_MIN_ARGUMENT_CHARS = 4


class Embedder(Protocol):
    """embedding 注入接口（11.3 第二道；A 案下缺省为 None）。"""

    def embed(self, text: str) -> list[float]: ...


@dataclass
class LoopVerdict:
    """单轮检测结论。"""

    frozen: bool                       # 是否冻结副 LLM 发言权
    frozen_reason: str = ""
    # 论点指纹 → 已重复次数（仅本轮出现过的论点）
    repeat_counts: dict[str, int] = field(default_factory=dict)


def jaccard(a: str, b: str) -> float:
    """分词后 Jaccard 重合度（零依赖：中文按 bigram、西文按词）。"""
    sa, sb = _tokenize(a), _tokenize(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _tokenize(text: str) -> set[str]:
    """零依赖分词：提取 CJK 连续段做 bigram，其余按非字母数字边界切词。"""
    tokens: set[str] = set()
    for cjk in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(cjk) == 1:
            tokens.add(cjk)
        else:
            tokens.update(cjk[i : i + 2] for i in range(len(cjk) - 1))
    for word in re.findall(r"[A-Za-z0-9_]+", text):
        tokens.add(word.lower())
    return tokens


class LoopDetector:
    """论点级循环检测器（程序判定，11.3）。

    M4-2 论点库持久化（opt-in）：library_path 给定时，论点文本与向量
    跨任务复用——预载论点在本任务首次复现视为首次入库（计数归零，
    冻结语义与不预载完全一致，见 config M4-2 注释）；加速体现在
    第二道 embedding 比对（向量直接命中，零 embed 调用）。
    """

    def __init__(self, settings: Settings, library_path: str | None = None):
        self.settings = settings
        self._embedder: Embedder | None = None
        # 论点指纹 → {count: 重复次数, vec: 向量缓存, seeded: 是否库预载}
        self._history: dict[str, dict] = {}
        self._frozen = False
        # 11.0：省 token 模式（预算 ≥90%）→ 跳过第二道 embedding 比对
        self.throttling: bool = False
        # M4-2：论点库（None = 不持久化）
        self._library_path = library_path
        self._library_dirty = False
        if library_path:
            self._load_library()

    # ------------------------------------------------------------------

    def set_embedder(self, embedder: Embedder) -> None:
        """注入第二道 embedding 实现（6.1：经 model_client 统一封装）。"""
        self._embedder = embedder

    def reset(self) -> None:
        """重置状态（冻结解除、历史清空；用于新项目/新讨论）。

        论点库文件不删除（跨任务资产，M4-2）；仅清空本任务内存状态。
        """
        self._history.clear()
        self._frozen = False

    def check(self, message: str) -> LoopVerdict:
        """检测一轮发言：切分论点 → 逐论点比对历史 → 更新计数与冻结状态。"""
        if self._frozen:
            return LoopVerdict(frozen=True, frozen_reason="已冻结（历史触发）")

        counts: dict[str, int] = {}
        inserted = False
        for argument in self._split_arguments(message):
            fingerprint, repeated, vec = self._match_history(argument)
            if repeated is not None:
                record = self._history[fingerprint]
                if record.pop("seeded", False):
                    # M4-2：库预载论点本任务首次复现 → 等价首次入库
                    #（计数归零，不计入重复；冻结语义与不预载完全一致）
                    record["count"] = 0
                    if record.get("vec") is None and vec is not None:
                        record["vec"] = vec
                    continue
                record["count"] += 1
                counts[fingerprint] = record["count"]
                if record["count"] >= self.settings.loop_repeat_limit:
                    self._frozen = True
                    return LoopVerdict(
                        frozen=True,
                        frozen_reason=(
                            f"论点「{argument[:30]}…」重复达 "
                            f"{self.settings.loop_repeat_limit} 次，冻结副 LLM 发言权，"
                            "由主 LLM 收权裁决（11.3）"
                        ),
                        repeat_counts=counts,
                    )
            else:
                # 新论点入库（缓存向量，11.3 缓存与增量；比对时已算出的向量直接复用）
                self._history[fingerprint] = {
                    "count": 0,
                    "text": argument,
                    "vec": vec if vec is not None else self._embed(argument),
                }
                inserted = True
        if inserted:
            self._save_library()
        return LoopVerdict(frozen=False, repeat_counts=counts)

    # ------------------------------------------------------------------

    def _split_arguments(self, text: str) -> list[str]:
        """按编号/分号/句号切分论点，过滤噪声。"""
        raw: list[str] = []
        # 先按编号列表切（保留项内容）
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        bullets = [ln for ln in lines if _BULLET.match(ln)]
        if bullets:
            raw = [_BULLET.sub("", ln) for ln in bullets]
        else:
            # 按分号/句号切
            parts = re.split(r"[；;。]", text)
            raw = [p.strip() for p in parts if p.strip()]
        return [a for a in (p.strip("：: ,，") for p in raw)
                if len(a) >= _MIN_ARGUMENT_CHARS and not _NOISE.match(a)]

    def _match_history(self, argument: str) -> tuple[str, str | None, list[float] | None]:
        """比对历史论点库。

        Returns:
            (指纹, 命中的历史论点指纹或 None, 本轮计算的向量或 None)。
            未命中时指纹为该论点自身键；向量供入库复用（11.3 缓存）。
        """
        tokens = _tokenize(argument)
        # 第一道：Jaccard 字面重复（先廉）
        for fp, record in self._history.items():
            historical = _tokenize(record["text"])
            if tokens and historical:
                overlap = len(tokens & historical) / len(tokens | historical)
                if overlap > self.settings.jaccard_threshold:
                    return fp, fp, None

        # 第二道：embedding 语义重复（后贵，仅注入且未节流时启用）
        if self._embedder is not None and not self.throttling:
            vec = self._embed(argument)
            for fp, record in self._history.items():
                cached = record["vec"]
                if cached is not None and _cosine(vec, cached) > self.settings.similarity_threshold:
                    return fp, fp, None
            return argument, None, vec  # 向量回传入库复用（避免二次 embed）

        return argument, None, None

    def _embed(self, text: str) -> list[float] | None:
        if self._embedder is None or self.throttling:
            return None
        return self._embedder.embed(text)

    # ------------------------------------------------------------------
    # M4-2 论点库持久化
    # ------------------------------------------------------------------

    def _load_library(self) -> None:
        """载入历史论点（全部标记 seeded：计数不跨任务，冻结语义不变）。"""
        import json
        from pathlib import Path

        path = Path(self._library_path)
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return  # 损坏库文件 → 视为空库（不阻塞讨论）
        for item in data.get("arguments", []):
            text = item.get("text", "")
            if len(text) < _MIN_ARGUMENT_CHARS:
                continue
            self._history[text] = {
                "count": 0,
                "text": text,
                "vec": item.get("vec"),
                "seeded": True,
            }

    def _save_library(self) -> None:
        """落盘论点库（去重、上限保留最新；损坏/失败静默——检测不因库失败中断）。"""
        import json
        from pathlib import Path

        if not self._library_path:
            return
        entries = [
            {"text": rec["text"], "vec": rec.get("vec")}
            for rec in self._history.values()
            if len(rec["text"]) >= _MIN_ARGUMENT_CHARS
        ]
        entries = entries[-self.settings.loop_library_max_entries:]
        try:
            Path(self._library_path).write_text(
                json.dumps({"arguments": entries}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass  # 库写失败不影响讨论主流程


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
