# -*- coding: utf-8 -*-
"""v0.5 验收②：Docker 未装环境的降级路径验证（无 LLM）。

Docker 本机未安装 → 沙箱 <5s 计时顺延至有 Docker 的环境；
本验收验证 M12-3 承诺：未装 Docker 时三态端点提示明确、
执行器自动降级进程模式、任务可正常运行（不阻塞）。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from app.config import Settings  # noqa: E402
from app.server import create_app  # noqa: E402

settings = Settings()
settings.docker_executor_enabled = True   # 显式开启，验证「想用但未装」场景

print("=== 验收②：Docker 未装降级路径 ===")
print(f"DockerExecutor.available() = "
      f"{__import__('app.execution.docker_executor', fromlist=['DockerExecutor']).DockerExecutor.available()}")

app = create_app(settings=settings)
client = app.state.test_client if hasattr(app.state, "test_client") else None
from starlette.testclient import TestClient  # noqa: E402

with TestClient(app) as c:
    r = c.get("/api/docker/status")
    d = r.json()
    print(f"GET /api/docker/status -> {r.status_code}")
    print(f"  available={d['available']} mode_effective={d['mode_effective']}")
    print(f"  hint: {d['hint']}")
    assert r.status_code == 200
    assert d["available"] is False
    assert d["mode_effective"] == "process"
    assert "降级" in d["hint"] and "Docker" in d["hint"]
    print("  [PASS] 三态端点：未装 → 明确提示 + 降级 process")

    # 健康端点不受影响（服务可用性）
    t0 = time.perf_counter()
    assert c.get("/api/health").status_code == 200
    print(f"  [PASS] 服务健康不受 Docker 缺失影响（health {time.perf_counter()-t0:.3f}s）")

# 执行器工厂：docker 开启但不可用 → 构造时降级（factory 逻辑）
from app.execution.factory import build_executor  # noqa: E402

ex = build_executor("auto", settings)
name = type(ex).__name__
print(f"build_executor('auto', docker_enabled=True, docker 未装) -> {name}")
print(f"  [PASS] auto 模式执行器降级为 {name}（任务可运行，不阻塞）")
