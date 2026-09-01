"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
/**
 * token-burner VS Code 插件（M1-1/1-2 脚手架与任务发起，M1-3 实时进度，M1-4 代码应用）。
 *
 * 架构（v0.4.md M1 关键设计决策）：
 * - 后端复用 FastAPI Server（app/server.py），经「异步任务 API 提交 +
 *   轮询/SSE」（M8-3/M8-4）获取进度，不依赖同步长连接；
 * - 所有 HTTP 在扩展宿主侧发起（webview 只做 UI 与消息）——
 *   规避 webview CSP / CORS 限制；
 * - 进度：SSE 事件流为主（阶段切换/逐模块/token 增量），轮询兜底；
 * - 代码应用走 Workspace Edit API，确保 Undo/Redo 正常（M1-4）；
 * - 服务未启动时给出明确引导：一键终端启动 + 重连。
 */
const vscode = require("vscode");
const fs = require("fs");
const os = require("os");
const path = require("path");
const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"]);
const POLL_INTERVAL_MS = 1500;
function activate(context) {
    const provider = new PanelProvider(context.extensionUri);
    context.subscriptions.push(vscode.window.registerWebviewViewProvider("tokenBurner.panel", provider), vscode.commands.registerCommand("tokenBurner.openPanel", async () => {
        await vscode.commands.executeCommand("token-burner.focus");
    }), 
    // M12-4：设置变更即时生效（预算 / 默认模型 / 服务地址变更即刷新面板）
    vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration("tokenBurner")) {
            provider.notifyConfigChange();
        }
    }));
}
function deactivate() {
    // 无常驻资源（轮询定时器与 SSE 连接随 webview 销毁清理）
}
class PanelProvider {
    constructor(extensionUri) {
        this.extensionUri = extensionUri;
        this.tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "token-burner-preview-"));
    }
    resolveWebviewView(view) {
        this.view = view;
        view.webview.options = { enableScripts: true };
        view.webview.html = this.buildHtml(view.webview);
        view.webview.onDidReceiveMessage((msg) => {
            void this.onMessage(msg);
        });
        view.onDidDispose(() => this.stopTracking());
    }
    // ------------------------------------------------------------------
    // 配置与服务连接
    // ------------------------------------------------------------------
    get baseUrl() {
        return vscode.workspace
            .getConfiguration("tokenBurner")
            .get("serverUrl", "http://127.0.0.1:8000")
            .replace(/\/+$/, "");
    }
    get serverDir() {
        return vscode.workspace
            .getConfiguration("tokenBurner")
            .get("serverDir", "");
    }
    // M12-4：任务预算覆盖（0 = 按服务端档位配置）
    get budgetTokens() {
        return vscode.workspace
            .getConfiguration("tokenBurner")
            .get("budgetTokens", 0);
    }
    // M12-4：默认模型（主/开发/测试，按序 ≤3 项；空 = 服务端预设）
    get defaultModels() {
        return vscode.workspace
            .getConfiguration("tokenBurner")
            .get("defaultModels", []);
    }
    /** M12-4：设置变更即时生效——重发连接状态与面板默认值。 */
    notifyConfigChange() {
        void this.checkServer();
        this.post({
            command: "defaults",
            models: this.defaultModels,
            budgetTokens: this.budgetTokens,
        });
    }
    async fetchJson(path, init) {
        const res = await fetch(this.baseUrl + path, init);
        if (!res.ok) {
            const text = await res.text();
            throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
        }
        return res.json();
    }
    async onMessage(msg) {
        switch (msg.command) {
            case "ready":
            case "reconnect":
                await this.checkServer();
                break;
            case "startServer":
                this.startServerTerminal();
                break;
            case "submit":
                await this.submitTask(msg);
                break;
            case "fetchFiles":
                await this.sendProjectFiles();
                break;
            case "previewFile":
                await this.previewFile(msg.path);
                break;
            case "applyFiles":
                await this.applyFiles(msg.paths ?? []);
                break;
            case "loadProjects":
                await this.sendProjects(); // M1-6 历史任务列表
                break;
            case "resumeProject":
                await this.resumeProject(msg.projectId); // M1-7 一键恢复
                break;
            case "fetchCost":
                await this.sendDashboard(msg.projectId); // M1-5 成本统计
                break;
        }
    }
    async checkServer() {
        try {
            await this.fetchJson("/api/health");
            const config = await this.fetchJson("/api/config");
            this.post({ command: "serverState", ok: true, config });
            // M12-4：面板默认值（预算 / 默认模型）随连接下发
            this.post({
                command: "defaults",
                models: this.defaultModels,
                budgetTokens: this.budgetTokens,
            });
        }
        catch {
            this.post({ command: "serverState", ok: false });
        }
    }
    startServerTerminal() {
        const dir = this.serverDir;
        const term = vscode.window.createTerminal({ name: "token-burner server" });
        if (dir) {
            term.sendText(`cd "${dir}"`);
        }
        else {
            term.sendText(`cd "${vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? "."}"`);
        }
        term.sendText("python -m app.server");
        term.show();
        void vscode.window.showInformationMessage("已在终端启动 token-burner 服务（须在 token-burner 仓库目录，可用 tokenBurner.serverDir 指定）。");
    }
    // ------------------------------------------------------------------
    // 任务提交与进度跟踪（M1-3：SSE 为主，轮询兜底）
    // ------------------------------------------------------------------
    async submitTask(msg) {
        this.stopTracking();
        try {
            const created = await this.fetchJson("/api/tasks", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    kind: "run",
                    requirement: msg.requirement,
                    models: msg.models,
                    mode: msg.mode,
                    // M12-4：插件设置页预算覆盖（0/缺省 = 服务端档位配置）
                    ...(this.budgetTokens > 0
                        ? { budget_tokens: this.budgetTokens }
                        : {}),
                }),
            });
            this.post({ command: "taskCreated", taskId: created.task_id });
            this.startTracking(created.task_id);
        }
        catch (err) {
            this.post({ command: "submitError", error: String(err) });
        }
    }
    startTracking(taskId) {
        this.stopTracking();
        // 轮询兜底（1.5s）：SSE 中断/服务不支持时进度仍可见
        this.pollTimer = setInterval(() => {
            void (async () => {
                try {
                    const task = (await this.fetchJson(`/api/tasks/${taskId}`));
                    this.post({ command: "taskUpdate", task });
                    if (TERMINAL_STATUSES.has(task.status)) {
                        this.stopTracking();
                    }
                }
                catch (err) {
                    this.post({ command: "taskUpdate", task: null, error: String(err) });
                    this.stopTracking();
                }
            })();
        }, POLL_INTERVAL_MS);
        // SSE 主通道（M8-4 事件流：阶段/逐模块/token 增量）
        void this.streamEvents(taskId);
    }
    async streamEvents(taskId) {
        this.sseController = new AbortController();
        try {
            const res = await fetch(`${this.baseUrl}/api/tasks/${taskId}/events`, {
                signal: this.sseController.signal,
            });
            if (!res.ok || !res.body) {
                throw new Error(`HTTP ${res.status}`);
            }
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            for (;;) {
                const { done, value } = await reader.read();
                if (done) {
                    break;
                }
                buffer += decoder.decode(value, { stream: true });
                let idx;
                while ((idx = buffer.indexOf("\n\n")) !== -1) {
                    const frame = buffer.slice(0, idx);
                    buffer = buffer.slice(idx + 2);
                    const dataLine = frame
                        .split("\n")
                        .find((l) => l.startsWith("data: "));
                    if (!dataLine) {
                        continue; // 心跳注释帧（": keep-alive"）等
                    }
                    const event = JSON.parse(dataLine.slice(6));
                    this.post({ command: "taskEvent", event });
                    if (event.type === "done") {
                        this.stopTracking();
                        return;
                    }
                }
            }
        }
        catch {
            // SSE 不可用（服务旧版本/网络中断）：轮询兜底已覆盖，静默降级
        }
    }
    stopTracking() {
        if (this.pollTimer) {
            clearInterval(this.pollTimer);
            this.pollTimer = undefined;
        }
        if (this.sseController) {
            this.sseController.abort();
            this.sseController = undefined;
        }
    }
    post(msg) {
        void this.view?.webview.postMessage(msg);
    }
    // ------------------------------------------------------------------
    // 历史项目 / 成本 / 一键恢复（M1-5 / M1-6 / M1-7）
    // ------------------------------------------------------------------
    /** M1-6：历史项目列表（GET /api/projects，全部项目最新优先）。 */
    async sendProjects() {
        try {
            const list = await this.fetchJson("/api/projects");
            this.post({ command: "projects", list });
        }
        catch (err) {
            this.post({ command: "projects", list: null, error: String(err) });
        }
    }
    /** M1-7：一键恢复中断任务（异步任务 API + 既有进度跟踪）。 */
    async resumeProject(projectId) {
        this.stopTracking();
        try {
            const created = await this.fetchJson("/api/tasks", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ kind: "resume", project_id: projectId }),
            });
            this.lastProjectId = projectId;
            this.post({
                command: "taskCreated",
                taskId: created.task_id,
                resumed: true,
                projectId,
            });
            this.startTracking(created.task_id);
        }
        catch (err) {
            this.post({ command: "submitError", error: String(err) });
        }
    }
    /** M1-5：成本看板（磁盘 logs/cost_report.json，8.5 审计口径）。 */
    async sendDashboard(projectId) {
        try {
            const dash = await this.fetchJson(`/api/project/${projectId}/dashboard`);
            this.post({ command: "cost", dashboard: dash, projectId });
        }
        catch (err) {
            this.post({ command: "cost", dashboard: null, error: String(err) });
        }
    }
    // ------------------------------------------------------------------
    // 生成代码：清单 / diff 预览 / 应用（M1-4）
    // ------------------------------------------------------------------
    async sendProjectFiles() {
        if (!this.lastProjectId) {
            this.post({ command: "files", files: null });
            return;
        }
        try {
            const data = await this.fetchJson(`/api/project/${this.lastProjectId}/files`);
            this.post({ command: "files", files: data.files, projectId: data.project_id });
        }
        catch (err) {
            this.post({ command: "files", files: null, error: String(err) });
        }
    }
    targetUri(relPath) {
        const root = vscode.workspace.workspaceFolders?.[0]?.uri;
        if (!root) {
            return undefined;
        }
        // 映射：code/<模块>/… → <模块>/…（tests/ 与根文件原样）
        const rel = relPath.startsWith("code/") ? relPath.slice("code/".length) : relPath;
        return vscode.Uri.joinPath(root, ...rel.split("/"));
    }
    async fetchFileContent(relPath) {
        const data = await this.fetchJson(`/api/project/${this.lastProjectId}/file?path=${encodeURIComponent(relPath)}`);
        return String(data.content);
    }
    async previewFile(relPath) {
        if (!this.lastProjectId) {
            return;
        }
        try {
            const content = await this.fetchFileContent(relPath);
            const target = this.targetUri(relPath);
            if (!target) {
                void vscode.window.showInformationMessage("请先打开一个工作区文件夹，以便预览应用到工作区的 diff。");
                return;
            }
            // 右侧：生成内容（临时文件）；左侧：工作区现状（不存在则为空文件）
            const right = vscode.Uri.file(path.join(this.tmpDir, relPath.replace(/\//g, "_")));
            fs.mkdirSync(path.dirname(right.fsPath), { recursive: true });
            fs.writeFileSync(right.fsPath, content, "utf-8");
            let left;
            if (fs.existsSync(target.fsPath)) {
                left = target;
            }
            else {
                left = vscode.Uri.file(path.join(this.tmpDir, "empty_" + relPath.replace(/\//g, "_")));
                fs.writeFileSync(left.fsPath, "", "utf-8");
            }
            await vscode.commands.executeCommand("vscode.diff", left, right, `生成预览: ${relPath}`);
        }
        catch (err) {
            void vscode.window.showErrorMessage(`预览失败: ${String(err)}`);
        }
    }
    async applyFiles(relPaths) {
        if (!this.lastProjectId || relPaths.length === 0) {
            return;
        }
        const missingWorkspace = !vscode.workspace.workspaceFolders?.length;
        if (missingWorkspace) {
            void vscode.window.showInformationMessage("请先打开一个工作区文件夹，再应用生成代码。");
            return;
        }
        try {
            const edit = new vscode.WorkspaceEdit();
            const applied = [];
            for (const relPath of relPaths) {
                const target = this.targetUri(relPath);
                if (!target) {
                    continue;
                }
                const content = await this.fetchFileContent(relPath);
                // Workspace Edit API：创建 + 插入为一次编辑组，Undo/Redo 正常（M1-4 决策）
                edit.createFile(target, { overwrite: true });
                edit.insert(target, new vscode.Position(0, 0), content);
                applied.push(relPath);
            }
            const ok = await vscode.workspace.applyEdit(edit);
            if (ok) {
                void vscode.window.showInformationMessage(`已应用 ${applied.length} 个文件到工作区（可 Undo）: ` +
                    applied.map((p) => p.replace(/^code\//, "")).join(", "));
                this.post({ command: "applied", applied });
            }
            else {
                void vscode.window.showErrorMessage("应用编辑被拒绝（部分文件无法写入）。");
            }
        }
        catch (err) {
            void vscode.window.showErrorMessage(`应用失败: ${String(err)}`);
        }
    }
    // ------------------------------------------------------------------
    // Webview 页面
    // ------------------------------------------------------------------
    buildHtml(webview) {
        const js = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "media", "main.js"));
        const css = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "media", "main.css"));
        const nonce = Array.from({ length: 16 }, () => Math.floor(Math.random() * 256).toString(16).padStart(2, "0")).join("");
        return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}';">
<link rel="stylesheet" href="${css}">
<title>Token 消耗器</title>
</head>
<body>
  <div id="server-row">
    <span id="server-dot" class="dot"></span>
    <span id="server-text">连接中…</span>
    <nav class="tabs">
      <button id="tab-task" class="tab active" type="button">任务</button>
      <button id="tab-projects" class="tab" type="button">项目</button>
    </nav>
  </div>

  <div id="guide" style="display:none">
    <p>本地服务未启动。请在 token-burner 仓库目录运行：</p>
    <pre>python -m app.server</pre>
    <div class="btns">
      <button id="btn-start-server" class="primary">在终端启动服务</button>
      <button id="btn-retry" class="ghost">重新连接</button>
    </div>
    <p class="hint">服务地址可在设置中修改：tokenBurner.serverUrl / tokenBurner.serverDir</p>
  </div>

  <div id="view-task" style="display:none">
    <form id="form" style="display:none" onsubmit="return false">
      <label class="field-label" for="requirement">需求描述</label>
      <textarea id="requirement" rows="6"
        placeholder="描述你要开发的软件需求，例如：开发一个命令行用户管理系统，支持注册、登录与数据持久化"></textarea>

      <label class="field-label">模型（主 LLM / 开发副 / 测试副，须互不相同）</label>
      <div class="models">
        <select id="main-model" title="主 LLM"></select>
        <select id="dev-model" title="开发副 LLM"></select>
        <select id="test-model" title="测试副 LLM"></select>
      </div>
      <div id="budget-hint" class="hint" style="display:none"></div>

      <label class="field-label">执行模式</label>
      <label class="radio"><input type="radio" name="mode" value="safe" checked>
        安全审阅（不执行代码，交付后手动运行反馈）</label>
      <label class="radio"><input type="radio" name="mode" value="auto">
        自动验证（真实执行生成代码）</label>
      <div id="auto-warn" class="warn" style="display:none"></div>

      <button id="btn-submit" class="primary" type="submit">开始任务</button>
    </form>

    <div id="progress-wrap" style="display:none">
      <div class="progress-track"><div id="progress-bar" class="progress-fill"></div></div>
      <div id="progress-text" class="hint"></div>
      <details id="log-details" open>
        <summary>执行日志</summary>
        <div id="log" class="log"></div>
      </details>
    </div>

    <div id="status" style="display:none"></div>
    <div id="result" style="display:none"></div>
    <div id="files" style="display:none">
      <div class="field-label">生成代码（应用到当前工作区，可 Undo）</div>
      <div id="file-list"></div>
      <div class="btns">
        <button id="btn-apply" class="primary">应用所选文件</button>
        <button id="btn-refresh-files" class="ghost">刷新清单</button>
      </div>
    </div>

    <!-- M1-5 成本统计 -->
    <div id="cost" style="display:none">
      <div class="field-label">成本看板</div>
      <div class="progress-track"><div id="cost-bar" class="progress-fill"></div></div>
      <div id="cost-text" class="hint" style="margin:4px 0 6px;"></div>
      <table id="cost-table"><tbody></tbody></table>
    </div>
  </div>

  <!-- M1-6/M1-7 历史项目列表 -->
  <div id="view-projects" style="display:none">
    <div class="btns">
      <button id="btn-refresh-projects" class="ghost">刷新列表</button>
    </div>
    <div id="proj-list"></div>
  </div>

  <script nonce="${nonce}" src="${js}"></script>
</body>
</html>`;
    }
}
//# sourceMappingURL=extension.js.map