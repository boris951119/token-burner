/** token-burner 面板逻辑（M1-2 任务发起 / M1-3 实时进度 / M1-4 代码应用）。
 *  HTTP 全在扩展宿主侧；本文件只做 UI 渲染与消息。 */
(function () {
  "use strict";

  const vscode = acquireVsCodeApi();
  const $ = (id) => document.getElementById(id);

  let serverConfig = null;
  let projectFiles = [];       // [{relPath, checked}]
  let projectId = null;
  const logLines = [];

  // ------------------------------------------------------------------
  // 宿主 → 面板消息
  // ------------------------------------------------------------------

  window.addEventListener("message", (event) => {
    const msg = event.data;
    switch (msg.command) {
      case "serverState":
        renderServerState(msg);
        break;
      case "taskCreated":
        resetRunView(msg.taskId);
        break;
      case "taskEvent":
        renderTaskEvent(msg.event);
        break;
      case "taskUpdate":
        renderTaskUpdate(msg);
        break;
      case "submitError":
        showStatus("提交失败：" + msg.error, true);
        setBusy(false);
        break;
      case "files":
        renderFiles(msg);
        break;
      case "applied":
        log("已应用 " + msg.applied.length + " 个文件到工作区");
        break;
    }
  });

  // ------------------------------------------------------------------
  // 服务连接状态
  // ------------------------------------------------------------------

  function renderServerState(msg) {
    const ok = msg.ok;
    $("server-dot").className = "dot " + (ok ? "ok" : "bad");
    $("server-text").textContent = ok ? "本地服务已连接" : "本地服务未启动";
    $("guide").style.display = ok ? "none" : "block";
    $("form").style.display = ok ? "block" : "none";
    if (ok) {
      serverConfig = msg.config || {};
      fillModelSelects(serverConfig.models || []);
    }
  }

  function fillModelSelects(models) {
    const ids = ["main-model", "dev-model", "test-model"];
    for (const id of ids) {
      const sel = $(id);
      sel.innerHTML = "";
      for (const m of models) {
        const opt = document.createElement("option");
        opt.value = m;
        opt.textContent = m;
        sel.appendChild(opt);
      }
      sel.onchange = warnIfSameModels;
    }
    if (models.length >= 3) {  // 默认前三互异（3.3）
      $("main-model").value = models[0];
      $("dev-model").value = models[1];
      $("test-model").value = models[2];
    }
  }

  function warnIfSameModels() {
    if (sameModelsSelected()) {
      showStatus("提示：三个模型必须互不相同（规格 3.3）", true);
    }
  }

  function sameModelsSelected() {
    return (
      $("main-model").value === $("dev-model").value ||
      $("main-model").value === $("test-model").value ||
      $("dev-model").value === $("test-model").value
    );
  }

  // ------------------------------------------------------------------
  // 模式与预算警示（3.6.3：成本放大明示）
  // ------------------------------------------------------------------

  document.querySelectorAll('input[name="mode"]').forEach((radio) => {
    radio.addEventListener("change", renderAutoWarning);
  });

  function renderAutoWarning() {
    const auto = document.querySelector('input[name="mode"]:checked').value === "auto";
    const warn = $("auto-warn");
    if (!auto || !serverConfig) {
      warn.style.display = "none";
      return;
    }
    warn.textContent =
      "自动验证模式将真实执行 LLM 生成代码（危险 API 预扫描 + 超时熔断），" +
      "预算放大 ×" + serverConfig.auto_budget_multiplier +
      "：" + serverConfig.auto_budget_tokens +
      " token（安全模式 " + serverConfig.budget_tokens + "）。";
    warn.style.display = "block";
  }

  // ------------------------------------------------------------------
  // 任务提交
  // ------------------------------------------------------------------

  document.getElementById("btn-submit").addEventListener("click", () => {
    const requirement = $("requirement").value.trim();
    if (!requirement) {
      showStatus("请先输入需求描述", true);
      return;
    }
    if (sameModelsSelected()) {
      showStatus("三个模型必须互不相同（规格 3.3）", true);
      return;
    }
    const mode = document.querySelector('input[name="mode"]:checked').value;
    setBusy(true);
    vscode.postMessage({
      command: "submit",
      requirement: requirement,
      models: [$("main-model").value, $("dev-model").value, $("test-model").value],
      mode: mode,
    });
  });

  function resetRunView(taskId) {
    showStatus("任务已提交：" + taskId);
    setResult("");
    logLines.length = 0;
    $("log").textContent = "";
    $("progress-wrap").style.display = "block";
    $("progress-bar").style.width = "2%";
    $("progress-text").textContent = "排队中…";
    $("files").style.display = "none";
    $("file-list").innerHTML = "";
    projectFiles = [];
    projectId = null;
  }

  // ------------------------------------------------------------------
  // M1-3 实时进度（SSE 事件 / 轮询快照双通道）
  // ------------------------------------------------------------------

  function renderTaskEvent(event) {
    // SSE 事件流（M8-4）：stage / tokens / module_done / done / snapshot
    if (event.type === "snapshot") {
      const t = event.task || {};
      if (t.stage) { setStage(t.stage); }
      if (typeof t.tokens_used === "number") { setTokens(t.tokens_used); }
      return;
    }
    if (event.type === "stage") {
      setStage(event.stage);
      log("▶ 进入阶段：" + event.stage);
      setTokens(event.tokens);
    } else if (event.type === "module_done") {
      log("✓ 模块完成：" + event.module + "（" + event.status +
          "，修复 " + event.fix_attempts + " 次）");
      bumpModuleProgress();
      setTokens(event.tokens);
    } else if (event.type === "tokens") {
      setTokens(event.tokens);
    } else if (event.type === "done") {
      finishTask(event.status === "succeeded",
                 event.result || null, event.error || "");
    }
  }

  function renderTaskUpdate(msg) {
    // 轮询快照（兜底通道）
    if (!msg.task) {
      showStatus("轮询失败：" + msg.error, true);
      setBusy(false);
      return;
    }
    const t = msg.task;
    if (t.status === "pending" || t.status === "running") {
      if (t.stage) { setStage(t.stage); }
      setTokens(t.tokens_used);
    } else if (TERMINAL(t.status)) {
      finishTask(t.status === "succeeded", t.result || null, t.error || "");
    }
  }

  function TERMINAL(s) { return s === "succeeded" || s === "failed" || s === "cancelled"; }

  // 阶段权重进度条（启发式：阶段定基点，模块完成递增）
  const STAGE_PROGRESS = {
    "方案讨论": 10,
    "模块拆分与接口契约": 20,
    "模块开发": 25,
    "反馈修复": 92,
  };
  let moduleCount = 0;

  function setStage(stage) {
    $("progress-text").textContent = "阶段：" + stage + " ｜ " + tokenText();
    const base = STAGE_PROGRESS[stage];
    if (base !== undefined && base < currentProgress() ) {
      /* 不回退 */
    } else if (base !== undefined) {
      $("progress-bar").style.width = base + "%";
    }
    if (stage === "反馈修复") { $("progress-bar").style.width = "92%"; }
  }

  function bumpModuleProgress() {
    moduleCount += 1;
    const next = Math.min(90, 25 + moduleCount * 12);
    $("progress-bar").style.width = next + "%";
  }

  function currentProgress() {
    return parseInt($("progress-bar").style.width, 10) || 0;
  }

  let tokensUsed = 0;
  function setTokens(n) {
    if (typeof n !== "number") { return; }
    tokensUsed = n;
    const stage = $("progress-text").textContent.match(/阶段：([^｜]*)/);
    $("progress-text").textContent =
      "阶段：" + (stage ? stage[1].trim() : "—") + " ｜ " + tokenText();
  }
  function tokenText() { return "已耗 token：" + tokensUsed; }

  function log(line) {
    const stamp = new Date().toTimeString().slice(0, 8);
    logLines.push("[" + stamp + "] " + line);
    if (logLines.length > 200) { logLines.shift(); }
    $("log").textContent = logLines.join("\n");
    $("log").scrollTop = $("log").scrollHeight;
  }

  // ------------------------------------------------------------------
  // 终态渲染 + M1-4 文件清单
  // ------------------------------------------------------------------

  function finishTask(succeeded, result, error) {
    setBusy(false);
    stopUiForTerminal();
    if (!succeeded) {
      $("progress-bar").style.width = "100%";
      $("progress-bar").className = "progress-fill bad";
      showStatus("❌ 任务失败：" + (error || "未知错误"), true);
      return;
    }
    $("progress-bar").style.width = "100%";
    $("progress-text").textContent = "完成 ｜ " + tokenText();
    const kind = result.kind || "done";
    let lines = ["✅ 任务完成（" + kind + "）"];
    if (kind === "direct_answer" && result.answer) {
      lines.push("", String(result.answer).slice(0, 800));
    }
    if (result.project_dir) {
      lines.push("项目目录：" + result.project_dir);
      projectId = result.project_id;
    }
    if (result.frozen_modules && result.frozen_modules.length) {
      lines.push("冻结模块：" + result.frozen_modules.join(", "));
    }
    showStatus(lines.join("\n"));
    if (result.deliverable_summary) { setResult(result.deliverable_summary); }
    if (projectId) {
      vscode.postMessage({ command: "fetchFiles" });  // 拉取生成代码清单（M1-4）
    }
  }

  function stopUiForTerminal() {
    /* 保留日志与进度条终态显示；输入重新可用 */
  }

  function renderFiles(msg) {
    if (msg.error || !msg.files) {
      showStatus("获取文件清单失败：" + (msg.error || "无文件"), true);
      return;
    }
    projectFiles = (msg.files || []).map((p) => ({ relPath: p, checked: true }));
    const list = $("file-list");
    list.innerHTML = "";
    for (const f of projectFiles) {
      const row = document.createElement("div");
      row.className = "file-row";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = true;
      cb.id = "f_" + f.relPath;
      cb.addEventListener("change", () => { f.checked = cb.checked; });
      const label = document.createElement("label");
      label.htmlFor = cb.id;
      label.textContent = f.relPath.replace(/^code\//, "");
      const preview = document.createElement("a");
      preview.textContent = "预览 diff";
      preview.href = "#";
      preview.addEventListener("click", (e) => {
        e.preventDefault();
        vscode.postMessage({ command: "previewFile", path: f.relPath });
      });
      row.appendChild(cb);
      row.appendChild(label);
      row.appendChild(preview);
      list.appendChild(row);
    }
    $("files").style.display = projectFiles.length ? "block" : "none";
  }

  document.getElementById("btn-apply").addEventListener("click", () => {
    const selected = projectFiles.filter((f) => f.checked).map((f) => f.relPath);
    if (!selected.length) {
      showStatus("请先勾选要应用的文件", true);
      return;
    }
    vscode.postMessage({ command: "applyFiles", paths: selected });
  });
  document.getElementById("btn-refresh-files").addEventListener("click", () => {
    vscode.postMessage({ command: "fetchFiles" });
  });

  // ------------------------------------------------------------------
  // 引导按钮与小工具
  // ------------------------------------------------------------------

  document.getElementById("btn-start-server").addEventListener("click", () => {
    vscode.postMessage({ command: "startServer" });
  });
  document.getElementById("btn-retry").addEventListener("click", () => {
    showStatus("正在重新连接…");
    vscode.postMessage({ command: "reconnect" });
  });

  function showStatus(text, isError) {
    const el = $("status");
    el.style.display = "block";
    el.textContent = text;
    el.className = isError ? "status bad" : "status";
  }

  function setResult(text) {
    const el = $("result");
    if (!text) {
      el.style.display = "none";
      el.textContent = "";
      return;
    }
    el.style.display = "block";
    el.textContent = text;
  }

  function setBusy(busy) {
    $("btn-submit").disabled = busy;
    $("btn-submit").textContent = busy ? "任务执行中…" : "开始任务";
  }

  vscode.postMessage({ command: "ready" });
})();
