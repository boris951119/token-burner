"""提示词资源加载器：提示词正文外置于 app/prompts/*.md（一个常量一个文件）。

原则（不变，总则 D.1）：所有需要理解与权衡的判断交给大模型，
模板仅提供结构约束与输出格式要求，不替模型做决策。

- 公共 API 不变：仍以模块级常量导出，引用方保持 `from app.tools.prompt_templates import XXX`
- 占位符仍为 str.format 风格 {xxx}；提示词内的 JSON 示例沿用 {{}} 转义
- 缺文件 / 空文件 fail-fast：立即抛异常，绝不静默降级为空提示词
- PyInstaller 打包（v0.4 M7-3）：spec 需加入 datas=[("app/prompts", "app/prompts")]
"""

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"提示词文件为空: {path}")
    return text


# ---------------------------------------------------------------------------
# 3.2 节 需求评估（输出 8.1 节 JSON 结构）
# ---------------------------------------------------------------------------

TASK_ASSESSMENT_SYSTEM = _load("task_assessment_system")
TASK_ASSESSMENT_USER = _load("task_assessment_user")
# 15.3 节：重试时替换为更严格的提示词
TASK_ASSESSMENT_STRICT_REMINDER = _load("task_assessment_strict_reminder")

# ---------------------------------------------------------------------------
# M9 双模式意图识别：System-1 快判（{intent, confidence, reason} 契约）
# ---------------------------------------------------------------------------

FAST_TRIAGE_SYSTEM = _load("fast_triage_system")
FAST_TRIAGE_USER = _load("fast_triage_user")

# ---------------------------------------------------------------------------
# D.1 边界护栏：请求主 LLM 复核（程序不发回自判，最终拍板权在大模型）
# ---------------------------------------------------------------------------

TASK_ASSESSMENT_RECHECK_SYSTEM = _load("task_assessment_recheck_system")
TASK_ASSESSMENT_RECHECK_USER = _load("task_assessment_recheck_user")

# ---------------------------------------------------------------------------
# 3.4 节 方案讨论：初始方案 / 评审（8.2 JSON）/ 汇总修订 / 收敛裁决
# ---------------------------------------------------------------------------

INITIAL_PROPOSAL_SYSTEM = _load("initial_proposal_system")
INITIAL_PROPOSAL_USER = _load("initial_proposal_user")
REVIEW_PROPOSAL_SYSTEM = _load("review_proposal_system")
REVIEW_PROPOSAL_USER = _load("review_proposal_user")
REVISE_PROPOSAL_SYSTEM = _load("revise_proposal_system")
REVISE_PROPOSAL_USER = _load("revise_proposal_user")
# 11.1：最后一轮汇总必须直接产出收敛 spec，不再提出开放问题
CONVERGE_SPEC_SYSTEM = _load("converge_spec_system")
CONVERGE_SPEC_USER = _load("converge_spec_user")
SUMMARY_ROUND_SYSTEM = _load("summary_round_system")

# 11.5：spec 确认收敛——第 3 次修改后主动合并意见
SPEC_CONFIRM_REVISE_SYSTEM = _load("spec_confirm_revise_system")
SPEC_CONFIRM_REVISE_USER = _load("spec_confirm_revise_user")
SPEC_CONFIRM_FINAL_MERGE_SYSTEM = _load("spec_confirm_final_merge_system")
SPEC_CONFIRM_FINAL_MERGE_USER = _load("spec_confirm_final_merge_user")

# ---------------------------------------------------------------------------
# 3.5 节 / 12 章：spec 模块拆分与接口契约
# ---------------------------------------------------------------------------

SPLIT_SYSTEM = _load("split_system")
SPLIT_USER = _load("split_user")
INTERFACE_SYSTEM = _load("interface_system")
INTERFACE_USER = _load("interface_user")

# ---------------------------------------------------------------------------
# 3.5 / 3.7 节 模块开发循环：写代码 / 写测试 / 修复
# ---------------------------------------------------------------------------

WRITE_CODE_SYSTEM = _load("write_code_system")
WRITE_CODE_USER = _load("write_code_user")
WRITE_TESTS_SYSTEM = _load("write_tests_system")
WRITE_TESTS_USER = _load("write_tests_user")
FIX_CODE_SYSTEM = _load("fix_code_system")
FIX_CODE_USER = _load("fix_code_user")

# M14-7（v1.0）：safe 模式 LLM 逻辑审查（规格 3.6.2 三件套补全）
LOGIC_REVIEW_SYSTEM = _load("logic_review_system")
LOGIC_REVIEW_USER = _load("logic_review_user")

# ---------------------------------------------------------------------------
# M10 Researcher（v0.5 Beta）：结构化技术摘要（四段式：来源/版本/示例/坑点）
# ---------------------------------------------------------------------------

RESEARCH_BRIEF_SYSTEM = _load("research_brief_system")
RESEARCH_BRIEF_USER = _load("research_brief_user")
