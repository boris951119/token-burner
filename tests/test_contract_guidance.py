"""M15-1/M15-2 契约风格约束与门禁修改指导测试（v1.0 V1 批次）。

场景来源：v0.5 真实验收——file_utils 契约声明函数式 API（read_file 等
12 个导出），LLM 坚持生成类式实现（FileManager/FileEncryptor 等），
门禁报告只有 missing/extra 清单无修改指导，5 轮修复不收敛 → FROZEN。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.utils.interface_check import check_implementation  # noqa: E402

# v0.5 事故的最小化复现：函数式契约 vs 类式实现
FUNC_CONTRACT = {
    "exports": ["read_file", "write_file", "delete_file"],
    "public_api": [
        "read_file(path) -> str",
        "write_file(path, content) -> bool",
        "delete_file(path) -> bool",
    ],
    "imports": [],
    "dependencies": [],
}

CLASS_IMPL = '''\
class FileManager:
    """v0.5 事故形态：把契约 API 全收进类里。"""

    def __init__(self, root):
        self.root = root

    def read_file(self, path):
        return open(self.root / path).read()

    def write_file(self, path, content):
        return True

    def delete_file(self, path):
        return True
'''


class TestGuidanceContent:
    def test_missing_has_signature_template(self):
        """missing 指导含契约 public_api 原文签名模板。"""
        issues = check_implementation("file_utils", CLASS_IMPL, FUNC_CONTRACT)
        missing = [i for i in issues if i.kind == "missing"]
        assert len(missing) == 3
        read_issue = next(i for i in missing if "read_file" in i.detail)
        assert "def read_file(path) -> str" in read_issue.guidance
        assert "顶层" in read_issue.guidance
        assert "禁止封装成类" in read_issue.guidance

    def test_extra_has_disposition_guidance(self):
        """extra 指导给处置二选一（补声明 or 改私有/删除）。"""
        issues = check_implementation("file_utils", CLASS_IMPL, FUNC_CONTRACT)
        extra = next(i for i in issues if i.kind == "extra"
                     and "FileManager" in i.detail)
        assert "二选一" in extra.guidance
        assert "_FileManager" in extra.guidance    # 私有化路径

    def test_missing_no_public_api_falls_back_params(self):
        """无 public_api 时按 exports 参数生成模板。"""
        contract = {"exports": ["parse(path, strict)"], "public_api": [],
                    "imports": [], "dependencies": []}
        issues = check_implementation("m", "def other():\n    pass\n", contract)
        miss = next(i for i in issues if i.kind == "missing")
        assert "def parse(path, strict)" in miss.guidance

    def test_bare_export_guidance_is_constant(self):
        """裸名导出（无参数）指导为常量定义。"""
        contract = {"exports": ["MAX_SIZE"], "public_api": [],
                    "imports": [], "dependencies": []}
        issues = check_implementation("m", "def f():\n    pass\n", contract)
        miss = next(i for i in issues if i.kind == "missing")
        assert "常量" in miss.guidance and "MAX_SIZE = ..." in miss.guidance

    def test_compliant_implementation_no_issues(self):
        """按指导修复后的实现（顶层函数）→ 零 issue（收敛路径）。"""
        fixed = '''\
def read_file(path) -> str:
    return open(path).read()


def write_file(path, content) -> bool:
    return True


def delete_file(path) -> bool:
    return True
'''
        issues = check_implementation("file_utils", fixed, FUNC_CONTRACT)
        assert issues == []

    def test_signature_mismatch_warning_with_guidance(self):
        """签名不匹配（警告级）也附对齐建议。"""
        contract = {
            "exports": ["add(a, b)"],
            "public_api": ["add(a, b) -> int"],
            "imports": [], "dependencies": [],
        }
        code = "def add(x, y):\n    return x + y\n"
        issues = check_implementation("m", code, contract)
        warn = next(i for i in issues if i.kind == "signature_mismatch")
        assert warn.severity == "warning"
        assert "def add(a, b) -> int" in warn.guidance


class TestStylePromptConstraints:
    """M15-1：提示词文件含风格约束（拆分/写码双侧对齐）。"""

    def test_interface_system_has_style_rule(self):
        from app.tools.prompt_templates import INTERFACE_SYSTEM

        assert "顶层" in INTERFACE_SYSTEM
        assert "不要封装成类" in INTERFACE_SYSTEM
        assert "FileManager" in INTERFACE_SYSTEM     # 反例

    def test_write_code_system_has_style_rule(self):
        from app.tools.prompt_templates import WRITE_CODE_SYSTEM

        assert "顶层" in WRITE_CODE_SYSTEM
        assert "类或类方法" in WRITE_CODE_SYSTEM
