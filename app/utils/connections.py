"""v1.1 C1 连接注册表：用户在前端添加的模型连接（name/base_url/api_key/models）。

设计锚点（v1.1-workplan C1）：
- 密钥只写不读：列表接口永远返回掩码；密钥仅落服务端本地文件
  secrets.local.json（.gitignore 覆盖），绝不进入 config.json、日志、
  项目产物与任何返回体；
- 运行时解析热加载：ModelClient 每次调用前按模型名实时查连接（文件小，
  直读成本相对秒级 LLM 调用可忽略），命中则以连接的 base_url/api_key
  发起调用，未命中回落环境变量——新增连接免重启；
- 单一事实源：可用模型全集 = config.json 预设 ∪ 各连接 models，
  由 server 在连接增删时同步回 settings.models（TeamBuilder 校验零改动）；
- 探测/解析失败一律降级（返回 None 走环境变量路径），不阻断主管线。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

_STORE_VERSION = 1


def mask_key(key: str) -> str:
    """密钥掩码（后端单一事实源；前端展示层直接消费）。"""
    key = key or ""
    if len(key) <= 8:
        return "****"
    return f"{key[:5]}****{key[-4:]}"


def masked(conn: dict) -> dict:
    """返回掩码后的连接视图（绝不携带明文 api_key）。"""
    return {
        "id": conn.get("id", ""),
        "name": conn.get("name", ""),
        "base_url": conn.get("base_url", ""),
        "models": list(conn.get("models", [])),
        "api_key": mask_key(conn.get("api_key", "")),
        "created_at": conn.get("created_at", ""),
    }


class ConnectionStore:
    """本地连接注册表（secrets.local.json，写入后收紧文件权限）。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    # ---- 持久化 ----

    def load(self) -> list[dict]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            conns = raw.get("connections", [])
            return conns if isinstance(conns, list) else []
        except Exception:
            return []  # 损坏/不存在 → 空表（行为兼容，不阻断启动）

    def _save(self, conns: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"version": _STORE_VERSION, "connections": conns},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            import os
            os.chmod(self.path, 0o600)  # POSIX 收紧；Windows 忽略失败
        except Exception:
            pass

    # ---- CRUD ----

    def add(self, name: str, base_url: str, api_key: str,
            models: list[str]) -> dict:
        if not name.strip():
            raise ValueError("连接名称不能为空")
        if not api_key.strip():
            raise ValueError("API Key 不能为空")
        models = [m.strip() for m in models if m and m.strip()]
        if not models:
            raise ValueError("至少填写一个模型名")
        conn = {
            "id": uuid.uuid4().hex[:12],
            "name": name.strip(),
            "base_url": (base_url or "").strip(),
            "api_key": api_key.strip(),
            "models": models,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        conns = self.load()
        conns.append(conn)
        self._save(conns)
        return conn

    def delete(self, cid: str) -> bool:
        conns = self.load()
        remaining = [c for c in conns if c.get("id") != cid]
        if len(remaining) == len(conns):
            return False
        self._save(remaining)
        return True

    def get(self, cid: str) -> dict | None:
        for c in self.load():
            if c.get("id") == cid:
                return c
        return None

    def all(self) -> list[dict]:
        return self.load()

    # ---- 解析 ----

    def find_by_model(self, model: str) -> dict | None:
        for c in self.load():
            if model in (c.get("models") or []):
                return c
        return None

    def all_models(self) -> list[str]:
        seen: list[str] = []
        for c in self.load():
            for m in c.get("models") or []:
                if m not in seen:
                    seen.append(m)
        return seen


def registry_models(presets: list[str], store: "ConnectionStore") -> list[str]:
    """可用模型全集 = 预设 ∪ 各连接 models（保序去重）。"""
    out = list(presets)
    for m in store.all_models():
        if m not in out:
            out.append(m)
    return out


# ---- 进程级默认单例（server 启动时 set_path；ModelClient 调用时直读） ----

_default_store: ConnectionStore | None = None


def set_store(path: str | Path) -> None:
    global _default_store
    _default_store = ConnectionStore(path)


def get_store() -> ConnectionStore:
    global _default_store
    if _default_store is None:
        _default_store = ConnectionStore("secrets.local.json")
    return _default_store


def resolve_credentials(model: str) -> dict | None:
    """按模型名解析连接凭据；未命中/异常返回 None（调用方回落环境变量）。"""
    try:
        conn = get_store().find_by_model(model)
        if conn is None:
            return None
        return {
            "api_key": conn.get("api_key", ""),
            "base_url": conn.get("base_url", ""),
            "name": conn.get("name", ""),
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# v1.1 C2:探针验证 + 模型自动发现
# ---------------------------------------------------------------------------

_VERDICT_MARKERS = (
    ("auth_failed", ("401", "403", "unauthorized", "invalid api key",
                     "invalid_api_key", "authentication", "permission denied",
                     "invalid x-api-key", "unauthenticated")),
    ("model_not_found", ("model_not_found", "model not found",
                         "does not exist", "404", "no matching")),
    ("rate_limited", ("429", "rate limit", "ratelimit", "quota",
                      "insufficient", "balance", "arrears", "欠费")),
    ("network_error", ("timeout", "timed out", "connection", "connect",
                       "resolve", "getaddrinfo", "unreachable", "ssl",
                       "network")),
)


def probe_connection(conn: dict, model: str | None = None,
                     completion_fn=None) -> dict:
    """连接探针(C2):用连接自身的凭据发一次微型真实调用。

    3 秒级告诉用户 Key/地址/模型名是否可用。直接使用连接凭据(litellm
    per-call 参数),不经 ModelClient——不进任务预算、不进调用日志、
    不污染成本报告。verdict: ok | auth_failed | model_not_found |
    rate_limited | network_error | error。
    completion_fn 可注入(测试桩)。
    """
    models = conn.get("models") or []
    target = model or (models[0] if models else "")
    if not target:
        return {"ok": False, "verdict": "error", "latency_ms": 0,
                "model": "", "detail": "连接未配置模型,无法探针"}
    t0 = time.time()
    try:
        fn = completion_fn
        if fn is None:
            try:
                import litellm
            except ImportError as exc:
                raise RuntimeError(f"litellm 未安装: {exc}") from exc
            fn = litellm.completion
        kwargs = {"model": target,
                  "messages": [{"role": "user", "content": "ping"}],
                  "max_tokens": 8, "timeout": 20}
        if conn.get("base_url"):
            kwargs["base_url"] = conn["base_url"]
        if conn.get("api_key"):
            kwargs["api_key"] = conn["api_key"]
        fn(**kwargs)
        return {"ok": True, "verdict": "ok",
                "latency_ms": int((time.time() - t0) * 1000),
                "model": target, "detail": "连通正常"}
    except Exception as exc:
        text = f"{type(exc).__name__} {exc}"
        low = text.lower()
        verdict = "error"
        for v, markers in _VERDICT_MARKERS:
            if any(m in low for m in markers):
                verdict = v
                break
        return {"ok": False, "verdict": verdict,
                "latency_ms": int((time.time() - t0) * 1000),
                "model": target, "detail": text[:200]}


def discover_models(base_url: str, api_key: str,
                    http_get=None) -> dict:
    """模型自动发现(C2):对 OpenAI 兼容端点拉取 {base}/models 清单。

    http_get(url, api_key) -> dict 可注入(测试桩);默认 urllib。
    失败返回 {"ok": False, "models": [], "detail": ...},前端回落手动输入。
    """
    base = (base_url or "").rstrip("/")
    if not base:
        return {"ok": False, "models": [], "detail": "缺少 Base URL"}
    url = base + "/models"

    def _default_get(u: str, key: str) -> dict:
        import urllib.request
        req = urllib.request.Request(
            u, headers={"Authorization": f"Bearer {key}",
                        "User-Agent": "token-burner"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))

    getter = http_get or _default_get
    try:
        data = getter(url, api_key)
        items = data.get("data", []) if isinstance(data, dict) else []
        ids = [m.get("id") for m in items if isinstance(m, dict) and m.get("id")]
        return {"ok": True, "models": ids}
    except Exception as exc:
        return {"ok": False, "models": [], "detail": str(exc)[:200]}
