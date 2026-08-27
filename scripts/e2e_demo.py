"""端到端模拟演示：无 API 密钥的真实管线运行。

- LLM 层：MockLLM（确定性桩，按提示词语义返回预制内容）；
- 其余全部真实：路由/讨论护栏/拆分校验/静态与接口门禁/
  安全执行器（SKIPPED→手动指引）/真实项目落盘；
- 输出复用 CLI 的展示函数（app.main._print_result）。

运行：python scripts/e2e_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings
from app.execution.safe_executor import SafeExecutor
from app.main import _print_result
from app.pipeline import Pipeline
from app.tools.file_manager import FileManager
from app.utils.model_client import LLMResponse

REQUIREMENT = "开发一个命令行用户管理系统：支持注册、登录（密码校验）与用户数据持久化（JSON 文件）"

# ----------------------------- 预制内容 -----------------------------------

ASSESSMENT = json.dumps(
    {"difficulty_score": 6, "difficulty_level": "中等", "task_type": "编程",
     "reason": "涉及用户注册/登录逻辑与文件持久化，需模块化处理"}, ensure_ascii=False)

PROPOSAL = (
    "技术方案：\n"
    "1. 架构：三模块——user（用户注册与查询）、data（JSON 持久化）、"
    "auth（登录密码校验）。\n"
    "2. 技术栈：纯 Python 标准库（json/pathlib）。\n"
    "3. 数据流：auth 依赖 user 与 data 的接口完成校验。"
)

POSITIVE_REVIEW = json.dumps(
    {"scores": {"feasibility": 9, "security": 8, "maintainability": 9},
     "strengths": ["职责划分清晰", "标准库零依赖"],
     "weaknesses": [], "risks": []}, ensure_ascii=False)

SPEC_MD = """# 用户管理系统 spec

## 项目目标
命令行用户管理系统：注册、登录、持久化。

## 用户故事
- 用户可注册（ID + 姓名 + 密码）
- 用户可登录（密码校验）
- 数据重启不丢失（JSON 文件）

## 架构设计
user / data / auth 三模块，auth 依赖 user 与 data。

## 接口定义
- user: create_user(user_id, name, password), get_user(user_id)
- data: save(key, value), load(key)
- auth: login(user_id, password) -> bool

## 数据模型
{user_id: {name, password}} 存于 users.json。

## 任务拆分
user（优先级 1）→ data（优先级 1）→ auth（优先级 2）。

## 验收标准
- 注册后可查询到用户
- 正确密码登录成功，错误密码失败
- 数据落盘可恢复
"""

SPLIT = json.dumps(
    {"modules": [
        {"name": "user", "responsibility": "用户注册与查询（内存态）", "dependencies": [], "priority": 1},
        {"name": "data", "responsibility": "JSON 文件持久化", "dependencies": [], "priority": 1},
        {"name": "auth", "responsibility": "登录密码校验", "dependencies": ["user", "data"], "priority": 2},
    ]}, ensure_ascii=False)


INTERFACES = {
    "user": {"imports": [], "exports": ["create_user(user_id, name, password)", "get_user(user_id)", "USERS"],
             "public_api": ["create_user", "get_user"], "dependencies": []},
    "data": {"imports": [], "exports": ["save(key, value)", "load(key)", "STORE"],
             "public_api": ["save", "load"], "dependencies": []},
    "auth": {"imports": ["create_user", "get_user", "save", "load"], "exports": ["login(user_id, password)"],
             "public_api": ["login"], "dependencies": ["user", "data"]},
}


CODE = {
    "user": '''USERS = {}


def create_user(user_id, name, password):
    """注册用户（返回是否成功）。"""
    if user_id in USERS:
        return False
    USERS[user_id] = {"name": name, "password": password}
    return True


def get_user(user_id):
    """查询用户（返回字典或 None）。"""
    return USERS.get(user_id)


if __name__ == "__main__":
    print(create_user("u1", "Alice", "p@ss"))
    print(get_user("u1"))
''',
    "data": '''import json
from pathlib import Path

STORE = Path("data_store.json")


def save(key, value):
    """保存键值到 JSON 文件。"""
    data = {}
    if STORE.exists():
        data = json.loads(STORE.read_text(encoding="utf-8"))
    data[key] = value
    STORE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return True


def load(key):
    """读取键值（不存在返回 None）。"""
    if not STORE.exists():
        return None
    return json.loads(STORE.read_text(encoding="utf-8")).get(key)


if __name__ == "__main__":
    save("k", "v")
    print(load("k"))
''',
    "auth": '''from user import create_user, get_user
from data import save, load


def login(user_id, password):
    """登录校验：用户存在且密码一致 → True。"""
    user = get_user(user_id)
    if user is None:
        return False
    if user["password"] != password:
        return False
    save("last_login", user_id)
    return True


if __name__ == "__main__":
    create_user("u1", "Alice", "p@ss")
    print(login("u1", "p@ss"))
    print(login("u1", "wrong"))
''',
}

TESTS = {
    "user": '''from user import create_user, get_user


def test_create_and_get():
    assert create_user("t1", "Bob", "secret") is True
    user = get_user("t1")
    assert user["name"] == "Bob"


def test_duplicate_rejected():
    assert create_user("t1", "Bob", "secret") is False
''',
    "data": '''from data import save, load


def test_save_and_load(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert save("k", {"a": 1}) is True
    assert load("k") == {"a": 1}


def test_load_missing():
    assert load("no_such_key") is None
''',
    "auth": '''from auth import login
from user import create_user


def test_login_success():
    create_user("u1", "Alice", "p@ss")
    assert login("u1", "p@ss") is True


def test_login_wrong_password():
    assert login("u1", "wrong") is False
''',
}


class MockLLM:
    """按提示词语义路由的确定性桩（与 ModelClient 同 chat 接口）。"""

    def __init__(self):
        self.calls: list[str] = []
        self.call_log: list[dict] = []  # 与 ModelClient 对齐（8.5 仪表盘数据源）

    def chat(self, model, messages, json_mode=False):
        system = messages[0]["content"]
        user = messages[-1]["content"]
        self.calls.append(system[:20])
        content = self._route(system, user)
        self.call_log.append(
            {"model": model, "json_mode": json_mode, "input_tokens": 100,
             "output_tokens": 200, "content_chars": len(content),
             "system_hint": system}
        )
        return LLMResponse(model=model, content=content, input_tokens=100, output_tokens=200)

    def _route(self, system: str, user: str) -> str:
        import re

        def module_name() -> str:
            m = re.search(r"模块名：(\w+)", user)
            return m.group(1) if m else ""

        if "需求评估专家" in system:
            return ASSESSMENT
        if "拆分阶段声明的依赖" in user:  # 接口契约（依赖一致性由程序校验）
            return json.dumps(INTERFACES[module_name()], ensure_ascii=False)
        if "架构师" in system and "spec.md 内容" in user:
            return SPLIT
        if "项目经理" in system and "初始技术方案" in user:
            return PROPOSAL
        if "副 LLM" in system and "评审" in system:
            return POSITIVE_REVIEW
        if "最终收敛" in user or "spec.md" in user and "历轮" in user:
            return SPEC_MD
        if "开发工程师" in system:  # 写码与修复同源（修复返回同模块正确代码）
            return CODE.get(module_name(), "x = 1\n")
        if "测试工程师" in system:
            return TESTS.get(module_name(), "def test_ok():\n    assert True\n")
        return "（通用回复）"


def main() -> None:
    print("=" * 60)
    print("端到端模拟运行（MockLLM + 真实管线 + 安全审阅模式）")
    print("=" * 60)
    print(f"\n[需求] {REQUIREMENT}\n")

    root = Path(__file__).resolve().parent.parent / "demo_projects"
    settings = Settings()
    llm = MockLLM()

    print("[1/4] 评估路由 ...")
    from app.orchestrator import TaskRouter
    route = TaskRouter(llm, settings.models[0], settings).route(REQUIREMENT)
    print(f"      类型={route.task_type} 难度={route.difficulty_score}（{route.difficulty_level}）")
    print(f"      路径={route.route.value}  理由={route.reason}")

    print("[2/4] 组队（预算闸门 + 项目创建）...")
    print("[3/4] 方案讨论（评审→收敛 spec→确认）...")
    print("[4/4] 模块拆分 → 接口契约 → 逐模块开发循环（门禁+落盘）...\n")

    pipeline = Pipeline(
        llm=llm, executor=SafeExecutor(), settings=settings,
        file_manager=FileManager(projects_root=root),
    )
    result = pipeline.run(
        REQUIREMENT,
        models=("gpt-4o", "deepseek-chat", "claude-3-5-sonnet"),
        mode="safe",
        spec_confirm="确认",
        user_feedback="手动运行成功，输出符合预期，无报错",  # 模拟用户验证反馈（8.4）
    )

    _print_result(result)
    print(f"\nLLM 调用次数: {len(llm.calls)}（全部为 Mock，零真实消耗）")
    if result.cost_dashboard is not None:
        print()
        print(result.cost_dashboard.text_summary())
    print(f"\n项目根: {root}")


if __name__ == "__main__":
    main()
