"""调试：僵尸清扫用例的实际响应。"""

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.server import create_app
from app.tools.file_manager import FileManager

sys_path = Path(__file__).resolve().parent
import sys  # noqa: E402
sys.path.insert(0, str(sys_path))

from tests.test_task_cancel import _SlowLLMFactory, _SkippedExecutorFactory  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="tb-zombie-"))
fm = FileManager(projects_root=tmp / "projects")
pid = fm.create_project("僵尸项目").project_id
root = fm.get_project(pid).root
(root / "sessions").mkdir(parents=True, exist_ok=True)
(root / "sessions" / "task_state.json").write_text(json.dumps({
    "task_id": "zombie-running", "kind": "run", "status": "running",
    "project_id": pid, "project_dir": str(root),
    "tokens_used": 123, "stage": "模块开发",
}, ensure_ascii=False), encoding="utf-8")

app = create_app(
    settings=Settings(),
    projects_root=tmp / "projects",
    llm_factory=_SlowLLMFactory(),
    executor=_SkippedExecutorFactory(),
)
tc = TestClient(app)
resp = tc.get("/api/tasks/zombie-running")
print("HTTP", resp.status_code)
print(json.dumps(resp.json(), ensure_ascii=False)[:600])
print("file still exists:", (root / "sessions" / "task_state.json").exists())
