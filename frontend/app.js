let currentJobId = "";
let pollTimer = null;
let isSubmitting = false;
let lastReportName = "";
let currentReportName = "";
let allReportsCache = [];
let allIssuesCache = [];
let issueGroupsCache = [];
let skillWikisCache = [];
let currentSkillWikiId = "";
let currentSkillDocPath = "";
let skillBuildBusy = false;
let skillChatBusy = false;
let questionnaireFilesCache = [];
let questionnaireBusy = false;
let currentQuestionnaireFileName = "";
let issuesLoaded = false;
let issuesLoading = false;
let currentWizardStep = 1;
let selectionPanelJobId = "";
let selectionPanelCandidatesKey = "";

const MARKDOWN_TOC_WIDTH_KEY = "markdownTocWidth";
const MARKDOWN_TOC_DEFAULT_WIDTH = 240;
const MARKDOWN_TOC_MIN_WIDTH = 160;
const MARKDOWN_TOC_MAX_WIDTH = 420;
const MARKDOWN_TOC_MIN_CONTENT_WIDTH = 280;
const REPORT_SIDE_WIDTH_KEY = "reportSidePanelWidth";
const REPORT_SIDE_DEFAULT_WIDTH = 760;
const REPORT_SIDE_MIN_WIDTH = 520;
const REPORT_SIDE_MAX_WIDTH = 1500;
const REPORT_SIDE_MIN_REMAINING_WIDTH = 260;

const $ = (selector) => document.querySelector(selector);

function looksLikeSecret(value) {
  return /^(ark|sk)-[A-Za-z0-9_-]{16,}$/.test(String(value || "").trim());
}

const productDescription = $("#productDescription");
const llmProvider = $("#llmProvider");
const topN = $("#topN");
const queryCount = $("#queryCount");
const searchCount = $("#searchCount");
const searchBackend = $("#searchBackend");
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
const settingsMaxIterations = $("#settingsMaxIterations");
const settingsEnableQualityLoop = $("#settingsEnableQualityLoop");
const saveSettingsBtn = $("#saveSettingsBtn");
const knownParamFile = $("#knownParamFile");
const knownParamText = $("#knownParamText");
const questionnaireFile = $("#questionnaireFile");
const questionnaireText = $("#questionnaireText");
const startBtn = $("#startBtn");
const refreshBtn = $("#refreshBtn");
const terminateBtn = $("#terminateBtn");
const serverStatus = $("#serverStatus");
const jobMeta = $("#jobMeta");
const jobStatus = $("#jobStatus");
const reportName = $("#reportName");
const logBox = $("#logBox");
const openAgentLogBtn = $("#openAgentLogBtn");
const closeAgentLogBtn = $("#closeAgentLogBtn");
const agentLogModal = $("#agentLogModal");
const agentLogBackdrop = $("#agentLogBackdrop");
const agentLogMeta = $("#agentLogMeta");
const agentLogInlineMeta = $("#agentLogInlineMeta");
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
const reloadQuestionnairesBtn = $("#reloadQuestionnairesBtn");
const questionnaireTabs = Array.from(document.querySelectorAll("[data-questionnaire-tab]"));
const questionnairePanels = Array.from(document.querySelectorAll("[data-questionnaire-panel]"));
const questionnaireProductFile = $("#questionnaireProductFile");
const questionnaireProductDescription = $("#questionnaireProductDescription");
const questionnaireQuestionCount = $("#questionnaireQuestionCount");
const questionnaireSearchSource = $("#questionnaireSearchSource");
const questionnaireCompetitorNames = $("#questionnaireCompetitorNames");
const questionnaireOwnParamText = $("#questionnaireOwnParamText");
const questionnaireSkipSearch = $("#questionnaireSkipSearch");
const generateQuestionnaireBtn = $("#generateQuestionnaireBtn");
const questionnaireGenerateStatus = $("#questionnaireGenerateStatus");
const analysisQuestionnaireSelect = $("#analysisQuestionnaireSelect");
const analysisResponsesSelect = $("#analysisResponsesSelect");
const analysisProductDescription = $("#analysisProductDescription");
const analyzeQuestionnaireBtn = $("#analyzeQuestionnaireBtn");
const questionnaireAnalysisStatus = $("#questionnaireAnalysisStatus");
const simulateQuestionnaireSelect = $("#simulateQuestionnaireSelect");
const simulateResponseCount = $("#simulateResponseCount");
const simulateProductDescription = $("#simulateProductDescription");
const simulateCompetitorNames = $("#simulateCompetitorNames");
const simulateOwnParamText = $("#simulateOwnParamText");
const simulateQuestionnaireBtn = $("#simulateQuestionnaireBtn");
const questionnaireSimulateStatus = $("#questionnaireSimulateStatus");
const questionnaireFileList = $("#questionnaireFileList");
const questionnaireResultMeta = $("#questionnaireResultMeta");
const questionnaireResultPreview = $("#questionnaireResultPreview");
const reportSidePanel = $("#reportSidePanel");
const reportSideBackdrop = $("#reportSideBackdrop");
const closeSideReportBtn = $("#closeSideReportBtn");
const sideReportType = $("#sideReportType");
const sideReportTitle = $("#sideReportTitle");
const sideReportName = $("#sideReportName");
const sideReportSummary = $("#sideReportSummary");
const sideReportViewer = $("#sideReportViewer");
const sideDownloadBtn = $("#sideDownloadBtn");
const evidenceDrawer = $("#evidenceDrawer");
const closeEvidenceDrawerBtn = $("#closeEvidenceDrawerBtn");
const evidenceDrawerBadge = $("#evidenceDrawerBadge");
const evidenceDrawerTitle = $("#evidenceDrawerTitle");
const evidenceDrawerSource = $("#evidenceDrawerSource");
const evidenceDrawerActions = $("#evidenceDrawerActions");
const evidenceDrawerContent = $("#evidenceDrawerContent");
const sourceReportDrawer = $("#sourceReportDrawer");
const closeSourceReportDrawerBtn = $("#closeSourceReportDrawerBtn");
const sourceReportDrawerTitle = $("#sourceReportDrawerTitle");
const sourceReportDrawerPath = $("#sourceReportDrawerPath");
const sourceReportDrawerMeta = $("#sourceReportDrawerMeta");
const sourceReportDrawerContent = $("#sourceReportDrawerContent");
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
const skillReportSelect = $("#skillReportSelect");
const skillNameInput = $("#skillNameInput");
const skillDomainInput = $("#skillDomainInput");
const buildSkillBtn = $("#buildSkillBtn");
const reloadSkillsBtn = $("#reloadSkillsBtn");
const skillBuildStatus = $("#skillBuildStatus");
const skillWikiList = $("#skillWikiList");
const skillActiveMeta = $("#skillActiveMeta");
const skillDocPreview = $("#skillDocPreview");
const skillChatMessages = $("#skillChatMessages");
const skillChatInput = $("#skillChatInput");
const skillChatSendBtn = $("#skillChatSendBtn");
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
terminateBtn?.addEventListener("click", terminateCurrentJob);
openAgentLogBtn?.addEventListener("click", openAgentLogModal);
closeAgentLogBtn?.addEventListener("click", closeAgentLogModal);
agentLogBackdrop?.addEventListener("click", closeAgentLogModal);
document.addEventListener("click", handleEvidenceLinkClick);
document.addEventListener("click", handleLocalReportLinkClick);
document.addEventListener("click", handleMarkdownTocClick);
document.addEventListener("pointerdown", handleMarkdownTocResizeStart);
document.addEventListener("pointerdown", handleReportSideResizeStart);
window.addEventListener("resize", syncDrawerStackPositions);
reloadReportsBtn?.addEventListener("click", () => loadReports({ preserveSelection: true }));
reloadQuestionnairesBtn?.addEventListener("click", () => loadQuestionnaires({ forcePreview: false }));
reloadSkillsBtn?.addEventListener("click", () => refreshSkillPage({ force: true }));
buildSkillBtn?.addEventListener("click", buildSkillWiki);
generateQuestionnaireBtn?.addEventListener("click", generateQuestionnaire);
simulateQuestionnaireBtn?.addEventListener("click", simulateQuestionnaire);
analyzeQuestionnaireBtn?.addEventListener("click", analyzeQuestionnaire);
simulateQuestionnaireSelect?.addEventListener("change", () => fillQuestionnaireTheme(simulateQuestionnaireSelect, simulateProductDescription));
analysisQuestionnaireSelect?.addEventListener("change", () => fillQuestionnaireTheme(analysisQuestionnaireSelect, analysisProductDescription));
questionnaireTabs.forEach((button) => {
  button.addEventListener("click", () => showQuestionnaireTab(button.dataset.questionnaireTab));
});
questionnaireProductFile?.addEventListener("change", () => readFileInto(questionnaireProductFile, questionnaireProductDescription));
skillReportSelect?.addEventListener("change", () => updateSkillNameDefault(true));
skillNameInput?.addEventListener("input", () => {
  skillNameInput.dataset.auto = skillNameInput.value.trim() ? "0" : "1";
});
skillChatSendBtn?.addEventListener("click", sendSkillChatMessage);
skillChatInput?.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    sendSkillChatMessage();
  }
});
closeSideReportBtn?.addEventListener("click", closeReportSidePanel);
closeEvidenceDrawerBtn?.addEventListener("click", closeEvidenceDrawer);
closeSourceReportDrawerBtn?.addEventListener("click", closeSourceReportDrawer);
reportSideBackdrop?.addEventListener("click", closeReportSidePanel);
submitProductSelectionBtn?.addEventListener("click", submitProductSelection);
reportSelect.addEventListener("change", () => {
  if (reportSelect.value) loadReport(reportSelect.value);
});
knownParamFile.addEventListener("change", () => readFileInto(knownParamFile, knownParamText));
questionnaireFile.addEventListener("change", () => readFileInto(questionnaireFile, questionnaireText));
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
    if (event.key === "Escape" && agentLogModal?.classList.contains("open")) {
      event.preventDefault();
      closeAgentLogModal();
      return;
    }
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
    top_n: Number(topN.value || 3),
    query_count: Number(queryCount.value || 3),
    search_count: Number(searchCount.value || 3),
    search_backend: Number(searchBackend.value || 2),
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
    updateTerminateButton(null);
    updateAgentLogMeta(null);
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

    if (isJobActive(job)) {
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
    } else if (job.status === "terminated") {
      showToast("工作流已终止", "warning");
    }
  } catch (error) {
    clearTimeout(pollTimer);
    setStartButtonLoading(false);
    showToast("获取任务状态失败: " + error.message, "error");
  }
}

function isJobActive(job) {
  return job && ["queued", "running", "terminating"].includes(job.status);
}

async function terminateCurrentJob() {
  if (!currentJobId || !terminateBtn) return;
  if (!window.confirm("确定要终止当前工作流吗？")) return;
  terminateBtn.disabled = true;
  terminateBtn.textContent = "终止中";
  try {
    const job = await api(`/api/jobs/${currentJobId}/terminate`, {
      method: "POST",
      body: "{}",
    });
    renderJob(job);
    showToast("已发送终止信号", "warning");
    clearTimeout(pollTimer);
    pollTimer = setTimeout(pollJob, 1000);
  } catch (error) {
    showToast("终止失败: " + error.message, "error");
    if (currentJobId) {
      try {
        renderJob(await api(`/api/jobs/${currentJobId}`));
      } catch {
        updateTerminateButton(null);
      }
    }
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
  updateTerminateButton(job);
  updateAgentLogMeta(job);
  renderRuntimeState(job);
  renderSubtasks(job);
  maybeOpenProductSelection(job);
  renderNodeFlow(job);
  const statusStage = ["terminating", "terminated", "failed", "completed"].includes(job.status)
    ? job.status
    : job.stage || job.status;
  setQualityStatus(stageLabel(statusStage));
  updateBusinessMetrics(job);
}

function updateTerminateButton(job) {
  if (!terminateBtn) return;
  const active = isJobActive(job);
  terminateBtn.disabled = !active || job?.status === "terminating";
  terminateBtn.textContent = job?.status === "terminating" ? "终止中" : "终止";
}

function updateAgentLogMeta(job) {
  if (!agentLogMeta && !agentLogInlineMeta) return;
  const lineCount = (job?.logs || []).length;
  const statusText = job ? stageLabel(job.status) : "尚未启动";
  const pidText = job?.process_pid ? `PID ${job.process_pid}` : "PID -";
  const meta = job
    ? `${statusText} · ${pidText} · ${lineCount} 行日志`
    : "等待任务日志...";
  if (agentLogMeta) agentLogMeta.textContent = meta;
  if (agentLogInlineMeta) agentLogInlineMeta.textContent = meta;
}

function openAgentLogModal() {
  if (!agentLogModal) return;
  agentLogModal.classList.add("open");
  agentLogModal.setAttribute("aria-hidden", "false");
  if (agentLogBackdrop) agentLogBackdrop.hidden = false;
  logBox?.scrollTo({ top: logBox.scrollHeight });
}

function closeAgentLogModal() {
  agentLogModal?.classList.remove("open");
  agentLogModal?.setAttribute("aria-hidden", "true");
  if (agentLogBackdrop) agentLogBackdrop.hidden = true;
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
    terminated: "已终止",
  }[status] || status || "排队";
}

function renderNodeFlow(job) {
  const stage = job.stage || inferStage(job);
  const order = ["prepare", "discover", "select", "analyze", "summarize", "quality", "done"];
  const currentIndex = Math.max(order.indexOf(stage), 0);

  document.querySelectorAll(".flow-node").forEach((node) => {
    const index = order.indexOf(node.dataset.stage);
    node.classList.remove("active", "done", "failed", "terminated");
    if (job.status === "failed" && index === currentIndex) {
      node.classList.add("failed");
    } else if (job.status === "terminated" && index === currentIndex) {
      node.classList.add("terminated");
    } else if (stage === "done" || index < currentIndex) {
      node.classList.add("done");
    } else if (index === currentIndex) {
      node.classList.add("active");
    }
  });
}

function inferStage(job) {
  if (job.status === "completed") return "done";
  if (job.status === "terminated") return job.stage || "prepare";
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
    queued: "排队中",
    terminating: "终止中",
    terminated: "已终止",
    completed: "完成",
    failed: "失败",
  }[value] || value;
}

async function loadReports(options = {}) {
  const selected = reportSelect.value;
  try {
    const data = await api("/api/reports");
    allReportsCache = [...data.reports].sort(compareReports);
    renderSkillReportOptions();
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
              <h3 title="${escapeHtml(group.displayTitle)}">${escapeHtml(group.displayTitle)}</h3>
              <time>${escapeHtml(group.taskId)} · ${date}</time>
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
          <h3 title="${escapeHtml(group.displayTitle)}">${escapeHtml(group.displayTitle)}</h3>
          <p>${escapeHtml(group.taskId)} · ${reports.length} 个报告文件，点击文件在右侧预览。</p>
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

async function loadQuestionnaires(options = {}) {
  if (!questionnaireFileList) return;
  try {
    const data = await api("/api/questionnaires");
    questionnaireFilesCache = data.files || [];
    renderQuestionnaireFileOptions();
    renderQuestionnaireFileList();
    if (options.previewName) {
      await previewQuestionnaireFile(options.previewName);
    } else if (options.forcePreview && questionnaireFilesCache[0]) {
      await previewQuestionnaireFile(questionnaireFilesCache[0].name);
    }
  } catch (error) {
    questionnaireFileList.innerHTML = `<div class="issue-empty">问卷文件加载失败：${escapeHtml(error.message)}</div>`;
    showToast("问卷文件加载失败: " + error.message, "error");
  }
}

function renderQuestionnaireFileOptions() {
  const questionnaires = questionnaireFilesByKind("questionnaire");
  const responses = questionnaireFilesByKind("response_jsonl");
  fillQuestionnaireSelect(simulateQuestionnaireSelect, questionnaires, "暂无问卷文件");
  fillQuestionnaireSelect(analysisQuestionnaireSelect, questionnaires, "暂无问卷文件");
  fillQuestionnaireSelect(analysisResponsesSelect, responses, "暂无回答 JSONL");
}

function fillQuestionnaireSelect(select, files, emptyLabel) {
  if (!select) return;
  const previous = select.value;
  select.innerHTML = "";
  if (!files.length) {
    select.appendChild(new Option(emptyLabel, ""));
    return;
  }
  for (const file of files) {
    const count = file.record_count ? ` · ${file.record_count} 条` : "";
    select.appendChild(new Option(`${file.kind_label} · ${file.title}${count}`, file.name));
  }
  if (previous && files.some((file) => file.name === previous)) {
    select.value = previous;
  }
}

function renderQuestionnaireFileList() {
  if (!questionnaireFileList) return;
  if (!questionnaireFilesCache.length) {
    questionnaireFileList.innerHTML = `<div class="issue-empty">暂无本地问卷文件。</div>`;
    renderQuestionnairePreview(null);
    return;
  }
  questionnaireFileList.innerHTML = questionnaireFilesCache
    .map((file) => {
      const active = file.name === currentQuestionnaireFileName ? "active" : "";
      return `
        <button class="questionnaire-file-row ${active}" data-questionnaire-file="${escapeHtml(file.name)}" type="button">
          <span>${escapeHtml(file.kind_label)}</span>
          <strong>${escapeHtml(file.title || file.name)}</strong>
          <small>${escapeHtml(file.name)} · ${formatSize(file.size || 0)}${file.record_count ? " · " + file.record_count + " 条" : ""}</small>
        </button>
      `;
    })
    .join("");
  questionnaireFileList.querySelectorAll("[data-questionnaire-file]").forEach((button) => {
    button.addEventListener("click", () => previewQuestionnaireFile(button.dataset.questionnaireFile));
  });
}

function questionnaireFilesByKind(kind) {
  return questionnaireFilesCache
    .filter((file) => file.kind === kind)
    .sort((a, b) => (b.modified_at || 0) - (a.modified_at || 0));
}

async function generateQuestionnaire() {
  if (questionnaireBusy) return;
  const description = questionnaireProductDescription?.value.trim() || "";
  if (!description) {
    questionnaireProductDescription?.focus();
    showToast("请输入产品/竞品方向", "error");
    return;
  }
  setQuestionnaireBusy(true, generateQuestionnaireBtn, "生成中...");
  if (questionnaireGenerateStatus) questionnaireGenerateStatus.textContent = "生成中：搜索竞品并设计问卷";
  try {
    const data = await api("/api/questionnaires/generate", {
      method: "POST",
      body: JSON.stringify({
        product_description: description,
        own_param_text: questionnaireOwnParamText?.value || "",
        competitor_names: questionnaireCompetitorNames?.value || "",
        question_count: Number(questionnaireQuestionCount?.value || 20),
        questionnaire_search_source: questionnaireSearchSource?.value || "bocha",
        skip_search: Boolean(questionnaireSkipSearch?.checked),
        ...questionnaireSharedPayload(),
      }),
    });
    questionnaireFilesCache = data.files || questionnaireFilesCache;
    renderQuestionnaireFileOptions();
    renderQuestionnaireFileList();
    if (questionnaireGenerateStatus) {
      const competitors = (data.competitors || []).slice(0, 8).join("、") || "未抽取到明确竞品";
      questionnaireGenerateStatus.textContent = `已生成 ${data.items?.length || 0} 题：${data.questionnaire?.name || ""}；竞品：${competitors}`;
    }
    showToast("问卷已生成", "success");
    await previewQuestionnaireFile(data.questionnaire?.name);
  } catch (error) {
    if (questionnaireGenerateStatus) questionnaireGenerateStatus.textContent = `生成失败：${error.message}`;
    showToast("问卷生成失败: " + error.message, "error");
  } finally {
    setQuestionnaireBusy(false, generateQuestionnaireBtn, "生成问卷");
  }
}

async function simulateQuestionnaire() {
  if (questionnaireBusy) return;
  const questionnaireName = simulateQuestionnaireSelect?.value || "";
  if (!questionnaireName) {
    showToast("请选择问卷文件", "error");
    return;
  }
  setQuestionnaireBusy(true, simulateQuestionnaireBtn, "生成中...");
  if (questionnaireSimulateStatus) questionnaireSimulateStatus.textContent = "生成中：AI 模拟填写仅作为快速测试使用";
  try {
    const data = await api("/api/questionnaires/simulate", {
      method: "POST",
      body: JSON.stringify({
        questionnaire_name: questionnaireName,
        product_description: simulateProductDescription?.value.trim() || "",
        own_param_text: simulateOwnParamText?.value || "",
        competitor_names: simulateCompetitorNames?.value || "",
        simulated_count: Number(simulateResponseCount?.value || 25),
        ...questionnaireSharedPayload(),
      }),
    });
    questionnaireFilesCache = data.files || questionnaireFilesCache;
    renderQuestionnaireFileOptions();
    renderQuestionnaireFileList();
    if (questionnaireSimulateStatus) {
      questionnaireSimulateStatus.textContent = `已生成 ${data.response_count || 0} 份：${data.response_jsonl?.name || ""}；CSV：${data.response_csv?.name || ""}`;
    }
    showToast("模拟回答已生成", "success");
    await previewQuestionnaireFile(data.response_jsonl?.name);
  } catch (error) {
    if (questionnaireSimulateStatus) questionnaireSimulateStatus.textContent = `模拟失败：${error.message}`;
    showToast("模拟填写失败: " + error.message, "error");
  } finally {
    setQuestionnaireBusy(false, simulateQuestionnaireBtn, "生成模拟回答");
  }
}

async function analyzeQuestionnaire() {
  if (questionnaireBusy) return;
  const questionnaireName = analysisQuestionnaireSelect?.value || "";
  const responsesName = analysisResponsesSelect?.value || "";
  if (!questionnaireName || !responsesName) {
    showToast("请选择问卷文件和回答 JSONL", "error");
    return;
  }
  setQuestionnaireBusy(true, analyzeQuestionnaireBtn, "分析中...");
  if (questionnaireAnalysisStatus) questionnaireAnalysisStatus.textContent = "分析中：统计回答并生成 Markdown 报告";
  try {
    const data = await api("/api/questionnaires/analyze", {
      method: "POST",
      body: JSON.stringify({
        questionnaire_name: questionnaireName,
        responses_name: responsesName,
        product_description: analysisProductDescription?.value.trim() || "",
        ...questionnaireSharedPayload(),
      }),
    });
    questionnaireFilesCache = data.files || questionnaireFilesCache;
    renderQuestionnaireFileOptions();
    renderQuestionnaireFileList();
    if (questionnaireAnalysisStatus) {
      questionnaireAnalysisStatus.textContent = `已生成分析报告：${data.analysis?.name || ""}`;
    }
    showToast("问卷分析已生成", "success");
    await previewQuestionnaireFile(data.analysis?.name, data.analysis_markdown || "");
  } catch (error) {
    if (questionnaireAnalysisStatus) questionnaireAnalysisStatus.textContent = `分析失败：${error.message}`;
    showToast("问卷分析失败: " + error.message, "error");
  } finally {
    setQuestionnaireBusy(false, analyzeQuestionnaireBtn, "分析问卷");
  }
}

async function previewQuestionnaireFile(name, suppliedMarkdown = "") {
  if (!name) return;
  currentQuestionnaireFileName = name;
  renderQuestionnaireFileList();
  const file = questionnaireFilesCache.find((item) => item.name === name);
  if (!file) return;
  renderQuestionnairePreview({ loading: true, file });
  try {
    const data = suppliedMarkdown
      ? { file, content: suppliedMarkdown }
      : await api(`/api/questionnaires/file/${encodeURIComponent(name)}`);
    renderQuestionnairePreview({ file: data.file || file, content: data.content || "" });
  } catch (error) {
    renderQuestionnairePreview({ file, content: `预览失败：${error.message}`, error: true });
  }
}

function renderQuestionnairePreview(state) {
  if (!questionnaireResultMeta || !questionnaireResultPreview) return;
  if (!state) {
    questionnaireResultMeta.innerHTML = `<strong>未选择文件</strong><span>生成、模拟或分析后会在这里预览。</span>`;
    questionnaireResultPreview.innerHTML = `<div class="empty-state"><p>暂无预览</p><span>请选择一个本地问卷文件。</span></div>`;
    return;
  }
  const file = state.file || {};
  questionnaireResultMeta.innerHTML = `
    <strong>${escapeHtml(file.title || file.name || "问卷文件")}</strong>
    <span>${escapeHtml(file.kind_label || "")} · ${escapeHtml(file.name || "")} · ${formatSize(file.size || 0)}</span>
  `;
  if (state.loading) {
    questionnaireResultPreview.innerHTML = `<div class="skeleton-container"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text short"></div></div>`;
    return;
  }
  const content = state.content || "";
  if (file.kind === "analysis") {
    questionnaireResultPreview.innerHTML = renderMarkdownPreview(content, { headingPrefix: "questionnaire-preview" });
  } else if (file.kind === "questionnaire" || file.kind === "response_jsonl") {
    questionnaireResultPreview.innerHTML = renderJsonlPreview(content);
  } else if (file.kind === "response_csv") {
    questionnaireResultPreview.innerHTML = renderPlainPreview(content);
  } else {
    questionnaireResultPreview.innerHTML = state.error ? `<p class="error">${escapeHtml(content)}</p>` : renderPlainPreview(content);
  }
}

function renderJsonlPreview(content) {
  const rows = content
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 30)
    .map((line) => {
      try {
        return JSON.stringify(JSON.parse(line), null, 2);
      } catch {
        return line;
      }
    });
  if (!rows.length) return `<div class="issue-empty">文件为空。</div>`;
  return `<pre><code>${escapeHtml(rows.join("\n\n"))}</code></pre>`;
}

function renderPlainPreview(content) {
  const preview = String(content || "").slice(0, 20000);
  return preview ? `<pre><code>${escapeHtml(preview)}</code></pre>` : `<div class="issue-empty">文件为空。</div>`;
}

function showQuestionnaireTab(tab) {
  questionnaireTabs.forEach((button) => button.classList.toggle("active", button.dataset.questionnaireTab === tab));
  questionnairePanels.forEach((panel) => panel.classList.toggle("active", panel.dataset.questionnairePanel === tab));
}

function fillQuestionnaireTheme(select, input) {
  if (!select || !input || input.value.trim()) return;
  const file = questionnaireFilesCache.find((item) => item.name === select.value);
  if (file?.title) input.value = file.title;
}

function setQuestionnaireBusy(value, button, label) {
  questionnaireBusy = value;
  if (button) {
    button.disabled = value;
    button.textContent = value ? label : label;
  }
}

function questionnaireSharedPayload() {
  return {
    llm_provider: llmProvider?.value || "0",
    ark_api_key: arkApiKey?.value.trim() || "",
    bocha_api_key: bochaApiKey?.value.trim() || "",
    google_api_key: googleApiKey?.value.trim() || "",
    google_cx_id: googleCxId?.value.trim() || "",
    llm_base_url: llmBaseUrl?.value.trim() || "",
    llm_model: llmModel?.value.trim() || "",
    query_count: Number(queryCount?.value || 3),
    search_count: Number(searchCount?.value || 3),
    top_n: Number(topN?.value || 3),
  };
}

function renderSkillReportOptions() {
  if (!skillReportSelect) return;
  const selected = skillReportSelect.value;
  const skillReportGroups = skillBuildReportGroups();
  skillReportSelect.innerHTML = "";
  if (!skillReportGroups.length) {
    skillReportSelect.appendChild(new Option("暂无可生成 Skill 的报告（需最终报告+分析总报告）", ""));
    updateSkillNameDefault(true);
    return;
  }
  for (const group of skillReportGroups) {
    const label = `报告包 · ${group.displayTitle}（最终报告+分析总报告）`;
    const option = new Option(label, group.agentReport.name);
    option.dataset.taskId = group.taskId;
    skillReportSelect.appendChild(option);
  }
  if (selected) {
    const selectedGroup = findSkillReportGroupBySelection(selected);
    if (selectedGroup) skillReportSelect.value = selectedGroup.agentReport.name;
  }
  if (!skillReportSelect.value && skillReportGroups[0]) {
    skillReportSelect.value = skillReportGroups[0].agentReport.name;
  }
  updateSkillNameDefault(false);
}

function updateSkillNameDefault(force = false) {
  if (!skillReportSelect || !skillNameInput) return;
  const group = findSkillReportGroupBySelection(skillReportSelect.value);
  const title = group?.displayTitle || "";
  const suggestion = title ? `${title} Skill` : "";
  if (force || !skillNameInput.value.trim() || skillNameInput.dataset.auto !== "0") {
    skillNameInput.value = suggestion;
    skillNameInput.dataset.auto = suggestion ? "1" : "0";
  }
}

function skillBuildReportGroups() {
  return groupReportsByTask(allReportsCache)
    .map((group) => ({
      ...group,
      finalReport: group.reports.find((report) => reportType(report) === "final"),
      agentReport: group.reports.find((report) => reportType(report) === "report_agent"),
    }))
    .filter((group) => group.finalReport && group.agentReport);
}

function findSkillReportGroupBySelection(value) {
  return skillBuildReportGroups().find(
    (group) => group.taskId === value || group.agentReport?.name === value
  );
}

async function refreshSkillPage(options = {}) {
  if (!skillReportSelect?.options.length) {
    await loadReports({ preserveSelection: true });
  } else {
    renderSkillReportOptions();
  }
  await loadSkillWikis(options.selectId || currentSkillWikiId || "", options);
}

async function loadSkillWikis(preferredId = "", options = {}) {
  if (!skillWikiList) return;
  try {
    const data = await api("/api/skill-wikis");
    skillWikisCache = data.skills || [];
    renderSkillWikiList();
    const nextId =
      preferredId ||
      (currentSkillWikiId && skillWikisCache.some((skill) => skill.id === currentSkillWikiId) ? currentSkillWikiId : "") ||
      skillWikisCache[0]?.id ||
      "";
    if (nextId && (options.force || nextId !== currentSkillWikiId || !skillDocPreview?.children.length)) {
      await selectSkillWiki(nextId);
    } else if (!nextId) {
      currentSkillWikiId = "";
      renderSkillDetail(null);
    }
  } catch (error) {
    skillWikiList.innerHTML = `<div class="issue-empty">Skill 加载失败：${escapeHtml(error.message)}</div>`;
    showToast("Skill 加载失败: " + error.message, "error");
  }
}

function renderSkillWikiList() {
  if (!skillWikiList) return;
  if (!skillWikisCache.length) {
    skillWikiList.innerHTML = `<div class="issue-empty">暂无本地 Skill。</div>`;
    return;
  }
  skillWikiList.innerHTML = skillWikisCache
    .map(
      (skill) => `
        <button class="skill-wiki-row ${skill.id === currentSkillWikiId ? "active" : ""}" data-skill-id="${escapeHtml(skill.id)}" type="button">
          <span>${escapeHtml(skill.name || skill.id)}</span>
          <strong>${escapeHtml(skill.source_report || skill.relative_path || "")}</strong>
          <small>${skill.file_count || 0} 个文件 · ${new Date((skill.modified_at || 0) * 1000).toLocaleString("zh-CN")}</small>
        </button>
      `
    )
    .join("");
  skillWikiList.querySelectorAll("[data-skill-id]").forEach((button) => {
    button.addEventListener("click", () => selectSkillWiki(button.dataset.skillId));
  });
}

async function buildSkillWiki() {
  if (skillBuildBusy) return;
  const reportName = skillReportSelect?.value || "";
  const group = findSkillReportGroupBySelection(reportName);
  const taskId = group?.taskId || skillReportSelect?.selectedOptions?.[0]?.dataset?.taskId || inferTaskId(reportName);
  if (!reportName || !taskId) {
    showToast("请选择本地报告", "error");
    return;
  }
  skillBuildBusy = true;
  setSkillBuildLoading(true);
  if (skillBuildStatus) skillBuildStatus.textContent = "生成中";
  try {
    const payload = {
      task_id: taskId,
      report_name: group?.agentReport?.name || reportName,
      skill_name: skillNameInput?.value.trim() || "",
      domain: skillDomainInput?.value.trim() || "",
      ...skillLLMPayload(),
    };
    const data = await api("/api/skill-wikis/build", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const skill = data.skill;
    if (skillBuildStatus) {
      skillBuildStatus.textContent = `已保存：${skill?.relative_path || skill?.id || ""}`;
    }
    showToast("Skill 已生成", "success");
    currentSkillWikiId = skill?.id || "";
    await loadSkillWikis(currentSkillWikiId, { force: true });
  } catch (error) {
    if (skillBuildStatus) skillBuildStatus.textContent = `生成失败：${error.message}`;
    showToast("Skill 生成失败: " + error.message, "error");
  } finally {
    skillBuildBusy = false;
    setSkillBuildLoading(false);
  }
}

function setSkillBuildLoading(value) {
  if (!buildSkillBtn) return;
  buildSkillBtn.disabled = value;
  buildSkillBtn.textContent = value ? "生成中..." : "生成并保存";
}

async function selectSkillWiki(skillId) {
  if (!skillId) return;
  if (skillId !== currentSkillWikiId) currentSkillDocPath = "";
  currentSkillWikiId = skillId;
  renderSkillWikiList();
  renderSkillDetail({ loading: true, id: skillId });
  try {
    const data = await api(`/api/skill-wikis/${encodeURIComponent(skillId)}`);
    const skill = data.skill;
    const index = skillWikisCache.findIndex((item) => item.id === skill.id);
    if (index >= 0) skillWikisCache[index] = { ...skillWikisCache[index], ...skill };
    renderSkillDetail(skill);
  } catch (error) {
    renderSkillDetail(null);
    showToast("Skill 详情加载失败: " + error.message, "error");
  }
}

function renderSkillDetail(skill) {
  if (!skillActiveMeta || !skillDocPreview) return;
  if (!skill) {
    skillActiveMeta.innerHTML = `<strong>未选择 Skill</strong><span>请选择一个本地 skill</span>`;
    skillDocPreview.innerHTML = `<div class="issue-empty">暂无文档预览。</div>`;
    return;
  }
  if (skill.loading) {
    skillActiveMeta.innerHTML = `<strong>加载中</strong><span>${escapeHtml(skill.id || "")}</span>`;
    skillDocPreview.innerHTML = `<div class="skeleton-container"><div class="skeleton skeleton-title"></div><div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text short"></div></div>`;
    return;
  }
  skillActiveMeta.innerHTML = `
    <strong>${escapeHtml(skill.name || skill.id)}</strong>
    <span>${escapeHtml(skill.relative_path || "")}${skill.source_report ? " · " + escapeHtml(skill.source_report) : ""}</span>
  `;
  const docs = skill.docs || [];
  if (!docs.length) {
    skillDocPreview.innerHTML = `<div class="issue-empty">暂无可读文档。</div>`;
    return;
  }
  const preferred =
    docs.find((doc) => doc.path.toLowerCase().endsWith("source_report_tables.md")) ||
    docs.find((doc) => doc.path.toLowerCase() === "skill.md") ||
    docs[0];
  if (!currentSkillDocPath || !docs.some((doc) => doc.path === currentSkillDocPath)) {
    currentSkillDocPath = preferred.path;
  }
  const activeDoc = docs.find((doc) => doc.path === currentSkillDocPath) || preferred;
  skillDocPreview.innerHTML = `
    <div class="skill-doc-tabs">
      ${docs.map((doc) => `
        <button class="report-tag skill-doc-tab ${doc.path === activeDoc.path ? "active" : ""}" data-skill-doc-path="${escapeHtml(doc.path)}" type="button">
          ${escapeHtml(doc.path)}
        </button>
      `).join("")}
    </div>
    <div class="skill-doc-content">
      <div class="report-file-type">${escapeHtml(activeDoc.path)} · ${formatCharCount(activeDoc.chars || 0)} 字符</div>
      ${markdownToHtml(activeDoc.content || "")}
    </div>
  `;
  skillDocPreview.querySelectorAll("[data-skill-doc-path]").forEach((button) => {
    button.addEventListener("click", () => {
      currentSkillDocPath = button.dataset.skillDocPath || "";
      renderSkillDetail(skill);
    });
  });
}

async function sendSkillChatMessage() {
  if (skillChatBusy) return;
  const question = skillChatInput?.value.trim() || "";
  if (!currentSkillWikiId) {
    showToast("请选择本地 Skill", "error");
    return;
  }
  if (!question) {
    skillChatInput?.focus();
    return;
  }
  skillChatBusy = true;
  appendSkillChatMessage("user", question);
  skillChatInput.value = "";
  const loadingNode = appendSkillChatMessage("assistant", "思考中...");
  if (skillChatSendBtn) {
    skillChatSendBtn.disabled = true;
    skillChatSendBtn.textContent = "发送中";
  }
  try {
    const data = await api("/api/skill-wikis/chat", {
      method: "POST",
      body: JSON.stringify({
        skill_id: currentSkillWikiId,
        question,
        domain_hints: skillDomainInput?.value.trim() || "",
        ...skillLLMPayload(),
      }),
    });
    loadingNode.innerHTML = `<div class="skill-chat-role">回答</div><div class="skill-chat-text">${markdownToHtml(data.answer || "")}</div>`;
  } catch (error) {
    loadingNode.innerHTML = `<div class="skill-chat-role">回答</div><div class="skill-chat-text error">问答失败：${escapeHtml(error.message)}</div>`;
    showToast("Skill 问答失败: " + error.message, "error");
  } finally {
    skillChatBusy = false;
    if (skillChatSendBtn) {
      skillChatSendBtn.disabled = false;
      skillChatSendBtn.textContent = "发送";
    }
    scrollSkillChatToBottom();
  }
}

function appendSkillChatMessage(role, text) {
  if (!skillChatMessages) return null;
  const empty = skillChatMessages.querySelector(".skill-chat-empty");
  if (empty) empty.remove();
  const node = document.createElement("article");
  node.className = `skill-chat-message ${role}`;
  const label = role === "user" ? "问题" : "回答";
  const body = role === "assistant" ? markdownToHtml(text) : `<p>${escapeHtml(text)}</p>`;
  node.innerHTML = `<div class="skill-chat-role">${label}</div><div class="skill-chat-text">${body}</div>`;
  skillChatMessages.appendChild(node);
  scrollSkillChatToBottom();
  return node;
}

function scrollSkillChatToBottom() {
  if (skillChatMessages) skillChatMessages.scrollTop = skillChatMessages.scrollHeight;
}

function skillLLMPayload() {
  return {
    llm_provider: llmProvider?.value || "0",
    ark_api_key: arkApiKey?.value.trim() || "",
    llm_base_url: llmBaseUrl?.value.trim() || "",
    llm_model: llmModel?.value.trim() || "",
  };
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
    reportViewer.dataset.reportName = data.name || name;
    reportViewer.innerHTML = renderMarkdownPreview(data.content, { headingPrefix: "report-preview" });
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
  applyReportSidePanelWidth();
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
    sideReportViewer.dataset.reportName = data.name || name;
    sideReportViewer.innerHTML = renderMarkdownPreview(data.content || "", { headingPrefix: "side-report-preview" });
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
  closeEvidenceDrawer();
}

async function handleEvidenceLinkClick(event) {
  if (!(event.target instanceof Element)) return;
  const link = event.target.closest("[data-evidence-id]");
  if (!link) return;
  event.preventDefault();
  event.stopPropagation();
  const evidenceId = String(link.dataset.evidenceId || "").trim();
  if (!evidenceId) return;
  const preview = link.closest(".report-preview");
  const reportName =
    link.dataset.reportName ||
    preview?.dataset.reportName ||
    currentReportName ||
    sideReportName?.textContent ||
    "";
  await openEvidenceDrawer({
    evidenceId,
    reportName,
    href: link.dataset.evidenceHref || link.getAttribute("href") || "",
  });
}

async function openEvidenceDrawer({ evidenceId, reportName, href = "" }) {
  if (!evidenceDrawer || !evidenceDrawerContent) return;
  const normalizedEvidenceId = String(evidenceId || "").trim();
  const evidenceReportName = evidenceCardsReportNameFrom(reportName, href);
  positionEvidenceDrawer();
  evidenceDrawer.classList.add("open");
  evidenceDrawer.setAttribute("aria-hidden", "false");
  if (evidenceDrawerBadge) evidenceDrawerBadge.textContent = "证据卡";
  if (evidenceDrawerTitle) evidenceDrawerTitle.textContent = normalizedEvidenceId;
  if (evidenceDrawerSource) evidenceDrawerSource.textContent = evidenceReportName || "未找到证据卡文件";
  if (evidenceDrawerActions) evidenceDrawerActions.innerHTML = "";
  evidenceDrawerContent.innerHTML = `
    <div class="skeleton-container">
      <div class="skeleton skeleton-title"></div>
      <div class="skeleton skeleton-text"></div>
      <div class="skeleton skeleton-text"></div>
      <div class="skeleton skeleton-text short"></div>
    </div>
  `;

  if (!evidenceReportName) {
    evidenceDrawerContent.innerHTML = `<div class="empty-state error"><p>未找到证据卡文件</p><span>${escapeHtml(reportName || "")}</span></div>`;
    return;
  }

  try {
    const data = await api(`/api/reports/${encodeURIComponent(evidenceReportName)}`);
    const cardMarkdown = extractEvidenceCardMarkdown(data.content || "", normalizedEvidenceId);
    if (evidenceDrawerSource) evidenceDrawerSource.textContent = data.name || evidenceReportName;
    evidenceDrawerContent.dataset.reportName = data.name || evidenceReportName;
    if (!cardMarkdown) {
      evidenceDrawerContent.innerHTML = `<div class="empty-state error"><p>未找到 ${escapeHtml(normalizedEvidenceId)}</p><span>${escapeHtml(data.name || evidenceReportName)}</span></div>`;
      return;
    }
    evidenceDrawerActions.innerHTML = renderEvidenceDrawerActions(cardMarkdown, data.name || evidenceReportName);
    evidenceDrawerContent.innerHTML = renderMarkdownPreview(cardMarkdown, {
      headingPrefix: `evidence-card-${normalizedEvidenceId}`,
    });
    evidenceDrawerContent.scrollTop = 0;
  } catch (error) {
    evidenceDrawerContent.innerHTML = `<div class="empty-state error"><p>证据卡加载失败</p><span>${escapeHtml(error.message)}</span></div>`;
    showToast("证据卡加载失败: " + error.message, "error");
  }
}

function closeEvidenceDrawer() {
  evidenceDrawer?.classList.remove("open");
  evidenceDrawer?.setAttribute("aria-hidden", "true");
  closeSourceReportDrawer();
}

function positionEvidenceDrawer() {
  if (!evidenceDrawer) return;
  const reportOpen = reportSidePanel?.classList.contains("open");
  const reportWidth = reportOpen ? currentReportSidePanelWidth() : 0;
  const drawerWidth = currentEvidenceDrawerWidth();
  const maxRight = Math.max(0, window.innerWidth - drawerWidth - 12);
  const right = Math.min(reportWidth, maxRight);
  evidenceDrawer.style.setProperty("--evidence-drawer-right", `${Math.round(right)}px`);
}

function evidenceCardsReportNameFrom(reportName, href = "") {
  const baseName = String(reportName || "").replace(/\\/g, "/").trim();
  const hrefText = String(href || "").replace(/\\/g, "/").trim();
  const hrefPath = hrefText.split("#")[0].split("?")[0].replace(/^\.\//, "");
  if (hrefPath && !/^[a-z]+:/i.test(hrefPath) && hrefPath.toLowerCase().endsWith(".md")) {
    if (hrefPath.includes("/")) return stripReportsPrefix(hrefPath);
    const dir = baseName.includes("/") ? baseName.split("/").slice(0, -1).join("/") : "";
    return stripReportsPrefix(dir ? `${dir}/${hrefPath}` : hrefPath);
  }
  if (/REPORT_AGENT_ANALYSIS\.md$/i.test(baseName)) {
    return baseName.replace(/REPORT_AGENT_ANALYSIS\.md$/i, "REPORT_AGENT_EVIDENCE_CARDS.md");
  }
  const taskId = inferTaskId(baseName);
  const match = allReportsCache.find((report) => {
    const name = String(report.name || "");
    return inferTaskId(name) === taskId && /REPORT_AGENT_EVIDENCE_CARDS\.md$/i.test(name);
  });
  return match?.name || "";
}

function stripReportsPrefix(value) {
  return String(value || "").replace(/^\/+/, "").replace(/^reports\//i, "");
}

function extractEvidenceCardMarkdown(content, evidenceId) {
  const lines = String(content || "").split("\n");
  const escapedId = escapeRegExp(String(evidenceId || "").trim());
  if (!escapedId) return "";
  let start = lines.findIndex((line) => new RegExp(`^#{3,6}\\s+${escapedId}\\b`, "i").test(line.trim()));
  if (start < 0) {
    const anchor = evidenceId.toLowerCase();
    start = lines.findIndex((line) => line.toLowerCase().includes(`id="${anchor}"`));
  }
  if (start < 0) return "";
  let end = lines.length;
  for (let index = start + 1; index < lines.length; index += 1) {
    const line = lines[index].trim();
    if (/^##\s+/.test(line) || /^###\s+ev_\d{3,}\b/i.test(line) || /^<a\s+id=["']ev_\d{3,}["']><\/a>$/i.test(line)) {
      end = index;
      break;
    }
  }
  return lines.slice(start, end).join("\n").trim();
}

function renderEvidenceDrawerActions(cardMarkdown, evidenceReportName) {
  const url = firstUrlFromText(cardMarkdown);
  const parts = [];
  if (url) {
    parts.push(`<a class="btn btn-primary btn-sm" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">打开原始链接</a>`);
  }
  if (evidenceReportName) {
    parts.push(`<a class="btn btn-ghost btn-sm" href="/download/reports/${encodeURIComponent(evidenceReportName)}" download>下载证据卡</a>`);
  }
  return parts.join("");
}

function firstUrlFromText(value) {
  const match = String(value || "").match(/https?:\/\/[^\s<>)\]]+/i);
  return match ? match[0].replace(/[，。；、)）\]]+$/g, "") : "";
}

async function handleLocalReportLinkClick(event) {
  if (!(event.target instanceof Element)) return;
  const link = event.target.closest("[data-local-report-path]");
  if (!link) return;
  event.preventDefault();
  event.stopPropagation();
  await openSourceReportDrawer(link.dataset.localReportPath || link.getAttribute("href") || "");
}

async function openSourceReportDrawer(rawPath) {
  if (!sourceReportDrawer || !sourceReportDrawerContent) return;
  const reportName = normalizeLocalReportName(rawPath);
  positionSourceReportDrawer();
  sourceReportDrawer.classList.add("open");
  sourceReportDrawer.setAttribute("aria-hidden", "false");
  if (sourceReportDrawerTitle) sourceReportDrawerTitle.textContent = "加载中...";
  if (sourceReportDrawerPath) sourceReportDrawerPath.textContent = reportName || rawPath || "未识别来源路径";
  if (sourceReportDrawerMeta) sourceReportDrawerMeta.innerHTML = "";
  sourceReportDrawerContent.innerHTML = `
    <div class="skeleton-container">
      <div class="skeleton skeleton-title"></div>
      <div class="skeleton skeleton-text"></div>
      <div class="skeleton skeleton-text"></div>
      <div class="skeleton skeleton-text short"></div>
    </div>
  `;

  if (!reportName) {
    sourceReportDrawerContent.innerHTML = `<div class="empty-state error"><p>无法识别来源报告</p><span>${escapeHtml(rawPath || "")}</span></div>`;
    return;
  }

  try {
    const data = await api(`/api/reports/${encodeURIComponent(reportName)}`);
    const summary = data.summary || {};
    if (sourceReportDrawerTitle) sourceReportDrawerTitle.textContent = summary.title || data.name || reportName;
    if (sourceReportDrawerPath) sourceReportDrawerPath.textContent = data.name || reportName;
    if (sourceReportDrawerMeta) sourceReportDrawerMeta.innerHTML = renderSideSummaryHtml(data);
    sourceReportDrawerContent.dataset.reportName = data.name || reportName;
    sourceReportDrawerContent.innerHTML = renderMarkdownPreview(data.content || "", {
      headingPrefix: "source-report-preview",
    });
    sourceReportDrawerContent.scrollTop = 0;
  } catch (error) {
    sourceReportDrawerContent.innerHTML = `<div class="empty-state error"><p>来源报告加载失败</p><span>${escapeHtml(error.message)}</span></div>`;
    showToast("来源报告加载失败: " + error.message, "error");
  }
}

function closeSourceReportDrawer() {
  sourceReportDrawer?.classList.remove("open");
  sourceReportDrawer?.setAttribute("aria-hidden", "true");
}

function positionSourceReportDrawer() {
  if (!sourceReportDrawer) return;
  const reportOpen = reportSidePanel?.classList.contains("open");
  const reportWidth = reportOpen ? currentReportSidePanelWidth() : 0;
  const evidenceOpen = evidenceDrawer?.classList.contains("open");
  const evidenceWidth = evidenceOpen ? currentEvidenceDrawerWidth() : 0;
  const drawerWidth = currentSourceReportDrawerWidth();
  const maxRight = Math.max(0, window.innerWidth - drawerWidth - 12);
  const right = Math.min(reportWidth + evidenceWidth, maxRight);
  sourceReportDrawer.style.setProperty("--source-report-drawer-right", `${Math.round(right)}px`);
}

function normalizeLocalReportName(rawPath) {
  let value = String(rawPath || "").trim();
  if (!value) return "";
  value = value.replace(/^file:\/+/i, "");
  value = value.replace(/\\/g, "/");
  value = decodeHtmlEntities(value);
  value = value.replace(/^\/+/, "");
  const reportsIndex = value.toLowerCase().lastIndexOf("/reports/");
  if (reportsIndex >= 0) value = value.slice(reportsIndex + "/reports/".length);
  value = value.replace(/^reports\//i, "");
  const mdIndex = value.toLowerCase().indexOf(".md");
  if (mdIndex >= 0) value = value.slice(0, mdIndex + 3);
  if (!value.toLowerCase().endsWith(".md")) return "";
  return value;
}

function decodeHtmlEntities(value) {
  const textarea = document.createElement("textarea");
  textarea.innerHTML = String(value || "");
  return textarea.value;
}

function escapeRegExp(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function handleReportSideResizeStart(event) {
  if (!reportSidePanel || !reportSidePanel.classList.contains("open")) return;
  if (!(event.target instanceof Element)) return;
  if (event.target.closest("[data-markdown-toc-resizer]")) return;
  const resizeTarget = drawerStackResizeTarget(event);
  if (!resizeTarget) return;

  event.preventDefault();
  const startX = event.clientX;
  const startWidth = currentReportSidePanelWidth();
  let latestWidth = startWidth;
  reportSidePanel.classList.add("is-resizing");
  evidenceDrawer?.classList.toggle("is-resizing", evidenceDrawer.classList.contains("open"));
  sourceReportDrawer?.classList.toggle("is-resizing", sourceReportDrawer.classList.contains("open"));
  document.body.classList.add("is-resizing-report-side");

  const onPointerMove = (moveEvent) => {
    latestWidth = clampReportSidePanelWidth(startWidth - (moveEvent.clientX - startX));
    reportSidePanel.style.setProperty("--report-side-width", `${latestWidth}px`);
    syncDrawerStackPositions();
  };
  const finishResize = () => {
    document.removeEventListener("pointermove", onPointerMove);
    document.removeEventListener("pointerup", finishResize);
    document.removeEventListener("pointercancel", finishResize);
    reportSidePanel.classList.remove("is-resizing");
    evidenceDrawer?.classList.remove("is-resizing");
    sourceReportDrawer?.classList.remove("is-resizing");
    document.body.classList.remove("is-resizing-report-side");
    syncDrawerStackPositions();
    try {
      localStorage.setItem(REPORT_SIDE_WIDTH_KEY, String(latestWidth));
    } catch {
      // Ignore storage failures; resizing still works for the current panel.
    }
  };

  document.addEventListener("pointermove", onPointerMove);
  document.addEventListener("pointerup", finishResize);
  document.addEventListener("pointercancel", finishResize);
}

function drawerStackResizeTarget(event) {
  const edgeHitWidth = 14;
  const candidates = [sourceReportDrawer, evidenceDrawer, reportSidePanel];
  return candidates.find((drawer) => {
    if (!drawer || !drawer.classList.contains("open")) return false;
    const rect = drawer.getBoundingClientRect();
    return event.clientX >= rect.left - 6 && event.clientX <= rect.left + edgeHitWidth;
  });
}

function syncDrawerStackPositions() {
  if (evidenceDrawer?.classList.contains("open")) positionEvidenceDrawer();
  if (sourceReportDrawer?.classList.contains("open")) positionSourceReportDrawer();
}

function applyReportSidePanelWidth() {
  if (!reportSidePanel) return;
  reportSidePanel.style.setProperty("--report-side-width", `${getReportSidePanelWidth()}px`);
  syncDrawerStackPositions();
}

function getReportSidePanelWidth() {
  try {
    const stored = Number(localStorage.getItem(REPORT_SIDE_WIDTH_KEY));
    if (Number.isFinite(stored)) return clampReportSidePanelWidth(stored);
  } catch {
    // Ignore storage failures; fall back to the default panel width.
  }
  return clampReportSidePanelWidth(REPORT_SIDE_DEFAULT_WIDTH);
}

function currentReportSidePanelWidth() {
  if (!reportSidePanel) return getReportSidePanelWidth();
  const value = Number.parseFloat(getComputedStyle(reportSidePanel).getPropertyValue("--report-side-width"));
  if (Number.isFinite(value)) return clampReportSidePanelWidth(value);
  return clampReportSidePanelWidth(reportSidePanel.getBoundingClientRect().width || REPORT_SIDE_DEFAULT_WIDTH);
}

function currentEvidenceDrawerWidth() {
  return currentDrawerWidth(evidenceDrawer, 440);
}

function currentSourceReportDrawerWidth() {
  return currentDrawerWidth(sourceReportDrawer, 620);
}

function currentDrawerWidth(drawer, fallbackWidth) {
  const rectWidth = drawer?.getBoundingClientRect().width || 0;
  if (rectWidth > 0) return Math.round(rectWidth);
  return Math.min(fallbackWidth, Math.max(0, window.innerWidth - 24));
}

function clampReportSidePanelWidth(value) {
  const numeric = Number(value);
  const fallback = REPORT_SIDE_DEFAULT_WIDTH;
  const viewportMax = Math.max(320, window.innerWidth - REPORT_SIDE_MIN_REMAINING_WIDTH);
  const minWidth = Math.min(REPORT_SIDE_MIN_WIDTH, Math.max(320, window.innerWidth - 24));
  const maxWidth = Math.max(minWidth, Math.min(REPORT_SIDE_MAX_WIDTH, viewportMax, window.innerWidth - 24));
  return Math.round(Math.min(Math.max(Number.isFinite(numeric) ? numeric : fallback, minWidth), maxWidth));
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
      displayTitle: issueGroupDisplayTitle(group),
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
              <h3 title="${escapeHtml(issueGroupDisplayTitle(group))}">${escapeHtml(issueGroupDisplayTitle(group))}</h3>
              <time>${escapeHtml(group.taskId)} · ${new Date(group.modifiedAt * 1000).toLocaleString("zh-CN")}</time>
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
          <h3 title="${escapeHtml(issueGroupDisplayTitle(group))}">${escapeHtml(issueGroupDisplayTitle(group))}</h3>
          <p>${escapeHtml(group.taskId)} · ${group.issues.length} 个 Issue，按来源报告展开；点击来源在右侧预览原文件。</p>
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
  if (job.status === "queued") timeMetric.textContent = `${elapsed}s 排队中`;
  if (job.status === "running") timeMetric.textContent = `${elapsed}s 运行中`;
  if (job.status === "terminating") timeMetric.textContent = `${elapsed}s 终止中`;
  if (job.status === "completed") timeMetric.textContent = `${elapsed}s 完成`;
  if (job.status === "terminated") timeMetric.textContent = `${elapsed}s 已终止`;
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
  qualityModePreview.textContent = "交付验收";
  maxIterationPreview.textContent = maxIterations.value || "3";
  setQualityStatus(enableQualityLoop.checked ? "已启用" : "已关闭");
}

function loadSettings() {
  const settings = JSON.parse(localStorage.getItem("competitor_ai_settings") || "{}");
  if (looksLikeSecret(settings.llm_model) || settings.llm_model === settings.ark_api_key) {
    delete settings.llm_model;
    localStorage.setItem("competitor_ai_settings", JSON.stringify(settings));
  }
  llmProvider.value = settings.llm_provider || "0";
  arkApiKey.value = settings.ark_api_key || "";
  bochaApiKey.value = settings.bocha_api_key || "";
  googleApiKey.value = settings.google_api_key || "";
  googleCxId.value = settings.google_cx_id || "";
  llmBaseUrl.value = settings.llm_base_url || "";
  llmModel.value = settings.llm_model || "";
  settingsTopN.value = settings.top_n || "3";
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
    max_iterations: settingsMaxIterations.value,
    enable_quality_loop: settingsEnableQualityLoop.checked,
  };
  localStorage.setItem("competitor_ai_settings", JSON.stringify(settings));
  syncSettingsToWorkspace();
  showToast("配置已保存", "success");
}

function syncSettingsToWorkspace() {
  topN.value = settingsTopN.value || "3";
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
  if (page === "skills") refreshSkillPage();
  if (page === "questionnaires") loadQuestionnaires({ forcePreview: !currentQuestionnaireFileName });
}

function groupReportsByTask(reports) {
  const groups = new Map();
  for (const report of reports) {
    const taskId = report.summary?.task_id || inferTaskId(report.name);
    if (!groups.has(taskId)) groups.set(taskId, { taskId, displayTitle: taskId, modifiedAt: 0, reports: [] });
    const group = groups.get(taskId);
    group.reports.push(report);
    group.modifiedAt = Math.max(group.modifiedAt, report.modified_at || 0);
  }
  for (const group of groups.values()) {
    group.displayTitle = reportGroupDisplayTitle(group);
  }
  return [...groups.values()].sort((a, b) => b.modifiedAt - a.modifiedAt);
}

function reportGroupDisplayTitle(group) {
  const reports = [...(group.reports || [])].sort(compareReports);
  const preferred =
    reports.find((report) => reportType(report) === "final" && report.summary?.title) ||
    reports.find((report) => reportType(report) === "report_agent" && report.summary?.title) ||
    reports.find((report) => report.summary?.title);
  return preferred?.summary?.title || group.taskId;
}

function groupIssuesByTask(issues) {
  const groups = new Map();
  for (const issue of issues) {
    const taskId = issue.taskId || inferTaskId(issue.report);
    if (!groups.has(taskId)) groups.set(taskId, { taskId, displayTitle: "", modifiedAt: 0, issues: [] });
    const group = groups.get(taskId);
    group.issues.push(issue);
    group.modifiedAt = Math.max(group.modifiedAt, issue.modifiedAt || 0);
  }
  for (const group of groups.values()) {
    group.displayTitle = issueGroupDisplayTitle(group);
  }
  return [...groups.values()].sort((a, b) => b.modifiedAt - a.modifiedAt);
}

function issueGroupDisplayTitle(group) {
  if (group?.displayTitle) return group.displayTitle;
  const taskId = group?.taskId || "";
  const reportGroup = groupReportsByTask(allReportsCache).find((item) => item.taskId === taskId);
  if (reportGroup?.displayTitle) return reportGroup.displayTitle;
  const issues = group?.issues || [];
  const preferred =
    issues.find((issue) => issue.reportType === "最终报告" && issue.reportTitle) ||
    issues.find((issue) => issue.reportType === "分析总报告" && issue.reportTitle) ||
    issues.find((issue) => issue.reportTitle);
  return preferred?.reportTitle || taskId;
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

function renderMarkdownPreview(markdown, options = {}) {
  const rendered = renderMarkdownDocument(markdown, {
    headingPrefix: options.headingPrefix || "markdown-preview",
  });
  const hasToc = rendered.headings.length >= 2;
  const tocStyle = hasToc ? ` style="--markdown-toc-width: ${getMarkdownTocWidth()}px"` : "";
  const empty = rendered.html.trim()
    ? ""
    : `<div class="issue-empty">No preview content.</div>`;
  return `
    <div class="markdown-preview-layout${hasToc ? "" : " no-toc"}"${tocStyle}>
      <article class="markdown-preview-content">${rendered.html || empty}</article>
      ${hasToc ? `<div class="markdown-preview-resizer" data-markdown-toc-resizer title="Resize outline" aria-hidden="true"></div>` : ""}
      ${renderMarkdownToc(rendered.headings)}
    </div>
  `;
}

function renderMarkdownToc(headings) {
  if (headings.length < 2) return "";
  return `
    <nav class="markdown-preview-toc" aria-label="Document outline">
      <div class="markdown-preview-toc-title">目录</div>
      <div class="markdown-preview-toc-list">
        ${headings
          .map(
            (heading) => `
              <a class="markdown-preview-toc-item level-${heading.level}" href="#${heading.id}" data-markdown-toc-target="${heading.id}">
                ${escapeHtml(heading.text)}
              </a>
            `
          )
          .join("")}
      </div>
    </nav>
  `;
}

function handleMarkdownTocClick(event) {
  if (!(event.target instanceof Element)) return;
  const link = event.target.closest("[data-markdown-toc-target]");
  if (!link) return;
  const preview = link.closest(".report-preview");
  if (!preview) return;
  const target = preview.querySelector(`[id="${link.dataset.markdownTocTarget}"]`);
  if (!target) return;
  event.preventDefault();
  preview.querySelectorAll(".markdown-preview-toc-item.active").forEach((item) => item.classList.remove("active"));
  link.classList.add("active");
  const previewRect = preview.getBoundingClientRect();
  const targetRect = target.getBoundingClientRect();
  preview.scrollTo({
    top: preview.scrollTop + targetRect.top - previewRect.top - 14,
    behavior: "smooth",
  });
}

function handleMarkdownTocResizeStart(event) {
  if (!(event.target instanceof Element)) return;
  const handle = event.target.closest("[data-markdown-toc-resizer]");
  if (!handle) return;
  const layout = handle.closest(".markdown-preview-layout");
  if (!layout || layout.classList.contains("no-toc")) return;
  event.preventDefault();
  const startX = event.clientX;
  const startWidth = currentMarkdownTocWidth(layout);
  let latestWidth = startWidth;
  layout.classList.add("is-resizing");
  document.body.classList.add("is-resizing-markdown-toc");
  handle.setPointerCapture?.(event.pointerId);

  const onPointerMove = (moveEvent) => {
    latestWidth = clampMarkdownTocWidth(startWidth - (moveEvent.clientX - startX), layout);
    layout.style.setProperty("--markdown-toc-width", `${latestWidth}px`);
  };
  const finishResize = () => {
    document.removeEventListener("pointermove", onPointerMove);
    document.removeEventListener("pointerup", finishResize);
    document.removeEventListener("pointercancel", finishResize);
    layout.classList.remove("is-resizing");
    document.body.classList.remove("is-resizing-markdown-toc");
    try {
      localStorage.setItem(MARKDOWN_TOC_WIDTH_KEY, String(latestWidth));
    } catch {
      // Ignore storage failures; resizing still works for the current render.
    }
  };

  document.addEventListener("pointermove", onPointerMove);
  document.addEventListener("pointerup", finishResize);
  document.addEventListener("pointercancel", finishResize);
}

function getMarkdownTocWidth() {
  try {
    const stored = Number(localStorage.getItem(MARKDOWN_TOC_WIDTH_KEY));
    if (Number.isFinite(stored)) return clampMarkdownTocWidth(stored);
  } catch {
    // Ignore storage failures; fall back to the default outline width.
  }
  return MARKDOWN_TOC_DEFAULT_WIDTH;
}

function currentMarkdownTocWidth(layout) {
  const value = Number.parseFloat(getComputedStyle(layout).getPropertyValue("--markdown-toc-width"));
  if (Number.isFinite(value)) return clampMarkdownTocWidth(value, layout);
  const toc = layout.querySelector(".markdown-preview-toc");
  return clampMarkdownTocWidth(toc?.getBoundingClientRect().width || MARKDOWN_TOC_DEFAULT_WIDTH, layout);
}

function clampMarkdownTocWidth(value, layout = null) {
  const numeric = Number(value);
  const fallback = MARKDOWN_TOC_DEFAULT_WIDTH;
  let maxWidth = MARKDOWN_TOC_MAX_WIDTH;
  if (layout) {
    const available = layout.clientWidth - MARKDOWN_TOC_MIN_CONTENT_WIDTH - 26;
    if (Number.isFinite(available)) {
      maxWidth = Math.min(maxWidth, Math.max(MARKDOWN_TOC_MIN_WIDTH, available));
    }
  }
  return Math.round(Math.min(Math.max(Number.isFinite(numeric) ? numeric : fallback, MARKDOWN_TOC_MIN_WIDTH), maxWidth));
}

function markdownToHtml(markdown) {
  return renderMarkdownDocument(markdown).html;
}

function renderMarkdownDocument(markdown, options = {}) {
  const lines = String(markdown || "").split("\n");
  const html = [];
  const headings = [];
  const headingPrefix = options.headingPrefix || "";
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
    if (/^<a\s+id=["'][-\w]+["']><\/a>\s*$/i.test(line.trim())) {
      continue;
    }
    const heading = /^(#{1,4})\s+(.+?)\s*$/.exec(line);
    if (heading) {
      closeTable();
      closeList();
      const level = heading[1].length;
      const text = heading[2].replace(/\s+#+\s*$/, "").trim();
      const id = headingPrefix ? `${headingPrefix}-${headings.length + 1}` : "";
      headings.push({ id, level, text: plainMarkdownText(text) });
      html.push(`<h${level}${id ? ` id="${id}"` : ""}>${inlineMarkdown(escapeHtml(text))}</h${level}>`);
    } else if (isTableLine(line)) {
      closeList();
      if (/^\s*\|?\s*:?-{3,}:?\s*\|/.test(line)) continue;
      const cells = line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => escapeHtml(cell.trim()));
      if (!inTable) {
        html.push("<table><tbody>");
        inTable = true;
      }
      html.push(`<tr>${cells.map((cell) => `<td>${inlineMarkdown(cell)}</td>`).join("")}</tr>`);
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
  if (inCode) {
    html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
  }
  closeTable();
  closeList();
  return { html: html.join(""), headings };

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

function plainMarkdownText(value) {
  return String(value || "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[*_`#]/g, "")
    .trim();
}

function isTableLine(line) {
  return line.trim().startsWith("|") && line.includes("|");
}

function inlineMarkdown(value) {
  const codeParts = [];
  let html = String(value || "").replace(/`([^`]+)`/g, (_match, code) => {
    const index = codeParts.push(`<code>${code}</code>`) - 1;
    return `\u0000CODE_${index}\u0000`;
  });

  html = html
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\(([^)\s]+(?:\s+&quot;[^&]*&quot;)?)\)/g, (_match, label, href) => {
      const cleanHref = String(href || "").replace(/\s+&quot;[^&]*&quot;$/, "");
      const evidenceId = evidenceIdFromLink(label, cleanHref);
      if (evidenceId) {
        return `<a class="evidence-link" href="${cleanHref}" data-evidence-id="${evidenceId}" data-evidence-href="${cleanHref}">${label}</a>`;
      }
      const external = /^https?:\/\//i.test(cleanHref) ? ` target="_blank" rel="noopener noreferrer"` : "";
      return `<a href="${cleanHref}"${external}>${label}</a>`;
    });

  html = autoLinkLocalReportPaths(html);
  html = autoLinkEvidenceIds(html);
  return html.replace(/\u0000CODE_(\d+)\u0000/g, (_match, index) => codeParts[Number(index)] || "");
}

function evidenceIdFromLink(label, href) {
  const labelMatch = String(label || "").match(/\bev_\d{3,}\b/i);
  if (labelMatch) return labelMatch[0].toLowerCase();
  const hrefMatch = String(href || "").match(/#(ev_\d{3,})\b/i);
  return hrefMatch ? hrefMatch[1].toLowerCase() : "";
}

function autoLinkEvidenceIds(html) {
  const parts = String(html || "").split(/(<a\b[^>]*>.*?<\/a>|<code\b[^>]*>.*?<\/code>)/gi);
  return parts
    .map((part) => {
      if (/^<(a|code)\b/i.test(part)) return part;
      return part.replace(/\bev_\d{3,}\b/gi, (evidenceId) => {
        const normalized = evidenceId.toLowerCase();
        return `<button class="evidence-link evidence-token" type="button" data-evidence-id="${normalized}">${evidenceId}</button>`;
      });
    })
    .join("");
}

function autoLinkLocalReportPaths(html) {
  const parts = String(html || "").split(/(<a\b[^>]*>.*?<\/a>|<code\b[^>]*>.*?<\/code>)/gi);
  const pattern = /(?:[A-Za-z]:[\\/][^\s<>"']+?\.md|(?:reports|\.\/reports)\/[^\s<>"']+?\.md)/gi;
  return parts
    .map((part) => {
      if (/^<(a|code)\b/i.test(part)) return part;
      return part.replace(pattern, (pathText) => {
        const reportName = normalizeLocalReportName(pathText);
        if (!reportName) return pathText;
        return `<button class="local-report-link" type="button" data-local-report-path="${escapeHtml(pathText)}">${pathText}</button>`;
      });
    })
    .join("");
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
