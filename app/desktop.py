"""桌面客户端模式（pywebview 原生窗口 + js_api 进程内桥接）。

v3 架构（重要变更——本地网络拦截问题的彻底规避）：

  v1/v2（已废弃）：exe 父进程 + uvicorn 子进程，WebView 加载
    http://127.0.0.1:<port>/。问题：安全软件（如火绒 HIPS）会拦截
    未签名 exe 的本地网络活动——bind/listen 正常，但回环 connect 的
    SYN 被内核层丢弃。asyncio Proactor 初始化自管道（Windows 用回环
    TCP 模拟 socketpair）时即挂死，且外部对监听端口的连接同样进不来
    （实测 dev Python 正常、frozen exe 全挂）。

  v3（当前）：单进程、零 socket、零端口。
    - pywebview 直接加载 client.html（html= 字符串）
    - JS 侧经 window.pywebview.api.request(method, path, body) 调用
    - Bridge 内部用 starlette TestClient 把请求进程内转发给
      FastAPI app（app.server.create_app）——ASGI 内存通道，不经网络
    - server.py 交互契约零改动；浏览器调试模式（python -m app.server
      + http://127.0.0.1:8000/）与桌面模式共用同一份 client.html

  出站 HTTPS（LLM API 调用）不受影响——实测 frozen exe 的
  https 出站完全正常，拦截仅针对本地监听/回环。

依赖：pip install pywebview（Windows 使用系统 WebView2/Edge 渲染）
"""

from __future__ import annotations

import sys
from pathlib import Path


class Bridge:
    """HTTP-over-function 桥：JS request() → TestClient 进程内转发。

    返回 {"status": int, "body": str}；JSON 解析由 JS 侧完成。
    串行锁：TestClient 非线程安全，pywebview 的 js_api 调用
    来自不同线程（长任务执行期间 UI 可能再发请求）。
    """

    def __init__(self) -> None:
        import threading

        from app.server import create_app
        from starlette.testclient import TestClient

        self._client = TestClient(create_app())
        self._lock = threading.Lock()

    def request(self, method: str, path: str, body: str | None) -> dict:
        kwargs: dict = {}
        if body is not None:
            kwargs["content"] = body.encode("utf-8")
            kwargs["headers"] = {"Content-Type": "application/json"}
        with self._lock:
            resp = self._client.request(method, path, **kwargs)
        return {"status": resp.status_code, "body": resp.text}


def _client_html() -> str:
    """client.html 定位：frozen 在 _MEIPASS 临时解压目录；dev 在项目根。"""
    if getattr(sys, "frozen", False):
        client = Path(sys._MEIPASS) / "client.html"  # type: ignore[attr-defined]
    else:
        client = Path(__file__).resolve().parent.parent / "client.html"
    return client.read_text(encoding="utf-8")


def main() -> None:
    # windowed exe 中 stdout/stderr 为 None：print 会抛 AttributeError
    if sys.stdout is None:
        import os
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        import os
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115

    import webview

    window = webview.create_window(
        title="token-burner · 文档消耗器",
        html=_client_html(),
        js_api=Bridge(),
        width=1360,
        height=880,
        min_size=(1024, 700),
    )
    webview.start()   # 阻塞至窗口关闭
    _ = window


if __name__ == "__main__":
    main()
