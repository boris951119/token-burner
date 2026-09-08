# -*- coding: utf-8 -*-
"""v1.2 环境适配层:SWE-bench 仓库家族的安装配方(数据 + 命令构建)。

背景(全量基准 R1 取证,logs/swebench_full/):8 个失败实例中 7 个死于
环境类失败——老仓库的测试依赖「当年版本」的 pytest/werkzeug/astroid,
全局最新版环境必然 ImportError。官方 harness 用 per-repo conda 环境
解决;本模块用「repo 家族配方表」近似同样的效果(轻量,无 conda)。

配方结构:
    pre   [-]  安装仓库本体**之前**先钉住的版本(防 -e . 拉入不兼容新版)
    extras[+]  仓库自带的可选依赖组(如 pytest 的 [testing]、sphinx 的 [test])
    post  [-]  本体之后补装的测试依赖(未被 setup 声明的)

匹配规则:先全名(pylint-dev/pylint),后按家族token(名称含 flask 等)。
未命中 → 通用配方(pip install -e .,行为与 v1.2 S2 一致)。
"""

from __future__ import annotations

# 家族配方表(首版基于 R1 失败归因;按失败证据持续迭代)
REPO_RECIPES: dict[str, dict] = {
    # flask 2019-2021:测试用 _pytest.monkeypatch.notset(新版 pytest 已移除),
    # werkzeug.url_quote(werkzeug 2.1 移除)——双双需要钉旧版
    "flask": {
        # 2026-09-07 实测验证:连贯 pin 组使 flask-5063 base 测试
        # 从 235 failed + 56 errors → 442 passed(剩 2 个年代行为差异)
        "pre": ["werkzeug==2.0.3", "jinja2==3.0.3", "itsdangerous==2.0.1",
                "click==8.0.4", "markupsafe==2.0.1", "setuptools==59.8.0",
                "pytest~=6.2"],
        "extras": [],
        "post": [],
    },
    # pytest 仓库:测试自身需要 testing extra(hypothesis/xmlschema 等)
    "pytest": {
        "pre": [],
        "extras": ["testing"],
        "post": [],
    },
    # sphinx:测试依赖在 [test] extra(html5lib/docutils/pytest 等)
    "sphinx": {
        "pre": [],
        "extras": ["test"],
        "post": [],
    },
    # pylint:astroid 为硬依赖,显式补装(pip 解析偶发漏装,R1 取证)
    "pylint": {
        "pre": [],
        "extras": [],
        "post": ["astroid"],
    },
    "astroid": {
        "pre": [],
        "extras": [],
        "post": [],
    },
    # requests:测试依赖 pytest-httpbin / pytest-mock(setup 未声明)
    "requests": {
        "pre": [],
        "extras": [],
        "post": ["pytest-httpbin", "pytest-mock"],
    },
    # xarray:numpy/pandas 显式补齐(版本随最新,2021+ 实例兼容)
    "xarray": {
        "pre": [],
        "extras": [],
        "post": ["pandas", "numpy"],
    },
    # seaborn:R1 实测 -e . 即工作(numpy/pandas/matplotlib 随装)
    "seaborn": {
        "pre": [],
        "extras": [],
        "post": [],
    },
}

# 家族 token → 配方键(按仓库名 slug 匹配)
_FAMILY_TOKENS = {
    "flask": "flask",
    "pytest": "pytest",
    "sphinx": "sphinx",
    "pylint": "pylint",
    "astroid": "astroid",
    "requests": "requests",
    "xarray": "xarray",
    "seaborn": "seaborn",
}


def recipe_for(repo: str) -> dict:
    """按 repo slug("pylint-dev/pylint")取配方;未命中返回通用空配方。"""
    slug = repo.rsplit("/", 1)[-1].lower()
    for token, key in _FAMILY_TOKENS.items():
        if token in slug:
            return REPO_RECIPES[key]
    return {"pre": [], "extras": [], "post": []}


def build_install_commands(recipe: dict, pip: list[str] | None = None) -> list[list[str]]:
    """构建安装命令序列(pure,可测):pre 钉版 → 本体 → extras → post。

    pip: 基础 pip 命令(缺省 [sys.executable, "-m", "pip", "install"]),
    extras 逐个尝试(-e ".[<extra>]"),与本体的合并写入同一条。
    """
    base = pip if pip is not None else ["python", "-m", "pip", "install"]
    cmds: list[list[str]] = []
    for spec in recipe.get("pre", []):
        cmds.append([*base, spec])
    cmds.append([*base, "-e", "."])
    for extra in recipe.get("extras", []):
        cmds.append([*base, "-e", f".[{extra}]"])
    for spec in recipe.get("post", []):
        cmds.append([*base, spec])
    return cmds


# ---------------------------------------------------------------------------
# v1.2 conda 环境规格:每仓库家族一个持久环境(Python 版本 + 依赖 pin)
# ---------------------------------------------------------------------------

FAMILY_CONDA: dict[str, dict] = {
    # python 版本按仓库 base_commit 年代选;pip pins 治 R1 的环境类失败
    "flask":   {"python": "3.9",  "pip": ["werkzeug~=2.0", "pytest~=6.2"]},
    "pytest":  {"python": "3.11", "pip": ["hypothesis", "xmlschema"]},
    "sphinx":  {"python": "3.9",  "pip": ["docutils", "jinja2"]},
    "pylint":  {"python": "3.10", "pip": ["astroid~=2.15"]},
    "astroid": {"python": "3.10", "pip": []},
    "requests": {"python": "3.9", "pip": ["urllib3", "pytest-httpbin", "pytest-mock"]},
    "xarray":  {"python": "3.10", "pip": ["numpy", "pandas", "pytest"]},
    "seaborn": {"python": "3.10", "pip": ["numpy", "pandas", "matplotlib"]},
}


def family_of(repo: str) -> str:
    """repo slug → 家族键(与 REPO_RECIPES 同一套 token)。"""
    slug = repo.rsplit("/", 1)[-1].lower()
    for token in _FAMILY_TOKENS:
        if token in slug:
            return token
    return slug


def conda_env_name(family: str) -> str:
    return f"swebench_{family}"
