"""M14-1 _shared 符号级合并守卫测试（v1.0 V0 批次）。

场景来源：v0.5 真实验收——book_validator 依赖 `_shared.utils.validate_isbn`，
后续模块输出的 _shared/utils.py 只含自己上下文的函数，整文件覆盖写入
导致 validate_isbn 丢失、跨模块 import 断裂（shared_check 未拦截）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tools.file_manager import FileManager  # noqa: E402
from app.utils.shared_merge import (  # noqa: E402
    MergeReport,
    merge_shared_source,
)

# v0.5 真实事故场景的最小化复现素材
OLD_UTILS = '''\
"""共享工具（第一模块写入：含 ISBN 校验）。"""


def validate_isbn(isbn: str) -> bool:
    """校验 ISBN-13。"""
    return len(isbn.replace("-", "")) == 13


def validate_date(date: str) -> bool:
    """校验日期格式 YYYY-MM-DD。"""
    return len(date) == 10 and date[4] == date[7] == "-"
'''

NEW_UTILS_LOST = '''\
"""共享工具（第二模块写入：只知道自己上下文的格式化函数）。"""


def format_title(title: str) -> str:
    return title.strip().title()


def format_author(author: str) -> str:
    return author.strip()
'''


class TestMergeSharedSource:
    """纯函数层：merge_shared_source 三态 + DELETED + 语法回退。"""

    def test_lost_symbol_kept(self):
        """新版静默丢失旧符号 → 自动保留（核心场景）。"""
        merged, report = merge_shared_source(OLD_UTILS, NEW_UTILS_LOST)
        assert sorted(report.kept_symbols) == ["validate_date", "validate_isbn"]
        assert not report.updated_symbols
        assert not report.deleted_symbols
        # 合并结果可解析且四个符号全部存在
        compile(merged, "<merged>", "exec")
        for name in ("validate_isbn", "validate_date",
                     "format_title", "format_author"):
            assert f"def {name}" in merged, name

    def test_kept_symbol_source_is_old_version(self):
        """保留符号保持旧版原文（含 docstring），不做语法拼装。"""
        merged, _ = merge_shared_source(OLD_UTILS, NEW_UTILS_LOST)
        assert "校验 ISBN-13" in merged          # 旧 docstring 原样保留
        assert "由合并守卫保留" in merged          # 分隔标记可审计

    def test_same_name_change_uses_new(self):
        """同名符号内容变更 → 采用新版（LLM 显式修改意图优先）。"""
        new = OLD_UTILS.replace("== 13", "== 14")   # 修改 validate_isbn
        merged, report = merge_shared_source(OLD_UTILS, new)
        assert report.updated_symbols == ["validate_isbn"]
        assert not report.kept_symbols
        assert "== 14" in merged and "== 13" not in merged

    def test_identical_content_no_merge(self):
        """内容未变 → 零合并动作。"""
        _, report = merge_shared_source(OLD_UTILS, OLD_UTILS)
        assert not report.merged
        assert not report.fallback_overwrite

    def test_explicit_deleted_marker(self):
        """`# DELETED: <name>` 显式标记 → 允许从旧版移除。"""
        new = (
            "# DELETED: validate_isbn, validate_date\n"
            + NEW_UTILS_LOST
        )
        merged, report = merge_shared_source(OLD_UTILS, new)
        assert sorted(report.deleted_symbols) == [
            "validate_date", "validate_isbn",
        ]
        assert not report.kept_symbols
        assert "def validate_isbn" not in merged

    def test_deleted_marker_case_insensitive(self):
        """标记大小写不敏感（# deleted: 同样生效）。"""
        new = "# deleted: validate_isbn\n" + NEW_UTILS_LOST
        _, report = merge_shared_source(OLD_UTILS, new)
        assert report.deleted_symbols == ["validate_isbn"]
        assert report.kept_symbols == ["validate_date"]   # 未标记的仍保留

    def test_syntax_error_fallback_overwrite(self):
        """新版语法错误 → 整文件覆盖回退（守卫不阻塞，门禁兜底）。"""
        broken = "def broken(:\n    pass\n"
        merged, report = merge_shared_source(OLD_UTILS, broken)
        assert report.fallback_overwrite
        assert merged == broken

    def test_old_syntax_error_fallback(self):
        """旧版语法错误（异常现场）→ 同样回退覆盖。"""
        merged, report = merge_shared_source("def broken(:", NEW_UTILS_LOST)
        assert report.fallback_overwrite
        assert merged == NEW_UTILS_LOST

    def test_class_and_constant_symbols(self):
        """类与常量赋值参与合并（多目标/解包赋值均计入）。"""
        old = (
            "class Config:\n    x = 1\n\n"
            "MAX = 10\n\nA, B = 1, 2\n\ndef f():\n    pass\n"
        )
        new = "def g():\n    pass\n"
        merged, report = merge_shared_source(old, new)
        assert sorted(report.kept_symbols) == ["A", "B", "Config", "MAX", "f"]
        assert "class Config" in merged and "MAX = 10" in merged


class TestFileManagerGuard:
    """集成层：write_shared_file 经 FileManager 落盘的守卫生效。"""

    @pytest.fixture()
    def fm(self, tmp_path):
        return FileManager(projects_root=tmp_path / "projects")

    @staticmethod
    def _shared_file(fm: FileManager, pid: str) -> Path:
        handle = fm.get_project(pid)
        return handle.root / "code" / "_shared" / "utils.py"

    def test_write_shared_preserves_lost_symbol(self, fm):
        """v0.5 事故链路重放：第二次写入丢 validate_isbn → 落盘仍保留。"""
        pid = fm.create_project("book-cli").project_id
        fm.write_shared_file(pid, "utils.py", OLD_UTILS)
        fm.write_shared_file(pid, "utils.py", NEW_UTILS_LOST)

        on_disk = self._shared_file(fm, pid).read_text(encoding="utf-8")
        # 断裂根因消除：新旧符号共存
        assert "def validate_isbn" in on_disk
        assert "def format_title" in on_disk

    def test_write_shared_deleted_via_marker(self, fm):
        """显式 DELETED 标记经 FileManager 生效（符号真正移除）。"""
        pid = fm.create_project("book-cli").project_id
        fm.write_shared_file(pid, "utils.py", OLD_UTILS)
        fm.write_shared_file(
            pid, "utils.py",
            "# DELETED: validate_isbn\n" + NEW_UTILS_LOST,
        )
        on_disk = self._shared_file(fm, pid).read_text(encoding="utf-8")
        assert "def validate_isbn" not in on_disk
        assert "def validate_date" in on_disk     # 未标记 → 保留

    def test_write_shared_syntax_fallback_keeps_old_flow(self, fm):
        """语法回退不阻塞：破碎内容整文件覆盖（门禁兜底语义）。"""
        pid = fm.create_project("book-cli").project_id
        fm.write_shared_file(pid, "utils.py", OLD_UTILS)
        fm.write_shared_file(pid, "utils.py", "def broken(:\n")
        on_disk = self._shared_file(fm, pid).read_text(encoding="utf-8")
        assert on_disk == "def broken(:\n"

    def test_merge_report_logged(self, fm):
        """合并动作写入项目日志（审计可查）。"""
        pid = fm.create_project("book-cli").project_id
        fm.write_shared_file(pid, "utils.py", OLD_UTILS)
        fm.write_shared_file(pid, "utils.py", NEW_UTILS_LOST)
        handle = fm.get_project(pid)
        log_text = "".join(
            f.read_text(encoding="utf-8")
            for f in sorted((handle.root / "logs").glob("*.log"))
        )
        assert "合并守卫" in log_text
        assert "validate_isbn" in log_text


class TestMergeReportShape:
    def test_report_defaults(self):
        r = MergeReport()
        assert r.merged is False
        assert r.fallback_overwrite is False
