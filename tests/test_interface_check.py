"""interface_check 单元测试（TDD 先行）。

依据：规格文档 17 章第三阶段：utils/interface_check.py——
AST 抽取实际代码接口 + 三类差异判定（缺失实现 / 多余实现 / 签名不一致）
+ 接口地图自洽性校验（悬空接口 / 幽灵引用）；
12.2 接口校验门禁接入模块完成前置。
"""

from __future__ import annotations

from app.utils.interface_check import (
    InterfaceIssue,
    check_implementation,
    check_map,
    extract_public_defs,
    parse_api_signature,
)


class TestExtractPublicDefs:
    def test_top_level_functions_extracted(self):
        code = "def login(user_id, password):\n    pass\n\ndef _internal():\n    pass\n"
        defs = extract_public_defs(code)
        assert defs == {"login": ("user_id", "password")}

    def test_underscore_private_excluded(self):
        code = "def _private():\n    pass\n"
        assert extract_public_defs(code) == {}

    def test_classes_extracted_with_init_params(self):
        code = "class Store:\n    def __init__(self, path):\n        pass\n"
        defs = extract_public_defs(code)
        # M15-3：类 __init__ 参数去 self（self 是实现器物非 API 面）
        assert defs == {"Store": ("path",)}

    def test_variables_extracted(self):
        code = "session_data = {}\nVERSION = '1.0'\n_private_var = 1\n"
        defs = extract_public_defs(code)
        assert defs == {"session_data": (), "VERSION": ()}


class TestParseApiSignature:
    def test_parse_function_signature(self):
        name, params = parse_api_signature("login(user_id, password) -> bool")
        assert name == "login"
        assert params == ("user_id", "password")

    def test_parse_no_params(self):
        name, params = parse_api_signature("logout()")
        assert name == "logout"
        assert params == ()

    def test_parse_bare_name(self):
        name, params = parse_api_signature("session_data")
        assert name == "session_data"
        assert params is None  # 非函数：不比对参数

    def test_parse_invalid(self):
        assert parse_api_signature("") is None


class TestImplementationDiff:
    CONTRACT = {
        "imports": ["user"],
        "exports": ["login(user_id, password)", "logout()", "session_data"],
        "public_api": ["login"],
        "dependencies": ["user"],
    }

    def test_matching_implementation_passes(self):
        code = (
            "def login(user_id, password):\n    return True\n"
            "def logout():\n    pass\n"
            "session_data = {}\n"
        )
        issues = check_implementation("auth", code, self.CONTRACT)
        assert issues == []

    def test_missing_implementation_reported(self):
        # 类型 1：契约声明导出但代码未实现
        code = "def login(user_id, password):\n    return True\n"
        issues = check_implementation("auth", code, self.CONTRACT)
        kinds = {i.kind for i in issues}
        assert "missing" in kinds
        missing_names = {i.detail for i in issues if i.kind == "missing"}
        assert any("logout" in d for d in missing_names)

    def test_extra_implementation_reported(self):
        # 类型 2：代码实现但契约未声明
        code = (
            "def login(user_id, password):\n    return True\n"
            "def logout():\n    pass\n"
            "session_data = {}\n"
            "def secret_helper():\n    pass\n"
        )
        issues = check_implementation("auth", code, self.CONTRACT)
        extras = [i for i in issues if i.kind == "extra"]
        assert len(extras) == 1
        assert "secret_helper" in extras[0].detail

    def test_signature_mismatch_reported(self):
        # 类型 3：函数名匹配但参数不一致
        code = (
            "def login(uid, pwd):\n    return True\n"
            "def logout():\n    pass\n"
            "session_data = {}\n"
        )
        issues = check_implementation("auth", code, self.CONTRACT)
        mismatches = [i for i in issues if i.kind == "signature_mismatch"]
        assert len(mismatches) == 1
        assert "login" in mismatches[0].detail

    def test_no_contract_passes(self):
        issues = check_implementation("auth", "x = 1\n", None)
        assert issues == []


class TestMapConsistency:
    def test_consistent_map_passes(self):
        interfaces = {
            "user": {
                "imports": [],
                "exports": ["get_user(user_id)", "session_data"],
                "public_api": ["get_user"],
                "dependencies": [],
            },
            "auth": {
                "imports": ["get_user", "session_data"],
                "exports": ["login(user_id, password)"],
                "public_api": ["login"],
                "dependencies": ["user"],
            },
        }
        issues = check_map(interfaces)
        assert issues == []

    def test_dangling_import_reported(self):
        # 悬空接口：auth 声明 import 的符号未被依赖模块导出
        interfaces = {
            "user": {
                "imports": [],
                "exports": ["get_user(user_id)"],
                "public_api": ["get_user"],
                "dependencies": [],
            },
            "auth": {
                "imports": ["missing_symbol"],
                "exports": ["login()"],
                "public_api": ["login"],
                "dependencies": ["user"],
            },
        }
        issues = check_map(interfaces)
        dangling = [i for i in issues if i.kind == "dangling_import"]
        assert len(dangling) == 1
        assert "missing_symbol" in dangling[0].detail

    def test_ghost_module_reported(self):
        # 幽灵引用：依赖了不存在的模块
        interfaces = {
            "auth": {
                "imports": [],
                "exports": ["login()"],
                "public_api": ["login"],
                "dependencies": ["ghost"],
            }
        }
        issues = check_map(interfaces)
        ghosts = [i for i in issues if i.kind == "ghost_module"]
        assert len(ghosts) == 1

    def test_import_symbol_module_resolution(self):
        # 形如 from user import get_user 的声明：符号在 user.exports 中存在
        interfaces = {
            "user": {
                "imports": [],
                "exports": ["get_user(user_id)"],
                "public_api": ["get_user"],
                "dependencies": [],
            },
            "auth": {
                "imports": ["user.get_user"],
                "exports": ["login()"],
                "public_api": ["login"],
                "dependencies": ["user"],
            },
        }
        assert check_map(interfaces) == []

    def test_issue_carries_module_info(self):
        interfaces = {
            "auth": {"imports": [], "exports": [], "public_api": [], "dependencies": ["ghost"]}
        }
        issue = check_map(interfaces)[0]
        assert isinstance(issue, InterfaceIssue)
        assert issue.module == "auth"
