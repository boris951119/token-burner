# v8 设计方案：协同契约 + 自测交付闸（2026-09-20）

## 背景取证（v7 平台双跑）

- Keep 9.4（3/32）、BookStack 8.8（3/34），成本 ¥210.45，效率 0.085-0.088 pass/CNY
- 失效面：交互层 10s 超时族（能看不能点）+ BookStack 认证链断裂（登录页即挂）
- 根因链：模块独立生成无共享契约 → 接缝裂缝；自检信号弱 → 修复盲飞

## 三原则 → 三机制（用户定盘）

### 原则一：充分理解需求 → 场景结构化

spec 期把每条 REQ 的 GIVEN/WHEN/THEN 编译为结构化场景条目：
`{req_id, module, scenario, given[], when, then[], seed_refs[]}`。
跨模块场景（如登录→书架列表）标注集成点。此结构同时驱动
测试生成与 traceability 登记（激活 feature_implementation_rate）。

### 原则二：协同作战 → 集成契约层 + 拼接机械化

spec 期产出**集成契约**（机器可校验的 YAML/JSON）：

```yaml
contract:
  database:
    file: instance/app.db        # 全项目唯一库文件
    engine: sqlite
  entities:
    shelf: {columns: [...], owner: db_core}
  api_surface: [GET /api/shelves, POST /api/shelves, ...]
  seed:                          # 机械通道：直接从 requirements.yaml 生成
    - table: shelves
      rows: [{name: "Shelf 4.1"}, ...]
  exports:                       # 拼接机械化的输入
    - {module: auth, blueprints: [auth_bp], inits: [init_app]}
    - {module: shelves, blueprints: [shelves_bp], inits: [init_shelves]}
```

- 每个模块提示词内嵌契约相关段（不是全文，是相关切片）
- 验收期机械校验：库文件唯一性（已有 fixer）、DDL 符合契约、
  API 面路由存在性、种子行精确命中
- **小块验收加契约符合性机械校验**：模块闸门当场拦截接缝裂缝
  （如 seed 模块写错库文件在闸门即拦，不进拼接）——
  v7 实证：三个模块各自合格，拼起来种子进不了 API 的库
- **拼接机械化**：AST 扫描各模块导出的 blueprint/init 函数，
  确定性生成 app_main 的 create_app 接线——组装是确定性工作，
  不交给概率（v7 实证：LLM 组装的根模块路由被 view 模块抢注，
  动态首页被静态 mockup 遮蔽，此类方差归零）
- **种子数据走机械播种器**：requirements.yaml → SQL，绕过 LLM 方差
  （双模式自动探测：题面带种子声明=机械播种；不带=测试自建数据，
  BookStack 实测无种子声明）

### 原则三：自生成测试 + 交付闸 → 测试工程模块

spec 期新增测试工程步骤（与模块拆分并行）：

1. 场景条目 → Playwright 严格断言（浏览器级，ARIA 语义 + 可见文本 +
   交互流；与评分器同形态）
2. **诚实性元测试**：自测先对空白骨架应用跑一遍，要求大多数用例
   FAIL——空应用就能过的测试太弱，打回重生成（防自证正确）
3. 交付闸：自测 → 修复环（mech fixer 先行 → LLM 定向 → 止损）→
   轮次耗尽仍交付最好版本（平台评分只认交付物，9.4 > 不交付）

## 复用清单（已就绪 60%）

| 组件 | 现状 | v8 动作 |
|---|---|---|
| official_probe 运行器 | 已建（跑官方真题） | 换测试源=自生成 specs，零改动复用 |
| RepoFixer 有界修复 + 止损 | 今日已修（4bbce46） | 直接复用 |
| 预算活动护栏 | 今日已修（4bbce46） | 直接复用 |
| journey 验收（测试自生成） | 已有但弱 | 升级为 Playwright 严格形态 |
| traceability | 已有 | 测试条目登记 → feature_rate 激活 |
| 反作弊三件套 | 已有（v6-3 取证） | 继续生效 |

## 实施顺序

1. **P0-a 集成契约层**：requirements.yaml → contract.yaml 解析器 +
   机械种子播种器 + 模块提示词契约切片注入
2. **P0-b 测试工程模块**：场景 → Playwright specs 生成 + 元测试 +
   交付闸接线（official_probe 换测试源）
3. **P1 Keep 交互挂点**：More options/标签/搜索高亮/设置页（与契约层
   不冲突，挂点清单现成）
4. **验证**：BookStack 本地彩排（跑动中）= 旧路线基线；v8 路线同起点
   A/B。正赛前完成 Keep 全链 + BookStack 至少一轮。

## 效率预算

- 测试生成：spec 期一次性 ~50-100k tokens
- 交付闸自测：跑测试零 LLM；修复环受预算护栏 + 止损约束
- 目标：单任务总消耗 ≤2M 帽内（v7 实际 7M 的三分之二来自护栏外修复，
  已堵），通过率 50%+ 时效率即进榜上中游
