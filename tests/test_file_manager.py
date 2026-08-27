"""file_manager 单元测试（TDD 先行）。

依据：规格文档 v0.3.1
- 6.3 节：projects/{project_id}_{timestamp}/ 完整目录树
  （spec.md、interfaces.json、modules/、code/、tests/、changelog/、logs/、sessions/）；
- 3.5 节：代码按模块落盘 code/<module>/，公共依赖 _shared/；
- 12.3 节：modules/<module>.md 模块规格、changelog/<module>/fix_history.md 修复历史；
- 第 5 章：所有文件操作记录到 logs/；
- 安全：模块名/文件名不得逃逸项目目录（防路径穿越，确定性校验）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.tools.file_manager import FileManager


@pytest.fixture
def fm(tmp_path: Path) -> FileManager:
    return FileManager(projects_root=tmp_path / "projects")


class TestProjectCreation:
    def test_create_project_makes_required_tree(self, fm):
        project = fm.create_project("糖尿病管理智能体")
        root = project.root
        assert root.exists()
        for sub in ("modules", "code", "tests", "changelog", "logs", "sessions"):
            assert (root / sub).is_dir(), f"缺少目录 {sub}/"
        assert (root / "code" / "_shared").is_dir()
        # 6.3 节：README.md 与 .env.example 位于 code/ 下
        for f in ("spec.md", "interfaces.json"):
            assert (root / f).is_file(), f"缺少文件 {f}"
        for f in ("README.md", ".env.example"):
            assert (root / "code" / f).is_file(), f"缺少文件 code/{f}"

    def test_project_dir_name_contains_id_and_timestamp(self, fm):
        project = fm.create_project("demo")
        name = project.root.name
        assert re.match(r"^demo_\d{8}_\d{6}$", name), name

    def test_project_id_sanitized(self, fm):
        # 非法字符需清理为安全目录名（确定性校验）
        project = fm.create_project("a/b\\c:d")
        assert "/" not in project.root.name
        assert "\\" not in project.root.name
        assert ":" not in project.root.name

    def test_requirements_saved_to_sessions(self, fm):
        project = fm.create_project("demo")
        assert (project.root / "sessions" / "requirements.md").is_file()

    def test_create_log_written(self, fm):
        project = fm.create_project("demo")
        log_dir = project.root / "logs"
        logs = list(log_dir.glob("*.log"))
        assert logs, "项目创建应写入首条日志"

    def test_project_under_projects_root(self, fm):
        project = fm.create_project("demo")
        assert project.root.parent == fm.projects_root


class TestReadProject:
    def test_get_project_returns_existing(self, fm):
        created = fm.create_project("demo")
        found = fm.get_project(created.project_id)
        assert found is not None
        assert found.root == created.root

    def test_get_project_missing_returns_none(self, fm):
        assert fm.get_project("no-such-id") is None


class TestFileReadWrite:
    def test_write_and_read_module_spec(self, fm):
        project = fm.create_project("demo")
        fm.write_module_spec(project.project_id, "news_query", "# 规格")
        path = project.root / "modules" / "news_query.md"
        assert path.is_file()
        assert fm.read_file(project.project_id, "modules/news_query.md") == "# 规格"

    def test_write_code_files_under_module(self, fm):
        project = fm.create_project("demo")
        fm.write_code_file(project.project_id, "news_query", "main.py", "print('hi')")
        assert (project.root / "code" / "news_query" / "main.py").is_file()

    def test_write_test_file(self, fm):
        project = fm.create_project("demo")
        fm.write_test_file(project.project_id, "news_query", "test_main.py", "# tests")
        assert (project.root / "tests" / "news_query" / "test_main.py").is_file()

    def test_append_fix_history(self, fm):
        project = fm.create_project("demo")
        fm.append_fix_history(project.project_id, "news_query", "第 1 轮修复：xxx")
        fm.append_fix_history(project.project_id, "news_query", "第 2 轮修复：yyy")
        path = project.root / "changelog" / "news_query" / "fix_history.md"
        text = path.read_text(encoding="utf-8")
        assert "第 1 轮修复" in text and "第 2 轮修复" in text

    def test_write_interfaces_json(self, fm):
        project = fm.create_project("demo")
        fm.write_json(project.project_id, "interfaces.json", {"shared_exports": []})
        assert (project.root / "interfaces.json").is_file()

    def test_read_missing_file_returns_none(self, fm):
        project = fm.create_project("demo")
        assert fm.read_file(project.project_id, "modules/none.md") is None

    def test_file_ops_logged(self, fm):
        # 第 5 章：文件操作记录到 logs/
        project = fm.create_project("demo")
        fm.write_module_spec(project.project_id, "news_query", "# x")
        log_text = "\n".join(
            p.read_text(encoding="utf-8") for p in (project.root / "logs").glob("*.log")
        )
        assert "news_query.md" in log_text


class TestPathSafety:
    def test_module_name_traversal_rejected(self, fm):
        project = fm.create_project("demo")
        with pytest.raises(ValueError, match="模块名"):
            fm.write_code_file(project.project_id, "../evil", "main.py", "x")

    def test_relative_path_traversal_rejected(self, fm):
        project = fm.create_project("demo")
        with pytest.raises(ValueError, match="路径"):
            fm.read_file(project.project_id, "../outside.txt")

    def test_absolute_path_rejected(self, fm):
        project = fm.create_project("demo")
        with pytest.raises(ValueError, match="路径"):
            fm.read_file(project.project_id, "C:/windows/win.ini")

    def test_filename_traversal_rejected(self, fm):
        project = fm.create_project("demo")
        with pytest.raises(ValueError):
            fm.write_code_file(project.project_id, "news_query", "../evil.py", "x")

    def test_unknown_project_rejected(self, fm):
        with pytest.raises(ValueError, match="项目"):
            fm.read_file("ghost", "spec.md")
