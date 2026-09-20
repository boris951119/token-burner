# 新试题接入指南（5 分钟）

任何 ARC Bench web 类试题接入本地全链路（生成→冒烟→评分→修复环）只需两步。
2026-09-21 起 `--task` 不再枚举，放置即接入。

## 步骤

1. **安装官方 specs**：把该任务的官方 Playwright specs 目录放到

   ```
   scripts/official_grade/specs/<task-name>/
   ```

   目录名即任务名（参考已有的 `keep/`、`bookstack/`）。须含 `*.spec.ts`
   与 `helpers.ts`（官方下发什么就放什么，不要改写断言）。

2. **跑起来**（全部命令用 `.venv/Scripts/python.exe`，系统 python 缺 flask）：

   ```bash
   # 生成 + 验收一条命令
   .venv/Scripts/python.exe scripts/local_loop.py \
       --requirement <官方需求文件或目录> --task <task-name>

   # 只评分
   .venv/Scripts/python.exe scripts/local_grade.py \
       --project-dir <projects/arcbench-app_*> --task <task-name>

   # 评分→定向修复→复评循环（带回滚保险：修复回退自动还原）
   .venv/Scripts/python.exe scripts/grade_repair_loop.py \
       --project-dir <projects/arcbench-app_*> --task <task-name> --rounds 3
   ```

## 框架无关性（2026-09-21 泛化后）

生成的项目无论 Flask 还是 FastAPI 风格，链路都通：

- **机械装配**（`app/utils/mechanical_assembly.py`）：AST 扫
  `Blueprint`/`APIRouter`（含 `fastapi.APIRouter()` 属性式），确定性
  生成 `app_main`；纯 FastAPI 项目走 `include_router` 模板。
- **导出入口**（`app/platform_export.py`）：两遍探测——作者写的模块级
  `app`/`application`（如 main.py 里的 `app = FastAPI()`）优先；
  `create_app()` 工厂兜底。项目自身 main.py 保真为 `project_main.py`
  不会被 runner 覆盖丢失。WSGI/ASGI 双起服，requirements 按代码实际
  import 生成。
- **冒烟**（`arcbench_smoke`）：与导出同语义的入口探测。

## 注意事项（踩过的坑）

- 评分器互斥：`scripts/official_grade/.grade.lock` 防并发踩踏
  （双循环并发会互相 rmtree 模板）。等在跑的评分结束再起第二个。
- 起服失败先看两件事：① 是否用了 venv python（系统 python 缺 flask，
  local_grade 现在会即时报错）；② 是否有孤儿 Flask/FastAPI 后端占着
  3301 端口或锁着 `.tmp/local_grade_template`（taskkill /T 清树）。
- 平台提交线：本地 ≥20 题再上平台烧钱。
