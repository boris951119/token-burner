"""spec → 模块拆分与接口生成（规格文档 3.5 节、12 章、第二阶段收尾任务）。

编排职责（决策 / 校验分离，总则 D 节）：
- 主 LLM 决策：模块拆分（名称/职责/依赖/优先级）、各模块接口三字段；
- 程序确定性校验：模块名白名单、四字段齐备、依赖闭合（12.2）、
  拆分依赖与接口依赖一致性、构建顺序拓扑排序；
- 程序落盘（12.3）：modules/<module>.md、interfaces.json（单一事实源）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.config import Settings
from app.tools.file_manager import FileManager
from app.utils.budget import BudgetExceededError, TaskCancelledError
from app.utils.model_client import _is_timeout, _is_transient
from app.utils.untrusted import sanitize_untrusted
from app.utils.requirement_anchors import collect_anchors_from_text
from app.tools.prompt_templates import (
    INTERFACE_SYSTEM,
    INTERFACE_USER,
    SPLIT_SYSTEM,
    SPLIT_USER,
)
from app.utils.parse import parse_json

# M15-3：契约风格约束段（接口生成侧）
from app.utils.contract_style import interface_style_prompt

_MODULE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,30}$")

# 保留名：与项目系统目录冲突的模块名（真实运行回归：LLM 为「附单元测试」
# 拆出名为 tests 的模块，与 tests/ 收集目录相撞导致导入混乱）
_RESERVED_MODULE_NAMES = frozenset({
    "code", "tests", "test", "modules", "changelog", "sessions",
    "logs", "_shared", "conftest", "spec", "docs",
})

_REQUIRED_FIELDS = ("name", "responsibility", "dependencies", "priority")

_INTERFACE_FIELDS = ("imports", "exports", "public_api", "dependencies")


class SplitError(ValueError):
    """spec 拆分失败（校验不过 / 解析失败需用户介入）。"""


def should_modularize(
    difficulty_score: int, estimated_files: int, settings: Settings
) -> bool:
    """12.2 模块化启用条件（程序确定性阈值判定）。

    难度 ≥ modular_difficulty_threshold（默认 5）或
    预估文件数 ≥ modular_file_count_threshold（默认 6）→ 启用拆分；
    否则单份 spec 直出（难度/文件数由大模型评估，阈值判定归程序）。
    """
    return (
        difficulty_score >= settings.modular_difficulty_threshold
        or estimated_files >= settings.modular_file_count_threshold
    )


@dataclass
class ModulePlan:
    """单个模块的拆分结果（3.5 节）。"""

    name: str
    responsibility: str
    dependencies: list[str]
    priority: int


_UI_TARGET_KEYS = ("view", "web", "ui", "页面", "前端", "界面", "视图",
                   "组装", "托管", "静态")


def inject_ui_manifest(plans: list[ModulePlan], requirement: str) -> str | None:
    """UI 页面清单注入（平台 v6-3 取证：占位壳页全盘落空——UI 完整性此前
    无结构化契约）。

    把需求锚点（页面名 + 逐字文案 + 种子数据）作为清单追加到前端/
    组装模块的职责尾部，成为 write_code 提示词的一部分——UI 完整性
    从「希望模型自觉」变成「按清单验收」。返回目标模块名或 None。
    """
    if not requirement.strip() or not plans:
        return None
    try:
        buckets = collect_anchors_from_text(requirement)
    except Exception:
        return None
    manifest_lines = []
    for section, anchors in buckets.items():
        if anchors:
            manifest_lines.append(
                f"- {section}: " + "、".join(anchors[:12]))
    if not manifest_lines:
        return None
    # 目标模块：职责/名称含 UI 关键词最多者（并列取 priority 小者）
    def _score(p: ModulePlan) -> tuple[int, int]:
        text = (p.name + " " + p.responsibility).lower()
        return (sum(k in text for k in _UI_TARGET_KEYS), -p.priority)

    target = max(plans, key=_score)
    if _score(target)[0] <= 0:
        return None  # 无 UI 形态模块（CLI 类任务）不注入
    # 规格保真度（9/22 keep#2 取证：锚点摊平后模型分不清「哪个词是按钮、
    # 哪个词是动作后提示」——Take a note 按钮级缺口）：把逐节点 GWT 结构
    # （控件/动作后文案/种子 三通道归属）追加为契约，写码首轮即可对准。
    ux_checklist = ""
    try:
        from app.acceptance_compile import (
            compile_checklists_from_text, render_ux_checklist)
        ux_checklist = render_ux_checklist(
            compile_checklists_from_text(requirement))
    except Exception:
        pass
    target.responsibility += (
        "\n\n【UI 页面与文案清单（硬契约，逐字实现——评测按这些字符串"
        "断言「对应触发时机渲染出的可见元素」，禁止占位页、"
        "禁止藏进 display:none/title 属性糊弄、禁止翻译改写）】\n"
        + "\n".join(manifest_lines)
        + ux_checklist
        + "\n\n【UI 全局硬规则（官方评测取证）】\n"
        "- 界面文案语言必须与需求原文一致：英文需求 → 全英文 UI；\n"
        "  出现其他语言界面 = 评分器按原文 role 名定位全部落空 = 0 分；\n"
        "- 带引号文案必须做成对应控件类型的可见元素（composer/按钮"
        "用 <button>，搜索框用 placeholder，通知用 snackbar），\n"
        "  评分器按 getByRole('button', {name}) 这类 ARIA 语义定位；\n"
        "  「可见」指的是**在需求规定的时机**可见，不是把清单一次性摊在"
        "首屏：首屏只放入口控件与种子数据，状态相关的控件（编辑框、"
        "确认框、每项操作菜单）在各自触发之后才出现——把全部文案摊成"
        "首屏一排按钮 = 交互流没实现 + 同名控件让严格定位歧义，"
        "两种都是实测过的失分形状；同一页面同一角色下不得出现同名"
        "（含大小写变体）的重复控件，一个操作只留一个入口；\n"
        "- 【ARIA 角色对照表】评分器的断言几乎全部按可访问性角色/名字"
        "定位元素（getByRole / getByLabel / getByPlaceholder 实测占绝大多数），"
        "而角色只来自语义标签——用非语义标签承载 = 该元素在评分器眼里"
        "不存在，与没写一模一样：\n"
        "    按钮 = <button>（严禁 <div>/<span> + onclick 伪按钮）；\n"
        "    链接 = <a href>（导航区每项都得是真链接，不是带样式的文字）；\n"
        "    单行输入 = <input type=\"text|search|email|password\">，"
        "多行内容输入 = <textarea>（用 input 装多行 = 无 textbox 语义）；\n"
        "    输入框必须【同时】给 placeholder 与 <label for>（配 id）——"
        "两种定位方式各自独立出现在用例里，缺一个就落一半；\n"
        "    勾选/开关 = <input type=\"checkbox\"> 配 label（不是"
        "点击变色的 div）；下拉 = <select><option>；\n"
        "    列表/卡片条目 = <ul><li> 或 <article>，且该条目的文本"
        "落在条目内部（外层容器不算）；\n"
        "    表格数据 = 真 <table><thead><th><tbody><tr><td>"
        "（div 网格不产生 row/cell 角色）；\n"
        "    弹窗/确认框 = <dialog> 或 role=\"dialog\" 且带可访问名"
        "（aria-label 或标题）；\n"
        "    菜单 = role=\"menu\" 容器内每项 role=\"menuitem\"；\n"
        "    内容区块 = <section aria-label=\"名称\">（<section> 没有"
        "可访问名时不产生 region 角色）；\n"
        "    侧栏/抽屉 = <aside>（role=complementary），主导航 = <nav>"
        "（role=navigation）——评测按地标角色限定作用域取其中的按钮，"
        "作用域落空则该区域内所有用例连环落空；\n"
        "    操作结果反馈（成功/失败提示）= 带 role=\"status\"（成功）或 "
        "role=\"alert\"（失败）的元素，文案逐字取需求原文——评测的"
        "反馈断言只收这两个角色与结果关键词，裸文字提示不可见；\n"
        "    同一个需求原文短语既是入口动作又是页面文案时，入口必须做成"
        "真控件（<button>/<a>），不能只有标题或正文文本——评测对入口的"
        "定位是 getByRole('button',{name}) 硬通道，无文本兜底；\n"
        "    标题用 <h1>~<h6> 的真实层级（评分器按 heading+level 断言，"
        "加粗文字不算标题）。\n"
        "  写完自查一遍：页面上每个可交互元素，用它对应的 role+name 能不能"
        "被定位到？\n"
        "- 禁止 markdown 符号（**、`、#）出现在任何界面文本中——\n"
        "  实跑取证按钮被渲染成带星号的字面文字；\n"
        "- 数据必须持久化：API 模块禁止用模块级内存列表当存储——\n"
        "  实跑取证有模块用模块级空列表当后端，库里的种子数据\n"
        "  API 永远看不见（评测重启进程即全灭）；读写必须经统一\n"
        "  db 层，create_app 启动加载 + 增删改写穿；全项目只允许\n"
        "  一个数据库文件，禁止各模块自建 .db。\n"
        "\n【组装与种子硬规则（官方评测取证；规则以需求文本为唯一事实源，不含任何特定题目内容）】\n"
        "- Flask 组装层必须设置 app.secret_key：用了 session 的应用缺\n"
        "  它 = 登录 POST 直接 500，认证相关用例全灭（隐形元凶）；\n"
        "- 首页 `/` 是评测的唯一起点：全部用例从首页出发导航——`/` 必须\n"
        "  200 且渲染真实导航链接（能点到各功能模块页面），\n"
        "  禁止 404/空白/纯文字壳（首页落空 = 全部用例连环落空）；\n"
        "- 种子数据必须覆盖需求点名的全部实体：名称逐字入库、数量\n"
        "  满足需求口径，只种一部分 = 对应用例的导航目标不存在直接落空；\n"
        "- 访问控制以需求文本为准：需求未声明登录/权限要求的页面\n"
        "  不得加登录墙，未登录访问必须渲染真实种子数据（评分脚本\n"
        "  常不登录直接断言内容存在）；同时禁止伪造登录态——假 user\n"
        "  对象、本地 fallback 数组、假成功横幅一律禁止，认证必须是\n"
        "  全局会话契约（header/nav 与页面消费同一会话状态）；\n"
        "- 表单控件标签与字段名逐字取自需求原文用语，禁止同义改写；\n"
        "  种子账号的凭据哈希必须与登录校验算法自洽（以种子数据实际\n"
        "  格式为准），保证种子账号能真实登录；登录成功后导航区显示\n"
        "  当前用户（同一全局会话状态）；\n"
        "- 模板禁止双重转义：内层渲染出的 HTML 传入外层模板时必须\n"
        "  标记安全（Jinja2 用 |safe）——否则整页链接/表单渲染成\n"
        "  转义死文本，增删改查全部不可交互；\n"
        "- 导航与入口控件文案必须逐字使用需求原文用语，禁用同义词\n"
        "  改写；需求里分开写的入口禁止合并成一个——评测按\n"
        "  getByRole(link/button, /^原文$/i) 精确匹配，同义词或\n"
        "  合并命名 = 该模块全部用例在导航一步就落空。")
    return target.name


class ModuleBuilder:
    """spec 拆分编排：拆分 → 校验 → 落盘 → 接口生成 → 合并。"""

    def __init__(self, llm, main_model: str, settings: Settings, file_manager: FileManager):
        self.llm = llm
        self.main_model = main_model
        self.settings = settings
        self.file_manager = file_manager

    # ------------------------------------------------------------------

    def _leg_chain(self) -> list[str]:
        """尝试用模型链：主模型打头，其余预设腿按序备胎（去重保序）。"""
        ordered = [self.main_model] + list(self.settings.models or [])
        seen: set[str] = set()
        chain = []
        for m in ordered:
            if m and m not in seen:
                seen.add(m)
                chain.append(m)
        return chain or [self.main_model]

    def _chat_json(self, attempt: int, messages: list[dict]) -> tuple[str | None, str]:
        """第 attempt 次 json 调用 → (内容, 失败原因)，瞬态故障时内容为 None。

        轮转而非「每次尝试遍历全链」：一条腿超时最坏烧掉 600s 墙钟，嵌套
        会把尝试数上限放大成腿数倍。配置错误（缺密钥）与预算/取消总闸直穿
        ——换腿续跑等于把「立即中止」改成「多烧几腿」。
        """
        chain = self._leg_chain()
        model = chain[attempt % len(chain)]
        try:
            response = self.llm.chat(model, messages, json_mode=True)
        except (BudgetExceededError, TaskCancelledError):
            raise
        except RuntimeError as exc:
            if not (_is_transient(exc) or _is_timeout(exc)):
                raise
            return None, f"调用失败（网关瞬态）{type(exc).__name__} {model}: {exc}"[:200]
        return response.content, ""

    def split_spec(self, spec_md: str, project_id: str | None = None,
                   requirement: str = "") -> list[ModulePlan]:
        """主 LLM 拆分 spec 为模块列表（含重试与确定性校验）。

        requirement（规模工程）：讨论阶段吃 FOLDER 摘要产出的 spec 不含
        原子验收细节——拆分时把原始需求全文作为补充上下文注入，模块
        职责必须引用其中的验收细节与种子契约，否则细节在讨论层丢失。
        """
        user_content = SPLIT_USER.format(spec=spec_md)
        if requirement.strip():
            user_content += (
                "\n\n【原始需求全文（模块职责必须引用其中的验收细节、"
                "种子数据与夹具契约）】\n"
                + sanitize_untrusted(requirement)
            )
        attempts = 1 + self.settings.max_parse_retries
        last_error = "未知错误"
        for attempt in range(attempts):
            content, call_error = self._chat_json(attempt, [
                {"role": "system", "content": SPLIT_SYSTEM},
                {"role": "user", "content": user_content},
            ])
            if content is None:
                # shape-keep 彩排同族：拆分环一次网关超时曾直穿成 SplitError
                # =零交付。这里本就有条带 last_error 的重试环，调用失败并进同一条口。
                last_error = call_error
                continue
            value, _detail = parse_json(content, location="module_split")
            if value is None or not isinstance(value, dict):
                last_error = "拆分输出解析失败"
                continue
            raw_modules = value.get("modules")
            if not isinstance(raw_modules, list) or not raw_modules:
                last_error = "拆分结果至少包含一个模块"
                continue
            plans: list[ModulePlan] = []
            for raw in raw_modules:
                if not isinstance(raw, dict) or any(
                    f not in raw for f in _REQUIRED_FIELDS
                ):
                    last_error = f"模块缺少必要字段 {_REQUIRED_FIELDS}"
                    plans = []
                    break
                name = raw["name"]
                if not isinstance(name, str) or not _MODULE_NAME.match(name):
                    last_error = f"模块名不合法: {name!r}"
                    plans = []
                    break
                if name in _RESERVED_MODULE_NAMES:
                    last_error = (
                        f"模块名 {name!r} 与系统目录冲突（保留名），"
                        "请以功能命名并另拆测试模块或并入各模块职责"
                    )
                    plans = []
                    break
                deps = raw["dependencies"]
                if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
                    last_error = f"模块 {name} 的 dependencies 须为字符串列表"
                    plans = []
                    break
                priority = raw["priority"]
                if not isinstance(priority, int) or isinstance(priority, bool):
                    last_error = f"模块 {name} 的 priority 须为整数"
                    plans = []
                    break
                plans.append(
                    ModulePlan(
                        name=name,
                        responsibility=str(raw["responsibility"]),
                        dependencies=list(deps),
                        priority=priority,
                    )
                )
            if not plans:
                continue
            # 名称唯一 + 依赖闭合（12.2）
            names = {p.name for p in plans}
            if len(names) != len(plans):
                last_error = "模块名重复"
                continue
            for plan in plans:
                for dep in plan.dependencies:
                    if dep not in names:
                        last_error = (
                            f"依赖闭合校验失败：模块 {plan.name} 依赖不存在的模块 {dep}"
                        )
                        plans = []
                        break
                if not plans:
                    break
            if plans:
                inject_ui_manifest(plans, requirement)
                from app.utils.seed_contract import inject_seed_contract
                seed_target = inject_seed_contract(plans, requirement)
                if seed_target:
                    print(f"[split] 种子硬契约已注入 {seed_target}",
                          flush=True)
                if project_id:
                    self._persist_module_plans(project_id, plans)
                return plans
            last_error = last_error or "校验失败"
        raise SplitError(f"spec 拆分失败（重试 {attempts} 次）: {last_error}，请用户介入调整 spec")

    def generate_interfaces(
        self, plans: list[ModulePlan], project_id: str | None = None
    ) -> dict[str, dict]:
        """主 LLM 为每个模块生成三字段接口契约并合并（12.1）。"""
        spec_deps = {p.name: set(p.dependencies) for p in plans}
        interfaces: dict[str, dict] = {}
        attempts = 1 + self.settings.max_parse_retries
        for plan in plans:
            messages = [
                # M15-3：风格约束段按 contract_style 运行时拼接
                # （function 缺省 = M15-1 原文；class 类式；auto 弱引导）
                {
                    "role": "system",
                    "content": INTERFACE_SYSTEM
                    + interface_style_prompt(self.settings.contract_style),
                },
                {
                    "role": "user",
                    "content": INTERFACE_USER.format(
                        name=plan.name,
                        responsibility=plan.responsibility,
                        dependencies=", ".join(plan.dependencies) or "无",
                    ),
                },
            ]
            value = None
            last_error = "未取得可用输出"
            for attempt in range(attempts):
                content, call_error = self._chat_json(attempt, messages)
                if content is None:
                    # 接口环原先一次调用定生死：网关瞬态在此重试/换腿，
                    # 不再直穿成 SplitError=零交付（批次#21 同族）。
                    last_error = call_error
                    continue
                parsed, _detail = parse_json(
                    content, location=f"interface_{plan.name}"
                )
                if not isinstance(parsed, dict):
                    last_error = "接口契约输出解析失败"
                    continue
                value = parsed
                break
            if value is None:
                raise SplitError(
                    f"模块 {plan.name} 接口契约未取得可用输出"
                    f"（重试 {attempts} 次）: {last_error}"
                )
            if any(f not in value for f in _INTERFACE_FIELDS):
                raise SplitError(
                    f"模块 {plan.name} 接口契约缺少必要字段 {_INTERFACE_FIELDS}"
                )
            # 12.2：接口依赖须与拆分依赖一致（确定性校验）
            iface_deps = set(value["dependencies"])
            if iface_deps != spec_deps[plan.name]:
                raise SplitError(
                    f"模块 {plan.name} 的接口依赖 {sorted(iface_deps)} "
                    f"与拆分依赖 {sorted(spec_deps[plan.name])} 不一致"
                )
            interfaces[plan.name] = {f: value[f] for f in _INTERFACE_FIELDS}

        if project_id:
            handle = self.file_manager.get_project(project_id)
            if handle is not None:
                (handle.root / "interfaces.json").write_text(
                    json.dumps(interfaces, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        return interfaces

    def build_order(self, plans: list[ModulePlan]) -> list[str]:
        """构建顺序：优先级升序 + 依赖拓扑（3.5 依赖顺序执行）。"""
        by_name = {p.name: p for p in plans}
        ordered: list[str] = []
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in visiting:
                raise SplitError(f"模块依赖存在环: {name}")
            visiting.add(name)
            for dep in sorted(by_name[name].dependencies):
                visit(dep)
            visiting.discard(name)
            visited.add(name)
            ordered.append(name)

        for plan in sorted(plans, key=lambda p: (p.priority, p.name)):
            visit(plan.name)
        return ordered

    # ------------------------------------------------------------------

    def single_module_plan(
        self, spec_md: str, project_id: str | None = None
    ) -> ModulePlan:
        """12.2 非模块化路径：单份 spec 直出为单一模块（跳过拆分与接口契约）。

        模块名固定 main（确定性程序决策，无 LLM 调用）；spec 全文作为
        职责传入开发循环，modules/main.md 落盘以维持目录结构一致。
        """
        plan = ModulePlan(
            name="main",
            responsibility=spec_md,
            dependencies=[],
            priority=1,
        )
        if project_id:
            self._persist_module_plans(project_id, [plan])
            # 单模块无接口契约：移除项目脚手架预生成的空 interfaces.json
            handle = self.file_manager.get_project(project_id)
            if handle is not None:
                iface_path = handle.root / "interfaces.json"
                if iface_path.exists():
                    iface_path.unlink()
        return plan

    def _persist_module_plans(self, project_id: str, plans: list[ModulePlan]) -> None:
        handle = self.file_manager.get_project(project_id)
        if handle is None:
            return
        for plan in plans:
            content = (
                f"# 模块 {plan.name}\n\n"
                f"## 职责\n{plan.responsibility}\n\n"
                f"## 依赖\n"
                + ("\n".join(f"- {d}" for d in plan.dependencies) or "无")
                + f"\n\n## 优先级\n{plan.priority}\n"
            )
            (handle.root / "modules" / f"{plan.name}.md").write_text(
                content, encoding="utf-8"
            )
