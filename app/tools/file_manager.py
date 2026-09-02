"""项目目录与文件读写（规格文档 6.3 节、第 17 章第一阶段任务）。

职责：
- 创建项目目录 projects/{project_id}_{timestamp}/ 并初始化 6.3 节完整目录树；
- 管理模块规格（modules/<module>.md）、模块代码（code/<module>/）、
  测试文件（tests/<module>/）、修复历史（changelog/<module>/fix_history.md）；
- 所有文件操作写入项目 logs/（第 5 章：日志可审计）；
- 路径安全：模块名 / 相对路径 / 文件名不得逃逸项目根（确定性校验，总则 D.1）。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

# 合法模块名：字母数字下划线连字符（禁止路径分隔符与穿越符）
_SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")

# 交付物可运行性基础设施（产品审计问题 1）：
# pytest 从项目根目录运行时经 conftest 把 code/ 插入 sys.path，
# 使 tests/<module>/ 下的 `from <module> import <符号>` 可解析。
_CONFTEST_CONTENT = '''"""pytest 路径引导：把 code/ 加入 sys.path，使测试可导入项目模块。"""
import sys
from pathlib import Path

_CODE_DIR = Path(__file__).resolve().parent / "code"
if _CODE_DIR.is_dir() and str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))
'''


class ProjectHandle:
    """已创建项目的运行时句柄。"""

    def __init__(self, project_id: str, root: Path):
        self.project_id = project_id
        self.root = root


@dataclass
class _ProjectRecord:
    handle: ProjectHandle


class FileManager:
    """项目目录与文件读写的统一入口。"""

    def __init__(self, projects_root: Path | str = "projects"):
        self.projects_root = Path(projects_root)
        self._records: dict[str, _ProjectRecord] = {}

    # ------------------------------------------------------------------
    # 项目创建与查询
    # ------------------------------------------------------------------

    def create_project(self, raw_requirement: str) -> ProjectHandle:
        """创建项目目录并初始化 6.3 节目录树。

        project_id 由原始需求生成（清理非法字符、压缩空白、限长）。
        """
        project_id = self._sanitize_project_id(raw_requirement)
        timestamp = time.strftime(_TIMESTAMP_FORMAT)
        root = self.projects_root / f"{project_id}_{timestamp}"
        root.mkdir(parents=True, exist_ok=False)

        for sub in ("modules", "code/_shared", "tests", "changelog", "logs", "sessions"):
            (root / sub).mkdir(parents=True, exist_ok=True)

        _write_text(root / "spec.md", "# 项目规格（主 LLM 维护）\n")
        _write_text(root / "interfaces.json", json.dumps({
            "cross_module_symbols": [],
            "shared_exports": [],
            "allowed_third_party_imports": [],
        }, ensure_ascii=False, indent=2))
        _write_text(root / "code" / "README.md",
                    "# 运行说明\n\n（开发副 LLM 生成代码后补充安装依赖与运行方式）\n")
        _write_text(root / "code" / ".env.example", "# 环境变量模板（默认值留空）\n")
        # 交付物可运行性：pytest 路径引导（项目根 conftest.py）
        _write_text(root / "conftest.py", _CONFTEST_CONTENT)
        # 6.3 节：原始需求保存到 sessions/requirements.md
        _write_text(root / "sessions" / "requirements.md", raw_requirement + "\n")

        handle = ProjectHandle(project_id=project_id, root=root)
        self._records[project_id] = _ProjectRecord(handle)

        self._log(handle, "创建项目目录", str(root))
        self._log(handle, "保存需求", "sessions/requirements.md")
        return handle

    def get_project(self, project_id: str) -> ProjectHandle | None:
        """按 project_id 查找已创建项目；不存在返回 None。

        兼容两种跨进程形态：
        - sanitized project_id（不含时间戳）→ 按目录名前缀 `{id}_*` 扫描；
        - 完整目录名（含时间戳，/api/resumable 与 CLI 中断恢复返回此形态）
          → 精确目录匹配（真实运行回归：前缀扫描对完整名必然 miss）。
        """
        record = self._records.get(project_id)
        if record is not None:
            return record.handle
        if not self.projects_root.is_dir():
            return None
        for entry in self.projects_root.glob(f"{_glob_escape(project_id)}_*"):
            if entry.is_dir():
                handle = ProjectHandle(project_id=project_id, root=entry)
                self._records[project_id] = _ProjectRecord(handle)
                return handle
        exact = self.projects_root / project_id
        if exact.is_dir():
            handle = ProjectHandle(project_id=project_id, root=exact)
            self._records[project_id] = _ProjectRecord(handle)
            return handle
        return None

    def _require_project(self, project_id: str) -> ProjectHandle:
        handle = self.get_project(project_id)
        if handle is None:
            raise ValueError(f"项目不存在或未创建: {project_id}")
        return handle

    @staticmethod
    def _sanitize_project_id(raw: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_\-一-龥]", "_", raw.strip())
        cleaned = re.sub(r"[_\s]+", "_", cleaned).strip("_")
        return cleaned[:40] or "project"

    # ------------------------------------------------------------------
    # 文件读写（模块规格 / 代码 / 测试 / 变更记录 / 通用）
    # ------------------------------------------------------------------

    def write_module_spec(self, project_id: str, module: str, content: str) -> Path:
        handle = self._require_project(project_id)
        self._check_module_name(module)
        path = handle.root / "modules" / f"{module}.md"
        _write_text(path, content)
        self._log(handle, "写入模块规格", path.relative_to(handle.root).as_posix())
        return path

    def write_code_file(
        self, project_id: str, module: str, filename: str, content: str
    ) -> Path:
        handle = self._require_project(project_id)
        self._check_module_name(module)
        self._check_filename(filename)
        path = handle.root / "code" / module / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_text(path, content)
        # 交付物可运行性：约定文件名（<module>.py）时生成包级重导出 init，
        # 使 `from <module> import <符号>` 与 python -m <module>.<module> 可用
        if filename == f"{module}.py":
            _write_text(
                path.parent / "__init__.py",
                f"from {module}.{module} import *  # noqa: F401,F403  包级重导出\n",
            )
        self._log(handle, "写入代码文件", path.relative_to(handle.root).as_posix())
        return path

    def write_test_file(
        self, project_id: str, module: str, filename: str, content: str
    ) -> Path:
        handle = self._require_project(project_id)
        self._check_module_name(module)
        self._check_filename(filename)
        path = handle.root / "tests" / module / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_text(path, content)
        self._log(handle, "写入测试文件", path.relative_to(handle.root).as_posix())
        return path

    def write_shared_file(
        self, project_id: str, filename: str, content: str
    ) -> Path:
        """写入公共层文件 code/_shared/<filename>（12.7：公共依赖集中归口）。

        M14-1 符号级合并守卫：已有旧版时，新版静默丢失的顶层符号自动保留
        （v0.5 实测覆盖事故根因修复）；显式删除须 `# DELETED: <name>` 标记；
        语法解析失败回退整文件覆盖（接口门禁兜底）。
        内容相同则不重写（mtime 稳定，变更检测以内容为准）。
        """
        handle = self._require_project(project_id)
        self._check_filename(filename)
        path = handle.root / "code" / "_shared" / filename
        effective = content
        merge_note = ""
        if path.is_file():
            old = path.read_text(encoding="utf-8")
            if old != content:
                from app.utils.shared_merge import merge_shared_source

                merged, report = merge_shared_source(old, content)
                effective = merged
                if report.fallback_overwrite:
                    merge_note = "（语法回退：整文件覆盖）"
                elif report.merged:
                    merge_note = (
                        f"（合并守卫：保留 {report.kept_symbols}"
                        f" 变更 {report.updated_symbols}"
                        f" 删除 {report.deleted_symbols}）"
                    )
        if not (path.is_file() and path.read_text(encoding="utf-8") == effective):
            _write_text(path, effective)
        # 交付物可运行性：_shared 包标记（from _shared.<file> import <符号>）
        _write_text(path.parent / "__init__.py", "")
        self._log(
            handle, "写入公共层文件",
            path.relative_to(handle.root).as_posix() + merge_note,
        )
        return path

    def shared_signature(self, project_id: str) -> str:
        """_shared/ 目录内容签名（14.4 变更检测基线，确定性 hash）。"""
        import hashlib

        handle = self._require_project(project_id)
        shared_dir = handle.root / "code" / "_shared"
        digest = hashlib.sha256()
        if shared_dir.is_dir():
            for py in sorted(shared_dir.rglob("*")):
                if py.is_file():
                    digest.update(py.relative_to(shared_dir).as_posix().encode("utf-8"))
                    digest.update(py.read_bytes())
                    digest.update(b"\x00")
        return digest.hexdigest()

    def append_fix_history(self, project_id: str, module: str, entry: str) -> Path:
        handle = self._require_project(project_id)
        self._check_module_name(module)
        path = handle.root / "changelog" / module / "fix_history.md"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"- [{timestamp}] {entry}\n")
        self._log(handle, "追加修复记录", path.relative_to(handle.root).as_posix())
        return path

    def write_json(self, project_id: str, relative_path: str, data: Any) -> Path:
        handle = self._require_project(project_id)
        path = self._resolve(handle, relative_path)
        _write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
        self._log(handle, "写入 JSON", relative_path)
        return path

    def read_file(self, project_id: str, relative_path: str) -> str | None:
        handle = self._require_project(project_id)
        path = self._resolve(handle, relative_path)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def list_files(self, project_id: str, subdir: str) -> list[str]:
        """列出项目内某子目录下的文件（相对项目根的 posix 路径）。"""
        handle = self._require_project(project_id)
        base = self._resolve(handle, subdir)
        if not base.is_dir():
            return []
        return sorted(
            p.relative_to(handle.root).as_posix()
            for p in base.rglob("*")
            if p.is_file()
        )

    # ------------------------------------------------------------------
    # 路径安全（确定性校验）
    # ------------------------------------------------------------------

    def _resolve(self, handle: ProjectHandle, relative_path: str) -> Path:
        """解析项目内相对路径，拒绝逃逸与绝对路径。"""
        if not relative_path or Path(relative_path).is_absolute():
            raise ValueError(f"路径必须为项目内相对路径: {relative_path!r}")
        candidate = (handle.root / relative_path).resolve()
        root_resolved = handle.root.resolve()
        if not candidate.is_relative_to(root_resolved):
            raise ValueError(f"路径逃逸项目根目录: {relative_path!r}")
        return candidate

    @staticmethod
    def _check_module_name(module: str) -> None:
        if not _SAFE_NAME_PATTERN.match(module):
            raise ValueError(f"模块名仅允许字母数字下划线连字符: {module!r}")

    @staticmethod
    def _check_filename(filename: str) -> None:
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            raise ValueError(f"文件名不得包含路径分隔符或穿越符: {filename!r}")

    # ------------------------------------------------------------------
    # 日志（第 5 章：文件操作记录到 logs/）
    # ------------------------------------------------------------------

    def _log(self, handle: ProjectHandle, action: str, detail: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_dir = handle.root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "session_001.log"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {action}: {detail}\n")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _glob_escape(segment: str) -> str:
    """转义 glob 特殊字符，避免 project_id 中的字符被当作通配符。"""
    return segment.replace("[", "[[]").replace("*", "[*]").replace("?", "[?]")
