"""M12-2 镜像缓存与预热（原 M2-6）：python/node 镜像 pull + 缓存校验。

预热语义（v0.5.md M12-2）：
- 已存在镜像（docker image inspect 命中）→ 跳过 pull（缓存校验，毫秒级）；
- 缺失镜像 → docker pull（首次代价，之后任务启动免去 pull 等待）；
- 返回逐镜像与总耗时（验收口径：预热后二次执行启动 <5s）。
"""

from __future__ import annotations

import subprocess
import time
from typing import Callable

CmdRunner = Callable[[list[str], int], "subprocess.CompletedProcess[str]"]


def _default_runner(cmd: list[str], timeout: int = 30):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def prewarm_images(settings, runner: CmdRunner | None = None) -> dict:
    """预热配置的 python 与 node 镜像（已存在跳过 pull），返回耗时报告。"""
    runner = runner or _default_runner
    images = [settings.docker_image, settings.docker_node_image]
    results: list[dict] = []
    for image in images:
        started = time.monotonic()
        inspect = runner(["docker", "image", "inspect", image], timeout=10)
        cached = inspect.returncode == 0
        ok, error = True, ""
        if not cached:
            pull = runner(["docker", "pull", image], timeout=600)
            ok = pull.returncode == 0
            if not ok:
                error = (
                    f"docker pull {image} 失败: "
                    f"{(pull.stderr or '').strip()[:200]}"
                )
        results.append({
            "image": image,
            "cached": cached,
            "ok": ok,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "error": error,
        })
    return {
        "images": results,
        "total_ms": sum(r["elapsed_ms"] for r in results),
        "ok": all(r["ok"] for r in results),
    }
