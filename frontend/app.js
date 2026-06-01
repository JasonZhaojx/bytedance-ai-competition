let currentJobId = "";
let pollTimer = null;
let isSubmitting = false;
let lastReportName = "";
let currentReportName = "";
let allReportsCache = [];
let allIssuesCache = [];
let issueGroupsCache = [];
let issuesLoaded = false;
let issuesLoading = false;
let currentWizardStep = 1;
let selectionPanelJobId = "";
let selectionPanelCandidatesKey = "";

const $ = (selector) => document.querySelector(selector);

const productDescription = $("#productDescription");
const candidatePreview = $("#candidatePreview");
const llmProvider = $("#llmProvider");
const topN = $("#topN");
const queryCount = $("#queryCount");
const searchCount = $("#searchCount");
const searchBackend = $("#searchBackend");
const qualityMode = $("#qualityMode");
const maxIterations = $("#maxIterations");
const analyzeTimeout = $("#analyzeTimeout");
const finalSummaryTimeout = $("#finalSummaryTimeout");
const evidenceMode = $("#evidenceMode");
const feedbackQueries = $("#feedbackQueries");
const feedbackBackend = $("#feedbackBackend");
const knownParamMaxChars = $("#knownParamMaxChars");
const questionnaireMaxChars = $("#questionnaireMaxChars");
const retryOnMinor = $("#retryOnMinor");
const enableQualityLoop = $("#enableQualityLoop");
const arkApiKey = $("#arkApiKey");
const bochaApiKey = $("#bochaApiKey");
const googleApiKey = $("#googleApiKey");
const googleCxId = $("#googleCxId");
const llmBaseUrl = $("#llmBaseUrl");
const llmModel = $("#llmModel");
const settingsTopN = $("#settingsTopN");
const settingsQualityMode = $("#settingsQualityMode");
const settingsMaxIterations = $("#settingsMaxIterations");
const settingsEnableQualityLoop = $("#settingsEnableQualityLoop");
const saveSettingsBtn = $("#saveSettingsBtn");
const knownParamFile = $("#knownParamFile");
const knownParamText = $("#knownParamText");
const questionnaireFile = $("#questionnaireFile");
const questionnaireText = $("#questionnaireText");
const startBtn = $("#startBtn");
const refreshBtn = $("#refreshBtn");
const serverStatus = $("#serverStatus");
const jobMeta = $("#jobMeta");
const jobStatus = $("#jobStatus");
const reportName = $("#reportName");
const logBox = $("#logBox");
const runtimeLogBox = $("#runtimeLogBox");
const threadName = $("#threadName");
const processPid = $("#processPid");
const idleSeconds = $("#idleSeconds");
const reportSelect = $("#reportSelect");
const reportViewer = $("#reportViewer");
const resultSummary = $("#resultSummary");
const issuePanel = $("#issuePanel");
const downloadBtn = $("#downloadBtn");
const navButtons = Array.from(document.querySelectorAll(".nav-list button"));
const pagePanels = Array.from(document.querySelectorAll("[data-page-panel]"));
const reportLibrary = $("#reportLibrary");
const reloadReportsBtn = $("#reloadReportsBtn");
const reportSidePanel = $("#reportSidePanel");
const reportSideBackdrop = $("#reportSideBackdrop");
const closeSideReportBtn = $("#closeSideReportBtn");
const sideReportType = $("#sideReportType");
const sideReportTitle = $("#sideReportTitle");
const sideReportName = $("#sideReportName");
const sideReportSummary = $("#sideReportSummary");
const sideReportViewer = $("#sideReportViewer");
const sideDownloadBtn = $("#sideDownloadBtn");
const qualityLoopStatus = $("#qualityLoopStatus");
const qualityCenterStatus = $("#qualityCenterStatus");
const qualityModePreview = $("#qualityModePreview");
const maxIterationPreview = $("#maxIterationPreview");
const timeMetric = $("#timeMetric");
const coverageMetric = $("#coverageMetric");
const consistencyMetric = $("#consistencyMetric");
const coverageHelp = $("#coverageHelp");
const consistencyHelp = $("#consistencyHelp");
const qualityIssueList = $("#qualityIssueList");
const wizardTabs = Array.from(document.querySelectorAll("[data-step-target]"));
const wizardPanels = Array.from(document.querySelectorAll("[data-wizard-step]"));
const prevStepBtn = $("#prevStepBtn");
const nextStepBtn = $("#nextStepBtn");
const wizardStepMeta = $("#wizardStepMeta");
const subtaskList = $("#subtaskList");
const subtaskMeta = $("#subtaskMeta");
const productSelectionPanel = $("#productSelectionPanel");
const productSelectionBackdrop = $("#productSelectionBackdrop");
const candidateProductList = $("#candidateProductList");
const manualProductAdd = $("#manualProductAdd");
const submitProductSelectionBtn = $("#submitProductSelectionBtn");

startBtn.addEventListener("click", startJob);
refreshBtn.addEventListener("click", handleRefresh);
reloadReportsBtn?.addEventListener("click", () => loadReports({ preserveSelection: true }));
closeSideReportBtn?.addEventListener("click", closeReportSidePanel);
reportSideBackdrop?.addEventListener("click", closeReportSidePanel);
submitProductSelectionBtn?.addEventListener("click", submitProductSelection);
reportSelect.addEventListener("change", () => {
  if (reportSelect.value) loadReport(reportSelect.value);
});
knownParamFile.addEventListener("change", () => readFileInto(knownParamFile, knownParamText));
questionnaireFile.addEventListener("change", () => readFileInto(questionnaireFile, questionnaireText));
qualityMode.addEventListener("change", updateQualityPreview);
maxIterations.addEventListener("input", updateQualityPreview);
enableQualityLoop.addEventListener("change", updateQualityPreview);
saveSettingsBtn?.addEventListener("click", saveSettings);
prevStepBtn?.addEventListener("click", () => showWizardStep(currentWizardStep - 1));
nextStepBtn?.addEventListener("click", () => showWizardStep(currentWizardStep + 1));
wizardTabs.forEach((button) => {
  button.addEventListener("click", () => showWizardStep(Number(button.dataset.stepTarget)));
});
for (const button of navButtons) {
  button.addEventListener("click", () => showPage(button.dataset.page));
}

document.addEventListener("DOMContentLoaded", () => {
  loadSettings();
  refresh();
  updateQualityPreview();
  showWizardStep(1);
  initKeyboardShortcuts();
});

function initKeyboardShortcuts() {
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !isSubmitting) {
      event.preventDefault();
      startJob();
    }
  });
}

async function startJob() {
  const description = productDescription.value.trim();
  if (!description) {
    productDescription.focus();
    showToast("请输入产品需求", "error");
    return;
  }
  if (isSubmitting) return;

  isSubmitting = true;
  currentReportName = "";
  lastReportName = "";
  selectionPanelJobId = "";
  selectionPanelCandidatesKey = "";
  closeProductSelectionPanel();
  clearTimeout(pollTimer);
  setStartButtonLoading(true);
  serverStatus.textContent = "Starting";

  const payload = {
    product_description: description,
    llm_provider: llmProvider.value,
    top_n: Number(topN.value || 5),
    query_count: Number(queryCount.value || 3),
    search_count: Number(searchCount.value || 3),
    search_backend: Number(searchBackend.value || 2),
    quality_mode: qualityMode.value,
    max_iterations: Number(maxIterations.value || 3),
    analyze_timeout: Number(analyzeTimeout.value || 1200),
    final_summary_timeout: Number(finalSummaryTimeout.value || 900),
    evidence_mode: Number(evidenceMode.value || 2),
    feedback_queries: Number(feedbackQueries.value || 2),
    quality_feedback_search_backend: Number(feedbackBackend.value || 0),
    known_param_max_chars: Number(knownParamMaxChars.value || 0),
    questionnaire_max_chars: Number(questionnaireMaxChars.value || 0),
    retry_on_minor: retryOnMinor.checked,
    enable_quality_loop: enableQualityLoop.checked,
    ark_api_key: arkApiKey.value.trim(),
    bocha_api_key: bochaApiKey.value.trim(),
    google_api_key: googleApiKey.value.trim(),
    google_cx_id: googleCxId.value.trim(),
    llm_base_url: llmBaseUrl.value.trim(),
    llm_model: llmModel.value.trim(),
    known_param_text: knownParamText.value,
    questionnaire_analysis_text: questionnaireText.value,
  };

  try {
    const job = await api("/api/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    currentJobId = job.job_id;
    renderJob(job);
    showToast("任务已启动，正在执行主流程", "success");
    pollJob();
  } catch (error) {
    serverStatus.textContent = "Error";
    logBox.textContent = String(error);
    showToast("启动失败: " + error.message, "error");
    setStartButtonLoading(false);
  }
}

function setStartButtonLoading(loading) {
  isSubmitting = loading;
  startBtn.disabled = loading;
  startBtn.classList.toggle("loading", loading);
  startBtn.innerHTML = loading ? "<span>分析中...</span>" : "<span>开始分析</span>";
}

async function handleRefresh() {
  refreshBtn.disabled = true;
  await refresh();
  setTimeout(() => {
    refreshBtn.disabled = false;
  }, 300);
}

async function refresh() {
  await loadReports();
  if (currentJobId) await pollJob();
}

async function pollJob() {
  if (!currentJobId) return;

  try {
    const job = await api(`/api/jobs/${currentJobId}`);
    renderJob(job);

    if (job.status === "running" || job.status === "queued") {
      if (job.report_name && job.report_name !== lastReportName) {
        lastReportName = job.report_name;
        loadReport(job.report_name);
      }
      clearTimeout(pollTimer);
      pollTimer = setTimeout(pollJob, 2500);
      return;
    }

    clearTimeout(pollTimer);
    lastReportName = "";
    if (job.report_name) {
      await loadReport(job.report_name);
    } else {
      await loadReports();
    }
    setStartButtonLoading(false);

    if (job.status === "completed") {
      showToast("任务完成，报告已生成", "success");
    } else if (job.status === "failed") {
      showToast("任务失败，请查看 Agent 决策回放", "error");
    }
  } catch (error) {
    clearTimeout(pollTimer);
    setStartButtonLoading(false);
    showToast("获取任务状态失败: " + error.message, "error");
  }
}

function renderJob(job) {
  serverStatus.textContent = job.status;
  jobStatus.textContent = job.status;
  const desc = job.product_description || "";
  jobMeta.textContent = desc.length > 46 ? desc.slice(0, 46) + "..." : desc || "尚未启动任务";
  reportName.textContent = job.report_name || "生成中";
  logBox.textContent = (job.logs || []).join("\n") || "等待任务日志...";
  logBox.scrollTop = logBox.scrollHeight;
  renderRuntimeState(job);
  renderSubtasks(job);
  maybeOpenProductSelection(job);
  renderNodeFlow(job);
  setQualityStatus(stageLabel(job.stage || job.status));
  updateBusinessMetrics(job);
}

function showWizardStep(step) {
  currentWizardStep = Math.max(1, Math.min(4, step));
  wizardPanels.forEach((panel) => {
    panel.classList.toggle("active", Number(panel.dataset.wizardStep) === currentWizardStep);
  });
  wizardTabs.forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.stepTarget) === currentWizardStep);
  });
  if (prevStepBtn) prevStepBtn.disabled = currentWizardStep === 1;
  if (nextStepBtn) nextStepBtn.disabled = currentWizardStep === 4;
  if (wizardStepMeta) wizardStepMeta.textContent = `步骤 ${currentWizardStep} / 4`;
}

function renderRuntimeState(job) {
  threadName.textContent = job.thread_name || (job.thread_alive ? "queued" : "未启动");
  processPid.textContent = job.process_pid || "-";
  idleSeconds.textContent =
    typeof job.idle_seconds === "number" ? `${job.idle_seconds}s` : "-";
  const runtimeLines = [
    `status=${job.status} stage=${job.stage} thread_alive=${job.thread_alive}`,
    `pid=${job.process_pid || "-"} started=${formatTimestamp(job.started_at)} finished=${formatTimestamp(job.finished_at)}`,
    ...(job.runtime_logs || []),
  ];
  runtimeLogBox.textContent = runtimeLines.join("\n") || "等待主线程事件...";
  runtimeLogBox.scrollTop = runtimeLogBox.scrollHeight;
}

function renderSubtasks(job) {
  const queries = job.search_queries || [];
  const candidates = job.candidate_products || [];
  const subtasks = job.subtasks || [];
  const chunks = [];

  if (queries.length) {
    chunks.push(`
      <div class="subtask-group">
        <span>搜索词 ${queries.length}</span>
        ${queries.map((query) => `<p>${escapeHtml(query)}</p>`).join("")}
      </div>
    `);
  }
  if (candidates.length) {
    chunks.push(`
      <div class="subtask-group">
        <span>候选产品 ${candidates.length}</span>
        ${candidates.map((name) => `<p>${escapeHtml(name)}</p>`).join("")}
      </div>
    `);
  }
  if (subtasks.length) {
    chunks.push(`
      <div class="subtask-group">
        <span>分析子任务 ${subtasks.length}</span>
        ${subtasks
          .map(
            (task) => `
              <div class="subtask-item ${escapeHtml(task.status || "queued")}">
                <strong>${escapeHtml(task.name)}</strong>
                <em>${escapeHtml(subtaskStatusLabel(task.status))}</em>
              </div>
            `
          )
          .join("")}
      </div>
    `);
  }

  subtaskMeta.textContent =
    queries.length || candidates.length || subtasks.length
      ? `${queries.length} 搜索词 · ${candidates.length} 候选 · ${subtasks.length} 子任务`
      : "等待搜索";
  subtaskList.innerHTML = chunks.join("") || `<div class="subtask-empty">等待主流程输出搜索词和候选产品。</div>`;
  if (candidatePreview) {
    candidatePreview.innerHTML = candidates.length
      ? candidates.map((name) => `<span class="report-tag">${escapeHtml(name)}</span>`).join("")
      : `<span>初步搜索完成后，这里会同步显示候选产品，并弹出选择面板。</span>`;
  }
}

function maybeOpenProductSelection(job) {
  if (!productSelectionPanel || !candidateProductList) return;
  const candidatesKey = (job.candidate_products || []).join("|");
  if (job.waiting_for_selection && !job.selection_submitted && (job.job_id !== selectionPanelJobId || candidatesKey !== selectionPanelCandidatesKey)) {
    selectionPanelJobId = job.job_id;
    selectionPanelCandidatesKey = candidatesKey;
    openProductSelectionPanel(job);
  }
}

function openProductSelectionPanel(job) {
  const candidates = job.candidate_products || [];
  const previouslySelected = new Set(selectedProductNames());
  const manualValue = manualProductAdd?.value || "";
  productSelectionPanel.classList.add("open");
  productSelectionPanel.setAttribute("aria-hidden", "false");
  if (productSelectionBackdrop) productSelectionBackdrop.hidden = false;
  if (manualProductAdd) manualProductAdd.value = manualValue;
  candidateProductList.innerHTML = candidates.length
    ? candidates
        .map(
          (name, index) => `
            <label class="candidate-option">
              <input type="checkbox" value="${escapeHtml(name)}" ${previouslySelected.has(name) ? "checked" : ""} />
              <span>${index + 1}. ${escapeHtml(name)}</span>
            </label>
          `
        )
        .join("")
    : `<div class="issue-empty">还没有候选产品。可以先手动填写要分析的产品名。</div>`;
  updateProductSelectionButton();
  candidateProductList.querySelectorAll("input[type='checkbox']").forEach((input) => {
    input.addEventListener("change", updateProductSelectionButton);
  });
  manualProductAdd?.addEventListener("input", updateProductSelectionButton);
}

function closeProductSelectionPanel() {
  productSelectionPanel?.classList.remove("open");
  productSelectionPanel?.setAttribute("aria-hidden", "true");
  if (productSelectionBackdrop) productSelectionBackdrop.hidden = true;
}

function selectedProductNames() {
  const checked = Array.from(candidateProductList?.querySelectorAll("input:checked") || []).map((item) => item.value.trim());
  const manual = (manualProductAdd?.value || "")
    .split(/[,，、\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  return Array.from(new Set([...checked, ...manual]));
}

function updateProductSelectionButton() {
  if (!submitProductSelectionBtn) return;
  submitProductSelectionBtn.disabled = selectedProductNames().length === 0;
}

async function submitProductSelection() {
  if (!currentJobId || !submitProductSelectionBtn) return;
  const products = selectedProductNames();
  if (!products.length) {
    showToast("请至少选择或手动添加一个产品", "warning");
    return;
  }
  submitProductSelectionBtn.disabled = true;
  try {
    const job = await api(`/api/jobs/${currentJobId}/selection`, {
      method: "POST",
      body: JSON.stringify({ selection: products.join(", ") }),
    });
    closeProductSelectionPanel();
    renderJob(job);
    showToast("产品选择已提交，继续分析", "success");
    clearTimeout(pollTimer);
    pollTimer = setTimeout(pollJob, 800);
  } catch (error) {
    showToast("提交产品选择失败: " + error.message, "error");
    updateProductSelectionButton();
  }
}

function subtaskStatusLabel(status) {
  return {
    queued: "排队",
    running: "运行中",
    done: "完成",
    failed: "失败",
  }[status] || status || "排队";
}

function renderNodeFlow(job) {
  const stage = job.stage || inferStage(job);
  const order = ["prepare", "discover", "select", "analyze", "summarize", "quality", "done"];
  const currentIndex = Math.max(order.indexOf(stage), 0);

  document.querySelectorAll(".flow-node").forEach((node) => {
    const index = order.indexOf(node.dataset.stage);
    node.classList.remove("active", "done", "failed");
    if (job.status === "failed" && index === currentIndex) {
      node.classList.add("failed");
    } else if (stage === "done" || index < currentIndex) {
      node.classList.add("done");
    } else if (index === currentIndex) {
      node.classList.add("active");
    }
  });
}

function inferStage(job) {
  if (job.status === "completed") return "done";
  const logs = (job.logs || []).join("\n");
  if (/总总结已保存|Markdown 已保存|最终报告通过质检|达到最大迭代次数/.test(logs)) return "done";
  if (/Quality Agent 质检|最终报告质检闭环|\[quality-loop\]/.test(logs)) return "quality";
  if (/生成所选产品大总结|FINAL COMPARISON|横向对比/.test(logs)) return "summarize";
  if (/等待所选产品分析报告完成|启动独立命令行窗口分析|将要分析的产品|分析窗口已经启动/.test(logs)) return "analyze";
  if (/请选择|\[web-input\] 产品选择/.test(logs)) return "select";
  if (/LLM 改写后的搜索词|搜索到的产品|rewrite search queries|find_product_names/.test(logs)) return "discover";
  return "prepare";
}

function stageLabel(value) {
  return {
    prepare: "准备输入",
    discover: "搜索发现",
    select: "等待/应用人工选择",
    analyze: "分块阅读与分析",
    summarize: "横向总结",
    quality: "质检闭环",
    done: "完成",
    running: "运行中",
    completed: "完成",
    failed: "失败",
  }[value] || value;
}

async function loadReports(options = {}) {
  const selected = reportSelect.value;
  try {
    const data = await api("/api/reports");
    allReportsCache = [...data.reports].sort(compareReports);
    reportSelect.innerHTML = "";

    if (!allReportsCache.length) {
      reportSelect.appendChild(new Option("暂无报告", ""));
      renderSummary(null);
      renderIssues([]);
      setDownload("");
      renderReportLibrary([]);
      allIssuesCache = [];
      issueGroupsCache = [];
      issuesLoaded = true;
      renderQualityIssueGroups([]);
      return;
    }

    renderReportLibrary(allReportsCache);
    for (const report of allReportsCache) {
      const label = `${reportTypeLabel(report)} · ${report.summary?.title || report.name}`;
      reportSelect.appendChild(new Option(label, report.name));
    }
    if (options.preserveSelection && selected) reportSelect.value = selected;
    if (!reportSelect.value && allReportsCache[0]) reportSelect.value = allReportsCache[0].name;
    if (options.loadSelected && reportSelect.value) await loadReport(reportSelect.value);
    issuesLoaded = false;
    allIssuesCache = [];
    issueGroupsCache = [];
    if (document.querySelector('[data-page-panel="quality"]')?.classList.contains("active")) {
      loadQualityIssues();
    } else if (qualityIssueList) {
      qualityIssueList.innerHTML = `<div class="issue-empty">进入本页后再加载 Issue 明细，避免工作台初始化卡顿。</div>`;
    }
  } catch (error) {
    showToast("加载报告列表失败: " + error.message, "error");
  }
}

function compareReports(a, b) {
  const order = { final: 0, report_agent: 1, single: 2, quality: 3 };
  const typeDelta = (order[reportType(a)] ?? 9) - (order[reportType(b)] ?? 9);
  if (typeDelta) return typeDelta;
  return (b.modified_at || 0) - (a.modified_at || 0);
}

function renderReportLibrary(reports) {
  if (!reportLibrary) return;
  if (!reports.length) {
    reportLibrary.innerHTML = `<div class="report-empty"><p>暂无报告</p><span>开始分析后会在这里展示。</span></div>`;
    return;
  }

  const groups = groupReportsByTask(reports);
  reportLibrary.innerHTML = groups
    .map((group) => {
      const tags = summarizeTaskTags(group.reports);
      const date = new Date(group.modifiedAt * 1000).toLocaleString("zh-CN");
      return `
        <section class="report-folder report-folder-card">
          <div class="report-folder-header">
            <div>
              <h3>${escapeHtml(group.taskId)}</h3>
              <time>${date}</time>
            </div>
            <span class="report-tag">${group.reports.length} 个文件</span>
          </div>
          <div class="report-meta">${tags.map((tag) => `<span class="report-tag">${escapeHtml(tag)}</span>`).join("")}</div>
          <div class="report-card-footer">
            <span class="report-tag">任务文件夹</span>
            <button class="btn btn-ghost btn-sm" data-task="${escapeHtml(group.taskId)}">打开文件夹</button>
          </div>
        </section>
      `;
    })
    .join("");

  reportLibrary.querySelectorAll("button[data-task]").forEach((button) => {
    button.addEventListener("click", () => {
      renderReportFolderFiles(button.dataset.task);
    });
  });
}

function renderReportFolderFiles(taskId) {
  const group = groupReportsByTask(allReportsCache).find((item) => item.taskId === taskId);
  if (!group || !reportLibrary) return;
  const reports = [...group.reports].sort(compareReports);
  reportLibrary.innerHTML = `
    <section class="report-file-page">
      <div class="report-file-page-header">
        <button class="btn btn-ghost btn-sm" data-back-folders type="button">返回文件夹</button>
        <div>
          <h3>${escapeHtml(group.taskId)}</h3>
          <p>${reports.length} 个报告文件，点击文件在右侧预览。</p>
        </div>
      </div>
      <div class="report-file-list">
        ${reports.map(renderReportRow).join("")}
      </div>
    </section>
  `;
  reportLibrary.querySelector("[data-back-folders]")?.addEventListener("click", () => {
    renderReportLibrary(allReportsCache);
  });
  reportLibrary.querySelectorAll("button[data-report]").forEach((button) => {
    button.addEventListener("click", () => openReportSidePanel(button.dataset.report));
  });
}

function renderReportRow(report) {
  const summary = report.summary || {};
  return `
    <div class="report-file-row">
      <div class="report-file-main">
        <span class="report-file-type">${escapeHtml(reportTypeLabel(report))}${summary.round ? " · " + escapeHtml(summary.round) : ""}</span>
        <strong>${escapeHtml(summary.title || report.name)}</strong>
        <small>${escapeHtml(report.name)}</small>
      </div>
      <div class="report-file-actions">
        <span class="report-tag">参考点 ${summary.reference_count || 0}</span>
        <span class="report-tag">Issue ${summary.issue_count || 0}</span>
        <button class="btn btn-ghost btn-sm" data-report="${escapeHtml(report.name)}">查看</button>
      </div>
    </div>
  `;
}

async function loadReport(name) {
  if (name === currentReportName && reportViewer.children.length > 0) return;
  currentReportName = name;
  showLoadingSkeleton();
  try {
    const data = await api(`/api/reports/${encodeURIComponent(name)}`);
    renderSummary(data.summary);
    renderIssues(data.summary?.issues || []);
    setDownload(data.name);
    reportViewer.innerHTML = markdownToHtml(data.content);
    reportViewer.style.opacity = "1";
    updateMetricsFromSummary(data.summary);
  } catch (error) {
    currentReportName = "";
    reportViewer.innerHTML = `<div class="empty-state error"><p>加载报告失败</p><span>${escapeHtml(error.message)}</span></div>`;
    showToast("加载报告失败: " + error.message, "error");
  }
}

async function openReportSidePanel(name, focus = {}) {
  if (!reportSidePanel || !sideReportViewer) return;
  reportSidePanel.classList.add("open");
  reportSidePanel.setAttribute("aria-hidden", "false");
  if (reportSideBackdrop) reportSideBackdrop.hidden = false;
  sideReportViewer.innerHTML = `
    <div class="skeleton-container">
      <div class="skeleton skeleton-title"></div>
      <div class="skeleton skeleton-text"></div>
      <div class="skeleton skeleton-text"></div>
      <div class="skeleton skeleton-text short"></div>
    </div>
  `;
  if (sideReportTitle) sideReportTitle.textContent = "加载中...";
  if (sideReportName) sideReportName.textContent = name;

  try {
    const data = await api(`/api/reports/${encodeURIComponent(name)}`);
    const summary = data.summary || {};
    if (sideReportType) sideReportType.textContent = reportTypeLabel({ summary });
    if (sideReportTitle) sideReportTitle.textContent = summary.title || data.name || name;
    if (sideReportName) sideReportName.textContent = data.name || name;
    if (sideReportSummary) sideReportSummary.innerHTML = renderSideSummaryHtml(data);
    if (sideDownloadBtn) {
      sideDownloadBtn.href = `/download/reports/${encodeURIComponent(data.name || name)}`;
      sideDownloadBtn.style.pointerEvents = "auto";
      sideDownloadBtn.style.opacity = "1";
    }
    sideReportViewer.innerHTML = markdownToHtml(data.content || "");
    focusReportPreview(data.content || "", focus);
  } catch (error) {
    sideReportViewer.innerHTML = `<div class="empty-state error"><p>加载报告失败</p><span>${escapeHtml(error.message)}</span></div>`;
    showToast("加载报告失败: " + error.message, "error");
  }
}

function focusReportPreview(content, focus = {}) {
  if (!sideReportViewer || (!focus.line && !focus.query)) return;
  const lines = content.split("\n");
  let targetLine = Number(focus.line || 0);
  if (!targetLine && focus.query) {
    const query = String(focus.query).slice(0, 80).trim();
    const found = lines.findIndex((line) => query && line.includes(query));
    if (found >= 0) targetLine = found + 1;
  }
  if (!targetLine) return;
  const start = Math.max(0, targetLine - 4);
  const end = Math.min(lines.length, targetLine + 3);
  const snippet = lines
    .slice(start, end)
    .map((line, index) => {
      const lineNumber = start + index + 1;
      const active = lineNumber === targetLine ? " active" : "";
      return `<div class="source-line${active}"><span>${lineNumber}</span><code>${escapeHtml(line || " ")}</code></div>`;
    })
    .join("");
  sideReportViewer.insertAdjacentHTML(
    "afterbegin",
    `<section class="source-focus-card">
      <strong>定位到 Issue 原文附近</strong>
      <div class="source-lines">${snippet}</div>
    </section>`
  );
  sideReportViewer.scrollTop = 0;
}

function closeReportSidePanel() {
  reportSidePanel?.classList.remove("open");
  reportSidePanel?.setAttribute("aria-hidden", "true");
  if (reportSideBackdrop) reportSideBackdrop.hidden = true;
}

function renderSideSummaryHtml(data) {
  const summary = data.summary || {};
  const values = [
    reportTypeLabel({ summary }),
    summary.task_id || inferTaskId(data.name),
    summary.reference_count || 0,
    summary.issue_count || 0,
  ];
  const labels = ["类型", "任务", "参考点", "Issue"];
  return values
    .map(
      (value, index) => `
        <div class="summary-item">
          <span>${labels[index]}</span>
          <strong>${escapeHtml(String(value))}</strong>
        </div>
      `
    )
    .join("");
}

function renderIssueField(label, value) {
  if (!value) return "";
  return `
    <p class="issue-field">
      <b>${escapeHtml(label)}：</b>${escapeHtml(value)}
    </p>
  `;
}

function findReportByName(name) {
  return allReportsCache.find((report) => report.name === name);
}

function showLoadingSkeleton() {
  reportViewer.style.opacity = "0.5";
  reportViewer.innerHTML = `
    <div class="skeleton-container">
      <div class="skeleton skeleton-title"></div>
      <div class="skeleton skeleton-text"></div>
      <div class="skeleton skeleton-text"></div>
      <div class="skeleton skeleton-text short"></div>
    </div>
  `;
}

function renderSummary(summary) {
  const values = summary
    ? [
        reportTypeLabel({ summary }),
        String(summary.reference_count || 0),
        String(summary.issue_count || 0),
        formatCharCount(summary.chars || 0),
      ]
    : ["暂无", "0", "0", "0"];
  resultSummary.querySelectorAll("strong").forEach((card, index) => {
    card.textContent = values[index];
  });
}

function renderIssues(issues) {
  if (!issuePanel) return;
  if (!issues.length) {
    issuePanel.innerHTML = `<div class="issue-empty">当前报告暂无结构化 Issue。可在质检报告或含“问题/风险/缺口”的章节中查看。</div>`;
    return;
  }
  issuePanel.innerHTML = `
    <div class="issue-panel-header">
      <strong>详细 Issue</strong>
      <span>来自分块阅读、报告正文或质检输出的结构化问题</span>
    </div>
    ${issues
      .map(
        (issue) => `
          <article class="issue-item ${escapeHtml(issue.severity || "medium")}">
            <span>${escapeHtml(issue.severity || "medium")}</span>
            <div class="issue-content">
              <strong>${escapeHtml(issue.title || "未命名 Issue")}</strong>
              ${renderIssueField("原因", issue.reason || issue.detail)}
              ${renderIssueField("证据", issue.evidence)}
              ${renderIssueField("建议", issue.suggestion)}
              ${renderIssueLocation({
                report: "当前报告",
                lineNumber: issue.line_number,
                section: issue.section,
              })}
              ${renderIssueContext({ context: issue.context })}
            </div>
          </article>
        `
      )
      .join("")}
  `;
}

function renderQualityIssues(issues) {
  if (!qualityIssueList) return;
  if (!issues.length) {
    qualityIssueList.innerHTML = `<div class="issue-empty">暂无 Issue。运行质检闭环后会展示每轮问题、影响范围和修复方向。</div>`;
    return;
  }
  const groups = groupIssuesByTask(issues);
  renderQualityIssueGroups(
    groups.map((group) => ({
      taskId: group.taskId,
      modifiedAt: group.modifiedAt,
      issueCount: group.issues.length,
      typeCounts: Object.fromEntries(issueFolderTags(group.issues).map((tag) => {
        const parts = tag.split(" ");
        return [parts.slice(0, -1).join(" "), Number(parts.at(-1) || 0)];
      })),
    }))
  );
}

function renderQualityIssueGroups(groups) {
  if (!qualityIssueList) return;
  if (!groups.length) {
    qualityIssueList.innerHTML = `<div class="issue-empty">暂无 Issue。运行质检闭环后会展示每轮问题、影响范围和修复方向。</div>`;
    return;
  }
  const totalIssues = groups.reduce((sum, group) => sum + Number(group.issueCount || 0), 0);
  qualityIssueList.innerHTML = `
    <div class="issue-library-summary">
      <strong>共 ${totalIssues} 个 Issue</strong>
      <span>先按任务归档；打开任务后再加载该任务的问题、来源章节、行号和原文片段。</span>
    </div>
    ${groups
    .map(
      (group) => `
        <section class="report-folder report-folder-card issue-folder-card">
          <div class="report-folder-header">
            <div>
              <h3>${escapeHtml(group.taskId)}</h3>
              <time>${new Date(group.modifiedAt * 1000).toLocaleString("zh-CN")}</time>
            </div>
            <span class="report-tag">${group.issueCount} 个 Issue</span>
          </div>
          <div class="report-meta">
            ${issueGroupTags(group).map((tag) => `<span class="report-tag">${escapeHtml(tag)}</span>`).join("")}
          </div>
          <div class="report-card-footer">
            <span class="report-tag">任务 Issue 文件夹</span>
            <button class="btn btn-ghost btn-sm" data-issue-task="${escapeHtml(group.taskId)}">打开 Issue</button>
          </div>
        </section>
      `
    )
    .join("")}
  `;
  qualityIssueList.querySelectorAll("button[data-issue-task]").forEach((button) => {
    button.addEventListener("click", () => renderIssueFolderFiles(button.dataset.issueTask));
  });
}

async function loadQualityIssues(force = false) {
  if (!qualityIssueList || issuesLoading) return;
  if (issuesLoaded && !force) {
    renderQualityIssueGroups(issueGroupsCache);
    return;
  }
  issuesLoading = true;
  qualityIssueList.innerHTML = `
    <div class="skeleton-container">
      <div class="skeleton skeleton-title"></div>
      <div class="skeleton skeleton-text"></div>
      <div class="skeleton skeleton-text short"></div>
    </div>
  `;
  try {
    const data = await api("/api/issues");
    issueGroupsCache = data.groups || [];
    allIssuesCache = [];
    issuesLoaded = true;
    renderQualityIssueGroups(issueGroupsCache);
  } catch (error) {
    qualityIssueList.innerHTML = `<div class="issue-empty">Issue 加载失败：${escapeHtml(error.message)}</div>`;
    showToast("加载 Issue 失败: " + error.message, "error");
  } finally {
    issuesLoading = false;
  }
}

async function renderIssueFolderFiles(taskId) {
  if (!qualityIssueList) return;
  qualityIssueList.innerHTML = `
    <div class="skeleton-container">
      <div class="skeleton skeleton-title"></div>
      <div class="skeleton skeleton-text"></div>
      <div class="skeleton skeleton-text short"></div>
    </div>
  `;
  let group;
  try {
    const data = await api(`/api/issues?task=${encodeURIComponent(taskId)}`);
    allIssuesCache = data.issues || [];
    group = groupIssuesByTask(allIssuesCache).find((item) => item.taskId === taskId);
  } catch (error) {
    qualityIssueList.innerHTML = `<div class="issue-empty">Issue 加载失败：${escapeHtml(error.message)}</div>`;
    showToast("加载任务 Issue 失败: " + error.message, "error");
    return;
  }
  if (!group) {
    qualityIssueList.innerHTML = `<div class="issue-empty">当前任务没有可展示的 Issue。</div>`;
    return;
  }
  qualityIssueList.innerHTML = `
    <section class="report-file-page">
      <div class="report-file-page-header">
        <button class="btn btn-ghost btn-sm" data-back-issue-folders type="button">返回文件夹</button>
        <div>
          <h3>${escapeHtml(group.taskId)}</h3>
          <p>${group.issues.length} 个 Issue，按来源报告展开；点击来源在右侧预览原文件。</p>
        </div>
      </div>
      <div class="issue-file-list">
        ${group.issues.map(renderIssueRow).join("")}
      </div>
    </section>
  `;
  qualityIssueList.querySelectorAll("button[data-report]").forEach((button) => {
    button.addEventListener("click", () => {
      const report = button.dataset.report;
      if (!findReportByName(report)) {
        showToast("找不到对应来源文件: " + report, "warning");
        return;
      }
      const line = Number(button.dataset.line || 0);
      const query = button.dataset.query || "";
      openReportSidePanel(report, { line, query });
    });
  });
  qualityIssueList.querySelector("[data-back-issue-folders]")?.addEventListener("click", () => {
    renderQualityIssueGroups(issueGroupsCache);
  });
}

function renderIssueRow(item) {
  return `
    <article class="issue-list-row">
      <div>
        <div class="issue-row-tags">
          <span class="report-tag">${escapeHtml(item.reportType)}</span>
          <span class="report-tag">${escapeHtml(item.reportTitle)}</span>
        </div>
        <strong>${escapeHtml(item.title)}</strong>
        ${renderIssueField("原因", item.reason || item.detail)}
        ${renderIssueField("证据", item.evidence)}
        ${renderIssueField("建议", item.suggestion)}
        ${renderIssueLocation(item)}
        ${renderIssueContext(item)}
      </div>
      <button class="btn btn-ghost btn-sm" data-report="${escapeHtml(item.report)}" data-line="${escapeHtml(item.lineNumber || "")}" data-query="${escapeHtml(item.title)}" ${item.sourceExists ? "" : "disabled"}>${item.sourceExists ? "定位原文" : "来源缺失"}</button>
    </article>
  `;
}

function renderIssueLocation(item) {
  const parts = [];
  if (item.section) parts.push(`章节：${item.section}`);
  if (item.lineNumber) parts.push(`行号：${item.lineNumber}`);
  parts.push(`来源文件：${item.report || "未匹配到文件"}`);
  return `<small class="issue-source">${escapeHtml(parts.join(" · "))}</small>`;
}

function renderIssueContext(item) {
  if (!item.context) return "";
  return `<pre class="issue-context">${escapeHtml(item.context)}</pre>`;
}

function collectIssues(reports) {
  const reportNames = new Set(reports.map((report) => report.name));
  return reports.flatMap((report) =>
    (report.summary?.issues || []).map((issue) => ({
      taskId: report.summary?.task_id || inferTaskId(report.name),
      report: report.name,
      reportTitle: report.summary?.title || report.name,
      reportType: reportTypeLabel(report),
      modifiedAt: report.modified_at || 0,
      sourceExists: reportNames.has(report.name),
      title: issue.title || report.summary?.title || report.name,
      detail: issue.detail || issue.title || "",
      reason: issue.reason || "",
      evidence: issue.evidence || "",
      suggestion: issue.suggestion || "",
      lineNumber: issue.line_number || 0,
      section: issue.section || "",
      context: issue.context || "",
    }))
  );
}

function updateBusinessMetrics(job) {
  if (!job) return;
  const elapsed = job.created_at ? Math.max(0, Math.round(Date.now() / 1000 - job.created_at)) : 0;
  if (job.status === "running") timeMetric.textContent = `${elapsed}s 运行中`;
  if (job.status === "completed") timeMetric.textContent = `${elapsed}s 完成`;
  if (job.status === "failed") timeMetric.textContent = "需人工介入";
}

function updateMetricsFromSummary(summary) {
  if (!summary) return;
  const references = summary.reference_count || 0;
  const sections = summary.sections || 0;
  const issues = summary.issue_count || 0;
  coverageMetric.textContent = `${references} 参考点 / ${sections} 章节`;
  consistencyMetric.textContent = issues ? `${issues} Issue 待看` : "结构通过";
  if (coverageHelp) {
    coverageHelp.textContent = `口径：后端从报告正文统计 [参考点N] 引用数和 Markdown 标题章节数；当前为 ${references} 个参考点、${sections} 个章节。`;
  }
  if (consistencyHelp) {
    consistencyHelp.textContent = `口径：后端从“Issue/问题/风险/缺口/待修复”等章节抽取结构化问题；当前为 ${issues} 个。`;
  }
}

function setQualityStatus(value) {
  if (qualityLoopStatus) qualityLoopStatus.textContent = value;
  if (qualityCenterStatus) qualityCenterStatus.textContent = value;
}

function updateQualityPreview() {
  qualityModePreview.textContent = qualityMode.value;
  maxIterationPreview.textContent = maxIterations.value || "3";
  setQualityStatus(enableQualityLoop.checked ? "已启用" : "已关闭");
}

function loadSettings() {
  const settings = JSON.parse(localStorage.getItem("competitor_ai_settings") || "{}");
  llmProvider.value = settings.llm_provider || "0";
  arkApiKey.value = settings.ark_api_key || "";
  bochaApiKey.value = settings.bocha_api_key || "";
  googleApiKey.value = settings.google_api_key || "";
  googleCxId.value = settings.google_cx_id || "";
  llmBaseUrl.value = settings.llm_base_url || "";
  llmModel.value = settings.llm_model || "";
  settingsTopN.value = settings.top_n || "5";
  settingsQualityMode.value = settings.quality_mode || "rule";
  settingsMaxIterations.value = settings.max_iterations || "3";
  settingsEnableQualityLoop.checked = settings.enable_quality_loop !== false;
  syncSettingsToWorkspace();
}

function saveSettings() {
  const settings = {
    llm_provider: llmProvider.value,
    ark_api_key: arkApiKey.value.trim(),
    bocha_api_key: bochaApiKey.value.trim(),
    google_api_key: googleApiKey.value.trim(),
    google_cx_id: googleCxId.value.trim(),
    llm_base_url: llmBaseUrl.value.trim(),
    llm_model: llmModel.value.trim(),
    top_n: settingsTopN.value,
    quality_mode: settingsQualityMode.value,
    max_iterations: settingsMaxIterations.value,
    enable_quality_loop: settingsEnableQualityLoop.checked,
  };
  localStorage.setItem("competitor_ai_settings", JSON.stringify(settings));
  syncSettingsToWorkspace();
  showToast("配置已保存", "success");
}

function syncSettingsToWorkspace() {
  topN.value = settingsTopN.value || "5";
  qualityMode.value = settingsQualityMode.value || "rule";
  maxIterations.value = settingsMaxIterations.value || "3";
  enableQualityLoop.checked = settingsEnableQualityLoop.checked;
  updateQualityPreview();
}

function setDownload(name) {
  if (!name) {
    downloadBtn.href = "#";
    downloadBtn.style.opacity = "0.4";
    downloadBtn.style.pointerEvents = "none";
    return;
  }
  downloadBtn.href = `/download/reports/${encodeURIComponent(name)}`;
  downloadBtn.style.opacity = "1";
  downloadBtn.style.pointerEvents = "auto";
}

function showPage(page) {
  navButtons.forEach((button) => button.classList.toggle("active", button.dataset.page === page));
  pagePanels.forEach((panel) => panel.classList.toggle("active", panel.dataset.pagePanel === page));
  if (page === "quality") loadQualityIssues();
}

function groupReportsByTask(reports) {
  const groups = new Map();
  for (const report of reports) {
    const taskId = report.summary?.task_id || inferTaskId(report.name);
    if (!groups.has(taskId)) groups.set(taskId, { taskId, modifiedAt: 0, reports: [] });
    const group = groups.get(taskId);
    group.reports.push(report);
    group.modifiedAt = Math.max(group.modifiedAt, report.modified_at || 0);
  }
  return [...groups.values()].sort((a, b) => b.modifiedAt - a.modifiedAt);
}

function groupIssuesByTask(issues) {
  const groups = new Map();
  for (const issue of issues) {
    const taskId = issue.taskId || inferTaskId(issue.report);
    if (!groups.has(taskId)) groups.set(taskId, { taskId, modifiedAt: 0, issues: [] });
    const group = groups.get(taskId);
    group.issues.push(issue);
    group.modifiedAt = Math.max(group.modifiedAt, issue.modifiedAt || 0);
  }
  return [...groups.values()].sort((a, b) => b.modifiedAt - a.modifiedAt);
}

function issueFolderTags(issues) {
  const counts = {};
  for (const issue of issues) {
    const label = issue.reportType || "Issue";
    counts[label] = (counts[label] || 0) + 1;
  }
  return Object.entries(counts).map(([label, count]) => `${label} ${count}`);
}

function issueGroupTags(group) {
  const counts = group.typeCounts || {};
  return Object.entries(counts).map(([label, count]) => `${label} ${count}`);
}

function reportType(report) {
  if (report.summary?.type) return report.summary.type;
  if (report.summary?.is_quality) return "quality";
  if (report.summary?.is_final) return "final";
  if (report.summary?.is_report_agent) return "report_agent";
  const name = String(report.name || "").toUpperCase();
  if (name.includes("QUALITY_WORKFLOW") || name.endsWith("QUALITY_REPORT.MD")) return "quality";
  if (name.includes("FINAL_COMPARISON")) return "final";
  if (name.includes("REPORT_AGENT_ANALYSIS")) return "report_agent";
  return "single";
}

function reportTypeLabel(report) {
  const type = reportType(report);
  if (type === "quality") return "质检报告";
  if (type === "final") return "最终报告";
  if (type === "report_agent") return "分析总报告";
  return "单品报告";
}

function summarizeTaskTags(reports) {
  const counts = {};
  for (const report of reports) {
    const label = reportTypeLabel(report);
    counts[label] = (counts[label] || 0) + 1;
  }
  return Object.entries(counts).map(([label, count]) => `${label} ${count}`);
}

function inferTaskId(name) {
  const match = String(name || "").match(/(\d{8}_\d{6})/);
  return match ? match[1] : "未分组";
}

function formatCharCount(chars) {
  if (chars > 10000) return `${(chars / 10000).toFixed(1)}万`;
  return String(chars);
}

function formatSize(value) {
  if (value > 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value > 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

function formatTimestamp(value) {
  if (!value) return "-";
  return new Date(value * 1000).toLocaleTimeString("zh-CN");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function markdownToHtml(markdown) {
  const lines = markdown.split("\n");
  const html = [];
  let inList = false;
  let inTable = false;
  let inCode = false;
  const codeLines = [];

  for (const line of lines) {
    if (line.startsWith("```")) {
      closeTable();
      closeList();
      if (inCode) {
        html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines.length = 0;
        inCode = false;
      } else {
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }
    if (isTableLine(line)) {
      closeList();
      if (/^\s*\|?\s*:?-{3,}:?\s*\|/.test(line)) continue;
      const cells = line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => escapeHtml(cell.trim()));
      if (!inTable) {
        html.push("<table><tbody>");
        inTable = true;
      }
      html.push(`<tr>${cells.map((cell) => `<td>${inlineMarkdown(cell)}</td>`).join("")}</tr>`);
    } else if (line.startsWith("# ")) {
      closeTable();
      closeList();
      html.push(`<h1>${inlineMarkdown(escapeHtml(line.slice(2)))}</h1>`);
    } else if (line.startsWith("## ")) {
      closeTable();
      closeList();
      html.push(`<h2>${inlineMarkdown(escapeHtml(line.slice(3)))}</h2>`);
    } else if (line.startsWith("### ")) {
      closeTable();
      closeList();
      html.push(`<h3>${inlineMarkdown(escapeHtml(line.slice(4)))}</h3>`);
    } else if (/^\s*[-*]\s+/.test(line)) {
      closeTable();
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${inlineMarkdown(escapeHtml(line.replace(/^\s*[-*]\s+/, "")))}</li>`);
    } else if (line.startsWith("> ")) {
      closeTable();
      closeList();
      html.push(`<blockquote>${inlineMarkdown(escapeHtml(line.slice(2)))}</blockquote>`);
    } else if (!line.trim()) {
      closeTable();
      closeList();
    } else {
      closeTable();
      closeList();
      html.push(`<p>${inlineMarkdown(escapeHtml(line))}</p>`);
    }
  }
  closeTable();
  closeList();
  return html.join("");

  function closeTable() {
    if (inTable) {
      html.push("</tbody></table>");
      inTable = false;
    }
  }
  function closeList() {
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
  }
}

function isTableLine(line) {
  return line.trim().startsWith("|") && line.includes("|");
}

function inlineMarkdown(value) {
  return value
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function readFileInto(input, textarea) {
  const file = input.files && input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    textarea.value = String(reader.result || "");
    showToast(`已加载文件 ${file.name}`, "success");
  };
  reader.onerror = () => showToast("文件读取失败", "error");
  reader.readAsText(file, "utf-8");
}

function showToast(message, type = "info") {
  const existing = document.querySelector(".toast");
  if (existing) existing.remove();
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3600);
}

reportViewer.style.transition = "opacity 0.3s ease-out";
