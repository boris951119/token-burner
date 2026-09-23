# -*- coding: utf-8 -*-
"""UI 页面清单注入回归（平台 v6-3 取证：占位壳 0/32）。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


class TestInjectUiManifest:
    def test_manifest_injected_into_ui_module(self):
        from app.agents.module_builder import ModulePlan, inject_ui_manifest
        plans = [
            ModulePlan(name="data_core", responsibility="数据层", dependencies=[], priority=1),
            ModulePlan(name="view", responsibility="组装页面与静态资源", dependencies=["data_core"], priority=2),
        ]
        req = '需求：首页含 "Take a note" 表单。Seed data: note "Sprint goals"。'
        target = inject_ui_manifest(plans, req)
        assert target == "view"
        assert "Take a note" in plans[1].responsibility
        assert "Sprint goals" in plans[1].responsibility
        assert "硬契约" in plans[1].responsibility

    def test_non_ui_task_skipped(self):
        from app.agents.module_builder import ModulePlan, inject_ui_manifest
        plans = [ModulePlan(name="cli", responsibility="命令行工具", dependencies=[], priority=1)]
        assert inject_ui_manifest(plans, '需求：做 "加法"') is None

    def test_empty_requirement_skipped(self):
        from app.agents.module_builder import ModulePlan, inject_ui_manifest
        plans = [ModulePlan(name="view", responsibility="页面", dependencies=[], priority=1)]
        assert inject_ui_manifest(plans, "") is None


class TestUxChecklistInjection:
    """9/22 keep#2 取证：锚点摊平丢 GWT 归属——逐节点清单须随契约注入。"""

    def test_structured_checklist_injected(self):
        from app.agents.module_builder import ModulePlan, inject_ui_manifest
        req = "\n".join([
            "## 模块：M1 Notes",
            "依赖：无",
            "笔记模块。",
            "### REQ-1.1 Create（验收标准）",
            'Seed data: note "Sprint goals".',
            "  - 场景：create",
            "    GIVEN: the home page is open",
            '    WHEN: press the "Take a note" button',
            '    THEN: a snackbar shows "Note created"',
        ])
        plans = [
            ModulePlan(name="data_core", responsibility="数据层",
                       dependencies=[], priority=1),
            ModulePlan(name="view", responsibility="组装页面与静态资源",
                       dependencies=["data_core"], priority=2),
        ]
        assert inject_ui_manifest(plans, req) == "view"
        r = plans[1].responsibility
        assert "验收节点逐字清单" in r
        assert "REQ-1.1" in r and '"Take a note"' in r and '"Note created"' in r

    def test_plain_text_requirement_unaffected(self):
        from app.agents.module_builder import ModulePlan, inject_ui_manifest
        plans = [ModulePlan(name="view", responsibility="页面",
                            dependencies=[], priority=1)]
        assert inject_ui_manifest(
            plans, '需求：首页含 "Search" 框。') == "view"
        assert "验收节点逐字清单" not in plans[0].responsibility


class TestL1RenderingContract:
    """9/23 深夜 L1 赎回率测量取证（keep 域手工重写导出件，1/32 → 30/32）：
    当时最大的死因簇不是模型能力，而是生成器把 UX 结构交给了「硬编码
    mockup」——库里种了 28 条，页面上手写 16 条不接库，官方 32 条用例从
    第一条定位就落空。单条「渲染层必须读库」契约赎回约 17 题。
    其余四条同样是量出来的（子串匹配、同名双卡、非幂等种子、hover 才渲染
    的卡内入口），规则必须泛化到零题目内容（#46 口径）。"""

    REQ = '需求：首页含 "Search" 输入框与笔记列表。'

    def _inject(self):
        from app.agents.module_builder import ModulePlan, inject_ui_manifest
        plans = [ModulePlan(name="view", responsibility="组装页面与静态资源",
                            dependencies=[], priority=1)]
        assert inject_ui_manifest(plans, self.REQ) == "view"
        return plans[0].responsibility

    def test_seed_must_be_rendered_from_storage(self):
        r = self._inject()
        assert "渲染层必须从库里读" in r, "只写「入库」不够，mockup 照样满分落空"
        assert "首屏条目数等于库里该视图的条目数" in r
        assert "静态样例" in r, "必须点名手写样例条目这一死法"

    def test_substring_locator_anti_contract(self):
        """getByRole 的 name 默认子串匹配——短词面撞长词面是双向判歧义。"""
        r = self._inject()
        assert "子串" in r and "而不是全等" in r
        assert "公共定位面" in r, "内部/编辑态词面不得进侧栏与菜单"

    def test_duplicate_name_creation_is_ambiguity(self):
        r = self._inject()
        assert "两张同名卡片" in r and "去重" in r

    def test_seed_init_is_idempotent_and_facet_clean(self):
        r = self._inject()
        assert "必须幂等" in r and "旧关联要先清掉" in r
        assert "渲染前必须去重" in r
        assert "不得自行加挂" in r, "条目归类只能来自需求原文"

    def test_card_actions_stay_in_dom(self):
        """常驻 vs 按需渲染是实测两难（赎回 2 题 vs 判红 6 题），契约须写死
        取向，否则模型每轮自己重新发明一次。"""
        r = self._inject()
        assert "常驻 DOM" in r and "悬停" in r
        assert "按常驻这侧取舍" in r


class TestAriaRoleContract:
    """9/23 取证：官方用例的断言几乎全走 getByRole/getByLabel/
    getByPlaceholder（button/textbox/cell/checkbox/dialog/placeholder…），
    而当期交付物里 placeholder= 只出现 2 次、role= / <dialog> / <select> /
    <textarea> 一次都没有——非语义标签承载的控件在评测眼里等于不存在。
    角色对照表因此必须是硬契约，而不是「建议用 <button>」的一句话。"""

    REQ = '需求：首页含 "Search" 输入框与 "Save" 按钮。'

    def _inject(self):
        from app.agents.module_builder import ModulePlan, inject_ui_manifest
        plans = [ModulePlan(name="view", responsibility="组装页面与静态资源",
                            dependencies=[], priority=1)]
        assert inject_ui_manifest(plans, self.REQ) == "view"
        return plans[0].responsibility

    def test_role_map_is_injected(self):
        r = self._inject()
        assert "ARIA 角色对照表" in r
        # 每一行都必须给出「用什么标签」而非只说「要语义化」
        for probe in ("<button>", "<a href>", "<textarea>", "<label for>",
                      'type="checkbox"', "<select>", "<li>", "<table>",
                      "<dialog>", 'role="menuitem"', "<h1>"):
            assert probe in r, f"角色对照表缺 {probe} 一行"

    def test_contract_names_the_locator_channel(self):
        """报错式提示必须点名评测的定位通道，否则模型不知道为何要改。"""
        r = self._inject()
        assert "getByRole" in r and "getByPlaceholder" in r
        assert "onclick" in r, "必须明确禁止 div/span+onclick 伪按钮"

    def test_landmarks_feedback_and_entry_control(self):
        """9/23 r1 快照取证：页面本身有 button/link/textbox，但需求里既是
        入口动作又是文案的短语被做成了 heading+textbox，侧栏无地标、
        反馈无实况区——这三条是官方硬通道（无文本兜底）的漏点。"""
        r = self._inject()
        for probe in ("<aside>", "<nav>", 'complementary', 'navigation'):
            assert probe in r, f"缺地标一行：{probe}"
        assert 'role="status"' in r and 'role="alert"' in r, "缺反馈实况区"
        assert "不能只有标题或正文文本" in r, "缺入口控件硬通道一行"

    def test_same_name_must_not_also_sit_on_a_heading(self):
        """9/23 官方 helpers.ts 真身取证（keep/ctrip/prestashop 三份同形）：
        可访问名是按固定角色序逐个试的，firstVisible 取到第一个可见的就收手
        ——heading 排在 label/placeholder 之前。当期交付 08 把入口短语同时
        写成 <h2>Take a note</h2> 与输入框 placeholder，标题赢下点击：页面
        正常、控件正常、用例就是点不到，与「控件缺失」是两种病。旧规则只
        写了正向（入口要真控件），漏了反向（同一短语不得再长在标题上）。"""
        r = self._inject()
        assert "button→link→menuitem" in r, "缺可访问名的角色解析顺序"
        assert "把点击从" in r, "缺「标题抢位」这一失效机理"
        assert "placeholder/label 上时" in r, "缺反向约束（改写同页标题措辞）"

    def test_card_container_and_state_attribute(self):
        """9/23 官方 helpers 真身取证（判分工作区 specs/*/helpers.ts）：卡片
        解析器首选容器只有 getByRole('article')，之后每个行内操作都是
        card.getByRole('button') —— 卡片用 <li>/div 承载时可见性尚有文本兜底，
        卡内按钮却一个都取不到，整族交互用例连环红（实测 17/32 停在这）。
        互斥视图切换另按 aria-pressed 判当前态。"""
        r = self._inject()
        assert "行内操作按钮也必须写进同一个 <article>" in r
        assert "aria-pressed" in r, "缺状态属性一行"
        assert "<ul><li>" in r, "纯展示清单的出口得留着，别把规则写反"

    def test_visibility_is_scoped_to_trigger_timing(self):
        """「禁止隐藏元素」被当成「全部摊在首屏」是实测失分形状：入口留在
        首屏，状态控件在各自触发后出现，且同一角色下不得同名重复。"""
        r = self._inject()
        assert "对应触发时机" in r
        assert "display:none" in r, "糊弄式隐藏必须单独点名"
        assert "同名" in r and "重复" in r

    def test_requirement_text_still_carries_the_rule_for_backend_modules(self):
        """角色规则不能只进 UI 模块：后端模块常自渲染模板，
        故需求文本（全模块共见）里也要有一条。"""
        from app.arcbench_ingest import render_requirement_text

        tree = {
            "name": "Demo", "description": "一个演示应用", "type": "FOLDER",
            "children": [{
                "type": "FOLDER", "name": "REQ-1 Home", "children": [
                    {"type": "ATOMIC", "name": "REQ-1.1 Enter",
                     "description": "d", "children": []}]}],
        }
        text = render_requirement_text(tree)
        assert "可访问性角色" in text
        assert "<textarea>" in text and "<dialog>" in text
