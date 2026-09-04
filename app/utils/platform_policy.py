"""交付目标平台策略（v1.0 M14-3/M14-4，规格 v1.0.md）。

背景（v0.5 真实验收教训）：生成代码含 Unix-only 的 fcntl（Windows 上不存在），
交付物在本机直接 ImportError；提示词无平台约束，危险扫描无平台黑名单类别。

单一数据源：提示词约束段与危险扫描黑名单共用同一「平台→不可用模块」映射，
保证「提示」与「拦截」不漂移。
"""
from __future__ import annotations

# 平台 → 该平台上不存在的标准库模块（依 CPython 文档编译定制）
_PLATFORM_UNAVAILABLE: dict[str, frozenset[str]] = {
    "windows": frozenset({
        "fcntl", "termios", "tty", "pwd", "grp", "resource",
        "posix", "syslog", "ossaudiodev", "crypt", "posix_ipc",
        "readline", "curses", "posixfile",
    }),
    "linux": frozenset({
        "msvcrt", "winreg", "winsound", "win32api", "win32con",
        "win32event", "win32file", "pythonwin", "nt", "_winapi",
    }),
    "macos": frozenset({
        "msvcrt", "winreg", "winsound", "win32api", "win32con",
        "win32event", "win32file", "pythonwin", "nt", "_winapi",
        "ossaudiodev",
    }),
}

_PLATFORM_LABEL = {
    "windows": "Windows",
    "linux": "Linux",
    "macos": "macOS",
    "any": "任意平台（跨平台兼容模式）",
}


def unavailable_modules(platform: str) -> frozenset[str]:
    """指定平台上不可用的模块集（any → 空集）。"""
    return _PLATFORM_UNAVAILABLE.get(platform, frozenset())


def prompt_constraint(platform: str) -> str:
    """平台约束提示词段（注入 write_code/fix_code/write_tests）。

    any 平台返回空串（不注入约束，行为与 v0.5 一致）。
    """
    mods = unavailable_modules(platform)
    if not mods:
        return ""
    label = _PLATFORM_LABEL.get(platform, platform)
    mod_list = ", ".join(sorted(mods))
    return (
        f"\n\n## 目标平台约束（{label}）\n"
        f"交付代码必须可在 {label} 上运行。"
        f"禁止使用以下标准库（{label} 上不存在，导入即 ImportError）：\n"
        f"{mod_list}\n"
        f"需要相应能力时请用平台可用方案替代（如文件锁用 msvcrt/portalocker 思路，"
        f"终端属性用 os.name/sys.platform 判断）。"
    )


def platform_violations(
    code: str, tests: str = "", platform: str = "any"
) -> list[str]:
    """M14-5 门禁链平台检查：代码/测试中 import 了目标平台不可用模块的清单。

    只查平台不可用（fcntl 类，可修复 → 进修复循环）；危险 API
    （os.system 类）不在此列——按 3.6.3 保持 executor 层 BLOCKED 直接
    冻结语义，两类拦截路径分离。语法错误静默放行（静态门禁负责报）。
    """
    import ast

    mods = unavailable_modules(platform)
    if not mods:
        return []
    issues: list[str] = []
    for label, text in (("代码", code), ("测试", tests)):
        if not text.strip():
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in mods:
                        issues.append(
                            f"{label}导入 {alias.name}"
                            f"（目标平台 {platform} 不存在，导入即 ImportError，"
                            f"请改用平台可用方案）"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in mods:
                    issues.append(
                        f"{label}从 {node.module} 导入"
                        f"（目标平台 {platform} 不存在，导入即 ImportError，"
                        f"请改用平台可用方案）"
                    )
    return issues
