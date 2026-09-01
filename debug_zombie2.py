"""精确镜像测试顺序：app 先建 → 写僵尸文件 → GET。"""

import json
import sys
import tempfile
from pathlib import Path

sys_path = Path(__file__).resolve().parent
sys.path.insert(0, str(sys_path))
sys.path.insert(0, str(sys_path.parent))

from fastapi.testclient import TestClient

from app.config import Settings
from app.server import create_app
from app.tools.file_manager import FileManager
from tests.test_task_cancel import _SlowLLMFactory, _SkippedExecutorFactory

tmp = Path(tempfile.mkdtemp(prefix="tb-z2-"))
app = create_app(
    settings=Settings(),
    projects_root=tmp / "projects",
    llm_factory=_SlowLLMFactory(),
    executor=_SkippedExecutorFactory(),
)

fm = FileManager(projects_root=tmp / "projects")
pid = fm.create_project("僵尸项目").project_id
root = fm.get_project(pid).root
(root / "sessions").mkdir(parents=True, exist_ok=True)
(root / "sessions" / "task_state.json").write_text(json.dumps({
    "task_id": "zombie-running", "kind": "run", "status": "running",
    "project_id": pid, "project_dir": str(root),
    "tokens_used": 123, "stage": "模块开发",
}, ensure_ascii=False), encoding="utf-8")

tc = TestClient(app)
resp = tc.get("/api/tasks/zombie-running")
print("HTTP", resp.status_code)
print(json.dumps(resp.json(), ensure_ascii=False)[:400])

# 直接验证磁盘文件与 TaskManager 的 projects_root
tm = app.state.task_manager
print("tm.projects_root:", tm._projects_root)
print("glob 结果:", [str(p) for p in tm._projects_root.glob("*/sessions/task_state.json")])
print("磁盘文件存在:", (root / "sessions" / "task_state.json").exists())
