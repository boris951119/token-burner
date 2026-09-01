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
      case "defaults":                    // M12-4：插件默认值（预算/默认模型）
        applyDefaults(msg);
        break;
      case "taskCreated":
        switchTab("task");
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
      case "projects":
        renderProjects(msg);   // M1-6 历史项目列表
        break;
      case "cost":
        renderCost(msg);       // M1-5 成本看板
        break;
    }
  });

  // ------------------------------------------------------------------
  // 视图 Tab（任务 / 项目）
  // ------------------------------------------------------------------

  function switchTab(name) {
    const task = name === "task";
    $("tab-task").classList.toggle("active", task);
    $("tab-projects").classList.toggle("active", !task);
    $("view-task").style.display = task ? "block" : "none";
    $("view-projects").style.display = task ? "none" : "block";
    if (!task) {
      vscode.postMessage({ command: "loadProjects" });   // M1-6
    }
  }
  $("tab-task").addEventListener("click", () => switchTab("task"));
  $("tab-projects").addEventListener("click", () => switchTab("projects"));
  $("btn-refresh-projects").addEventListener("click", () => {
    vscode.postMessage({ command: "loadProjects" });
  });

  // ------------------------------------------------------------------
  // 服务连接状态
  // ------------------------------------------------------------------

  function renderServerState(msg) {
    const ok = msg.ok;
    $("server-dot").className = "dot " + (ok ? "ok" : "bad");
    $("server-text").textContent = ok ? "本地服务已连接" : "本地服务未启动";
    $("guide").style.display = ok ? "none" : "block";
    $("view-task").style.display = ok ? "block" : "none";
    $("view-projects").style.display = "none";
    $("tab-task").classList.toggle("active", ok);
    $("tab-projects").classList.remove("active");
    $("tab-task").style.display = ok ? "inline-block" : "none";
    $("tab-projects").style.display = ok ? "inline-block" : "none";
    if (ok) {
      serverConfig = msg.config || {};
      fillModelSelects(serverConfig.models || []);
      if (msg.defaults) applyDefaults(msg.defaults);   // M12-4
    }
  }

  /* M12-4：插件设置页默认值（预算 / 默认模型），设置变更即时生效 */
  let panelDefaults = { models: [], budgetTokens: 0 };

  function applyDefaults(defaults) {
    panelDefaults = {
      models: Array.isArray(defaults.models) ? defaults.models : [],
      budgetTokens: Number(defaults.budgetTokens) || 0,
    };
    // 默认模型：按序预选（值必须在服务端预设列表内才可选中）
    const [main, dev, test] = panelDefaults.models;
    if (main) $("main-model").value = main;
    if (dev) $("dev-model").value = dev;
    if (test) $("test-model").value = test;
    // 预算提示（0 = 服务端档位配置）
    const budgetHint = $("budget-hint");
    if (budgetHint) {
      budgetHint.textContent = panelDefaults.budgetTokens > 0
        ? "任务预算：约 " + panelDefaults.budgetTokens.toLocaleString() +
          " token（来自插件设置 tokenBurner.budgetTokens）"
        : "";
      budgetHint.style.display = panelDefaults.budgetTokens > 0 ? "block" : "none";
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
      vscode.postMessage({ command: "fetchCost", projectId });  // M1-5 成本看板
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

  // ------------------------------------------------------------------
  // M1-6 历史项目列表
  // ------------------------------------------------------------------

  function renderProjects(msg) {
    const box = $("proj-list");
    box.innerHTML = "";
    if (msg.error || !msg.list) {
      box.innerHTML = '<div class="empty">加载失败：' + escapeText(msg.error || "") + "</div>";
      return;
    }
    if (!msg.list.length) {
      box.innerHTML = '<div class="empty">还没有项目 —— 在「任务」页发起第一个开发任务。</div>';
      return;
    }
    for (const p of msg.list) {
      const row = document.createElement("div");
      row.className = "proj";
      const title = p.requirement || p.project_id;

      const info = document.createElement("div");
      info.className = "proj-info";
      const name = document.createElement("div");
      name.className = "proj-name";
      name.textContent = title;
      name.title = p.project_id;
      const meta = document.createElement("div");
      meta.className = "proj-meta";
      const modeTag = document.createElement("span");
      modeTag.className = "tag " + (p.mode === "auto" ? "tag-auto" : "tag-safe");
      modeTag.textContent = p.mode === "auto" ? "自动验证" : "安全模式";
      meta.appendChild(modeTag);
      if (p.interrupted) {
        const bad = document.createElement("span");
        bad.className = "tag tag-bad";
        bad.textContent = "已中断";
        meta.appendChild(bad);
      }
      const cnt = document.createElement("span");
      cnt.textContent = (p.tokens || 0).toLocaleString() + " token";
      meta.appendChild(cnt);
      if (p.updated) {
        const up = document.createElement("span");
        up.textContent = p.updated;
        meta.appendChild(up);
      }
      info.appendChild(name);
      info.appendChild(meta);

      const ops = document.createElement("div");
      ops.className = "proj-ops";
      if (p.has_state) {
        const resume = document.createElement("button");
        resume.className = "primary";
        resume.textContent = "▶ 继续";
        resume.addEventListener("click", () => {
          vscode.postMessage({ command: "resumeProject", projectId: p.project_id });
        });
        ops.appendChild(resume);
      }
      if (p.tokens) {
        const cost = document.createElement("button");
        cost.className = "ghost";
        cost.textContent = "成本";
        cost.addEventListener("click", () => {
          vscode.postMessage({ command: "fetchCost", projectId: p.project_id });
        });
        ops.appendChild(cost);
      }

      row.appendChild(info);
      row.appendChild(ops);
      box.appendChild(row);
    }
  }

  // ------------------------------------------------------------------
  // M1-5 成本看板（预算条 + 按模型明细）
  // ------------------------------------------------------------------

  function renderCost(msg) {
    const wrap = $("cost");
    if (msg.error || !msg.dashboard) {
      wrap.style.display = "block";
      $("cost-bar").style.width = "0%";
      $("cost-text").textContent = "看板加载失败：" + (msg.error || "无数据");
      $("cost-table").querySelector("tbody").innerHTML = "";
      return;
    }
    const d = msg.dashboard;
    const total = d.total_tokens || 0;
    const budget = d.budget_tokens || 1;
    const ratio = Math.min(100, Math.round(total / budget * 100));
    wrap.style.display = "block";
    $("cost-bar").style.width = ratio + "%";
    $("cost-bar").className = "progress-fill" + (ratio >= 90 ? " bad" : "");
    let text = total.toLocaleString() + " / " + budget.toLocaleString() +
      " token（" + ratio + "%）";
    const sav = d.savings;
    if (sav && sav.saved_tokens > 0) {
      text += " · 已节省 " + sav.saved_tokens.toLocaleString() +
        "（" + Math.round(sav.saved_ratio * 100) + "% · 命中 " +
        Math.round(sav.cache_hit_rate * 100) + "%）";
    }
    $("cost-text").textContent = text;
    const tbody = $("cost-table").querySelector("tbody");
    tbody.innerHTML = "";
    for (const [model, tok] of Object.entries(d.by_model || {})) {
      const tr = document.createElement("tr");
      const td1 = document.createElement("td");
      td1.textContent = model;
      const td2 = document.createElement("td");
      td2.className = "num";
      td2.textContent = Number(tok).toLocaleString();
      tr.appendChild(td1);
      tr.appendChild(td2);
      tbody.appendChild(tr);
    }
    switchTab("task");
  }

  function escapeText(s) {
    return String(s);
  }

  vscode.postMessage({ command: "ready" });
})();
