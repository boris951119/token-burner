# token-burner VS Code 插件（v0.4 M1）

在 VS Code 侧边栏发起 token-burner 开发任务、跟踪进度与成本。
对应 v0.4.md：M1-1 插件脚手架、M1-2 任务发起面板（实时进度与代码应用属 M1-3/M1-4，后续批次）。

## 前置

1. 本地 API 服务（插件默认连 `http://127.0.0.1:8000`）：

   ```bash
   # 在 token-burner 仓库根目录
   python -m app.server
   ```

   未启动时面板会给出引导，可点「在终端启动服务」（用设置 `tokenBurner.serverDir`
   指定仓库目录）；服务地址经 `tokenBurner.serverUrl` 修改。

2. LLM API 密钥：token-burner 仓库根目录 `.env`（如 `OPENAI_API_KEY`）。

## 运行 / 侧载

开发调试（推荐）：

```bash
cd vscode-extension
npm install
npm run compile
```

然后用 VS Code 打开 `vscode-extension/` 目录，按 **F5** 启动
「Extension Development Host」，新窗口左侧活动栏出现火焰图标即激活。

打包 VSIX 侧载安装：

```bash
cd vscode-extension
npx @vscode/vsce package
code --install-extension token-burner-0.4.0.vsix
```

## 使用

1. 侧边栏确认「本地服务已连接」；
2. 输入需求 → 选三个互异的模型（主 / 开发副 / 测试副）→ 选执行模式
   （安全审阅 / 自动验证——自动模式会展示预算放大警示）；
3. 点「开始任务」→ 面板经异步 API（`POST /api/tasks`）提交并轮询状态
   （阶段 / 已耗 token），完成后展示项目目录与交付摘要。

## 通信契约

- `GET /api/health`、`GET /api/config`：连接检测与启动配置；
- `POST /api/tasks`（kind=run）→ `{task_id}`；
- `GET /api/tasks/{id}`：状态 / 当前阶段 / 已耗 token / 终态结果。
