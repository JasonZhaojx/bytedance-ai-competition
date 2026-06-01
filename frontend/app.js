let currentJobId = "";
let pollTimer = null;
let isSubmitting = false;

const productDescription = document.querySelector("#productDescription");
const llmProvider = document.querySelector("#llmProvider");
const topN = document.querySelector("#topN");
const qualityMode = document.querySelector("#qualityMode");
const maxIterations = document.querySelector("#maxIterations");
const enableQualityLoop = document.querySelector("#enableQualityLoop");
const arkApiKey = document.querySelector("#arkApiKey");
const bochaApiKey = document.querySelector("#bochaApiKey");
const llmBaseUrl = document.querySelector("#llmBaseUrl");
const llmModel = document.querySelector("#llmModel");
const settingsTopN = document.querySelector("#settingsTopN");
const settingsQualityMode = document.querySelector("#settingsQualityMode");
const settingsMaxIterations = document.querySelector("#settingsMaxIterations");
const settingsEnableQualityLoop = document.querySelector("#settingsEnableQualityLoop");
const saveSettingsBtn = document.querySelector("#saveSettingsBtn");
const knownParamFile = document.querySelector("#knownParamFile");
const knownParamText = document.querySelector("#knownParamText");
const questionnaireFile = document.querySelector("#questionnaireFile");
const questionnaireText = document.querySelector("#questionnaireText");
const startBtn = document.querySelector("#startBtn");
const refreshBtn = document.querySelector("#refreshBtn");
const serverStatus = document.querySelector("#serverStatus");
const jobMeta = document.querySelector("#jobMeta");
const jobStatus = document.querySelector("#jobStatus");
const reportName = document.querySelector("#reportName");
const logBox = document.querySelector("#logBox");
const reportSelect = document.querySelector("#reportSelect");
const reportViewer = document.querySelector("#reportViewer");
const resultSummary = document.querySelector("#resultSummary");
const downloadBtn = document.querySelector("#downloadBtn");
const nodeCards = Array.from(document.querySelectorAll(".node-card"));
const navButtons = Array.from(document.querySelectorAll(".nav-list button"));
const pagePanels = Array.from(document.querySelectorAll("[data-page-panel]"));
const reportLibrary = document.querySelector("#reportLibrary");
const reloadReportsBtn = document.querySelector("#reloadReportsBtn");
const qualityLoopStatus = document.querySelector("#qualityLoopStatus");
const qualityModePreview = document.querySelector("#qualityModePreview");
const maxIterationPreview = document.querySelector("#maxIterationPreview");

startBtn.addEventListener("click", startJob);
refreshBtn.addEventListener("click", handleRefresh);
reloadReportsBtn?.addEventListener("click", () => loadReports({ preserveSelection: true }));
reportSelect.addEventListener("change", () => {
  if (reportSelect.value) loadReport(reportSelect.value);
});
knownParamFile.addEventListener("change", () => readFileInto(knownParamFile, knownParamText));
questionnaireFile.addEventListener("change", () => readFileInto(questionnaireFile, questionnaireText));
qualityMode.addEventListener("change", updateQualityPreview);
maxIterations.addEventListener("input", updateQualityPreview);
enableQualityLoop.addEventListener("change", updateQualityPreview);
saveSettingsBtn?.addEventListener("click", saveSettings);
for (const button of navButtons) {
  button.addEventListener("click", () => showPage(button.dataset.page));
}

document.addEventListener("DOMContentLoaded", () => {
  loadSettings();
  refresh();
  updateQualityPreview();
  initMicroInteractions();
  initKeyboardShortcuts();
});

function initMicroInteractions() {
  const inputs = document.querySelectorAll("input, textarea, select");
  inputs.forEach((input) => {
    input.addEventListener("focus", () => {
      input.parentElement?.classList.add("focused");
    });
    input.addEventListener("blur", () => {
      input.parentElement?.classList.remove("focused");
    });
  });

  document.querySelectorAll(".btn").forEach((btn) => {
    btn.addEventListener("click", function (e) {
      if (this.classList.contains("loading")) return;
      createRipple(this, e);
    });
  });
}

function createRipple(button, event) {
  const ripple = document.createElement("span");
  ripple.className = "ripple";
  const rect = button.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height);
  ripple.style.width = ripple.style.height = `${size}px`;
  ripple.style.left = `${event.clientX - rect.left - size / 2}px`;
  ripple.style.top = `${event.clientY - rect.top - size / 2}px`;
  button.appendChild(ripple);
  setTimeout(() => ripple.remove(), 600);
}

function initKeyboardShortcuts() {
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey) {
      if (e.key === "Enter" && !isSubmitting) {
        e.preventDefault();
        startJob();
      }
    }
    if (e.key === "Escape") {
      const toast = document.querySelector(".toast");
      if (toast) {
        toast.style.animation = "toastOut 0.2s ease-out forwards";
        setTimeout(() => toast.remove(), 200);
      }
    }
  });
}

function showToast(message, type = "info") {
  const existing = document.querySelector(".toast");
  if (existing) {
    existing.style.animation = "toastOut 0.2s ease-out forwards";
    setTimeout(() => existing.remove(), 200);
  }

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;

  const icons = {
    success: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline>',
    error: '<circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line>',
    warning: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>',
    info: '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line>',
  };

  toast.innerHTML = `
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      ${icons[type] || icons.info}
    </svg>
    <span>${message}</span>
  `;
  document.body.appendChild(toast);

  requestAnimationFrame(() => {
    toast.style.animation = "toastIn 0.4s cubic-bezier(0.34, 1.56, 0.64, 1)";
  });

  setTimeout(() => {
    if (toast.parentNode) {
      toast.style.animation = "toastOut 0.3s ease-out forwards";
      setTimeout(() => {
        if (toast.parentNode) toast.remove();
      }, 300);
    }
  }, 4000);
}

const toastStyles = document.createElement("style");
toastStyles.textContent = `
  @keyframes toastIn {
    from { opacity: 0; transform: translateY(24px) scale(0.92); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }
  @keyframes toastOut {
    to { opacity: 0; transform: translateY(12px) scale(0.96); }
  }
  .ripple {
    position: absolute;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.3);
    transform: scale(0);
    animation: rippleEffect 0.6s ease-out;
    pointer-events: none;
  }
  @keyframes rippleEffect {
    to { transform: scale(4); opacity: 0; }
  }
  .btn { position: relative; overflow: hidden; }
`;
document.head.appendChild(toastStyles);

async function startJob() {
  const description = productDescription.value.trim();

  if (!description) {
    productDescription.focus();
    animateValidationError(productDescription);
    showToast("请输入产品需求", "error");
    return;
  }

  if (isSubmitting) return;
  isSubmitting = true;
  currentReportName = "";
  lastReportName = "";
  clearTimeout(pollTimer);

  startBtn.disabled = true;
  startBtn.classList.add("loading");
  startBtn.innerHTML = `
    <svg class="spinner" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
      <circle cx="12" cy="12" r="10" stroke-opacity="0.25"></circle>
      <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"></path>
    </svg>
    <span>分析中...</span>
  `;

  serverStatus.textContent = "Starting";
  serverStatus.style.opacity = "0.6";

  const payload = {
    product_description: description,
    llm_provider: llmProvider.value,
    top_n: Number(topN.value || 5),
    quality_mode: qualityMode.value,
    max_iterations: Number(maxIterations.value || 3),
    enable_quality_loop: enableQualityLoop.checked,
    ark_api_key: arkApiKey.value.trim(),
    bocha_api_key: bochaApiKey.value.trim(),
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
    showToast("任务已启动，正在分析...", "success");
    pollJob();
  } catch (error) {
    serverStatus.textContent = "Error";
    logBox.textContent = String(error);
    showToast("启动失败: " + error.message, "error");
    resetStartButton();
  }
}

function resetStartButton() {
  isSubmitting = false;
  startBtn.disabled = false;
  startBtn.classList.remove("loading");
  startBtn.innerHTML = `
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <polygon points="5 3 19 12 5 21 5 3"></polygon>
    </svg>
    开始分析
  `;
}

function animateValidationError(element) {
  element.style.borderColor = "var(--accent-danger)";
  element.style.animation = "shake 0.4s ease-out";
  setTimeout(() => {
    element.style.borderColor = "";
    element.style.animation = "";
  }, 600);
}

const shakeStyle = document.createElement("style");
shakeStyle.textContent = `
  @keyframes shake {
    0%, 100% { transform: translateX(0); }
    20% { transform: translateX(-8px); }
    40% { transform: translateX(8px); }
    60% { transform: translateX(-4px); }
    80% { transform: translateX(4px); }
  }
`;
document.head.appendChild(shakeStyle);

async function handleRefresh() {
  refreshBtn.disabled = true;
  refreshBtn.innerHTML = `
    <svg class="spinner" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M23 4v6h-6M1 20v-6h6"></path>
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
    </svg>
    刷新中...
  `;
  await refresh();
  setTimeout(() => {
    refreshBtn.disabled = false;
    refreshBtn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="23 4 23 10 17 10"></polyline>
        <polyline points="1 20 1 14 7 14"></polyline>
        <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
      </svg>
      刷新
    `;
  }, 500);
}

async function refresh() {
  await loadReports();
  if (currentJobId) {
    await pollJob();
  }
}

let lastReportName = "";
let currentReportName = "";
let lastJobStatus = "";

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
    } else {
      clearTimeout(pollTimer);
      lastReportName = "";
      if (job.report_name) {
        loadReport(job.report_name);
      } else {
        loadReports();
      }
      resetStartButton();

      if (job.status === "completed") {
        showToast("任务完成！报告已生成", "success");
        celebrateCompletion();
      } else if (job.status === "failed") {
        showToast("任务失败，请查看日志了解详情", "error");
      }
    }
  } catch (error) {
    clearTimeout(pollTimer);
    resetStartButton();
    showToast("获取任务状态失败: " + error.message, "error");
  }
}

function celebrateCompletion() {
  const header = document.querySelector(".page-header");
  if (header) {
    header.style.animation = "celebrate 0.6s ease-out";
    setTimeout(() => {
      header.style.animation = "";
    }, 600);
  }
}

const celebrateStyle = document.createElement("style");
celebrateStyle.textContent = `
  @keyframes celebrate {
    0% { transform: scale(1); }
    50% { transform: scale(1.02); }
    100% { transform: scale(1); }
  }
`;
document.head.appendChild(celebrateStyle);

function renderJob(job) {
  serverStatus.textContent = job.status;
  serverStatus.style.opacity = job.status === "running" ? "0.8" : "1";
  jobStatus.textContent = job.status;
  const desc = job.product_description || "";
  jobMeta.textContent = desc.length > 40 ? desc.slice(0, 40) + "..." : desc;
  reportName.textContent = job.report_name || "生成中";
  logBox.textContent = (job.logs || []).join("\n") || "等待任务日志...";
  logBox.scrollTop = logBox.scrollHeight;
  renderNodeFlow(job);
  qualityLoopStatus.textContent = job.stage || job.status;
}

function renderNodeFlow(job) {
  const stage = job.stage || inferStage(job);
  const order = ["prepare", "discover", "analyze", "summarize", "quality", "done"];
  const currentIndex = order.indexOf(stage);

  const flowNodes = document.querySelectorAll(".flow-node");
  flowNodes.forEach((node) => {
    const nodeStage = node.dataset.stage;
    const index = order.indexOf(nodeStage);

    node.classList.remove("active", "done", "failed");

    if (job.status === "failed" && index === Math.max(currentIndex, 0)) {
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
  if (/总总结已保存|最终报告通过质检|达到最大迭代次数/.test(logs)) return "done";
  if (/最终报告质检闭环|\[quality-loop\]/.test(logs)) return "quality";
  if (/生成所选产品大总结|FINAL COMPARISON|横向对比/.test(logs)) return "summarize";
  if (/等待所选产品分析报告完成|启动独立命令行窗口分析|将要分析的产品|分析窗口已经启动/.test(logs)) {
    return "analyze";
  }
  if (/LLM 改写后的搜索词|搜索到的产品|rewrite search queries|find_product_names/.test(logs)) {
    return "discover";
  }
  return "prepare";
}

async function loadReports(options = {}) {
  const selected = reportSelect.value;

  try {
    const data = await api("/api/reports");
    reportSelect.innerHTML = "";

    if (!data.reports.length) {
      const option = document.createElement("option");
      option.textContent = "暂无报告";
      option.value = "";
      reportSelect.appendChild(option);
      renderSummary(null);
      setDownload("");
      renderReportLibrary([]);
      return;
    }

    const sorted = [...data.reports].sort((a, b) => {
      const finalDelta = Number(b.summary?.is_final || false) - Number(a.summary?.is_final || false);
      if (finalDelta) return finalDelta;
      return b.modified_at - a.modified_at;
    });

    renderReportLibrary(sorted);

    sorted.forEach((report) => {
      const option = document.createElement("option");
      option.value = report.name;
      const typeLabel = report.summary?.is_final ? "最终报告" : "单品报告";
      const title = report.summary?.title || report.name;
      option.textContent = `${typeLabel} · ${title}`;
      reportSelect.appendChild(option);
    });

    if (options.preserveSelection && selected) {
      reportSelect.value = selected;
    }
    if (!reportSelect.value && sorted[0]) {
      reportSelect.value = sorted[0].name;
    }
    if (reportSelect.value) {
      loadReport(reportSelect.value);
    }
  } catch (error) {
    showToast("加载报告列表失败", "error");
  }
}

function renderReportLibrary(reports) {
  if (!reportLibrary) return;

  if (!reports.length) {
    reportLibrary.innerHTML = `
      <div class="report-empty">
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
          <polyline points="14 2 14 8 20 8"></polyline>
          <line x1="12" y1="18" x2="12" y2="12"></line>
          <line x1="9" y1="15" x2="15" y2="15"></line>
        </svg>
        <p>暂无报告</p>
        <span>开始分析后将在此显示</span>
      </div>
    `;
    return;
  }

  reportLibrary.innerHTML = reports
    .map((report, index) => {
      const type = report.summary?.is_final ? "最终报告" : "单品报告";
      const title = escapeHtml(report.summary?.title || report.name);
      const size = formatSize(report.size || 0);
      const date = new Date(report.modified_at * 1000).toLocaleDateString("zh-CN");

      return `
        <div class="report-card slide-in" style="animation-delay: ${index * 50}ms">
          <div class="report-card-header">
            <div class="report-icon">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                <polyline points="14 2 14 8 20 8"></polyline>
              </svg>
            </div>
            <div>
              <h3>${title}</h3>
              <time>${date}</time>
            </div>
          </div>
          <p class="report-card-preview">${escapeHtml(report.name)}</p>
          <div class="report-card-footer">
            <div class="report-meta">
              <span class="report-tag">${type}</span>
              <span class="report-tag">${size}</span>
            </div>
            <button class="btn btn-ghost" data-report="${escapeHtml(report.name)}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                <circle cx="12" cy="12" r="3"></circle>
              </svg>
              查看
            </button>
          </div>
        </div>
      `;
    })
    .join("");

  reportLibrary.querySelectorAll("button[data-report]").forEach((button) => {
    button.addEventListener("click", () => {
      const name = button.dataset.report;
      showPage("workspace");
      reportSelect.value = name;
      loadReport(name);
    });
  });
}

const slideInStyle = document.createElement("style");
slideInStyle.textContent = `
  .slide-in {
    animation: slideIn 0.4s ease-out both;
  }
  @keyframes slideIn {
    from { opacity: 0; transform: translateY(16px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .report-empty {
    grid-column: 1 / -1;
    text-align: center;
    padding: 60px 20px;
    color: var(--text-muted);
  }
  .report-empty svg {
    margin-bottom: 16px;
    opacity: 0.4;
  }
  .report-empty p {
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 4px;
  }
  .report-empty span {
    font-size: 13px;
  }
`;
document.head.appendChild(slideInStyle);

async function loadReport(name) {
  if (name === currentReportName && reportViewer.children.length > 0) return;
  currentReportName = name;
  
  showLoadingSkeleton();

  try {
    const data = await api(`/api/reports/${encodeURIComponent(name)}`);
    renderSummary(data.summary);
    setDownload(data.name);

    setTimeout(() => {
      reportViewer.innerHTML = markdownToHtml(data.content);
      reportViewer.style.opacity = "1";
    }, 300);
  } catch (error) {
    currentReportName = "";
    reportViewer.innerHTML = `
      <div style="text-align: center; padding: 60px 20px; color: var(--accent-danger);">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="margin: 0 auto 16px;">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="15" y1="9" x2="9" y2="15"></line>
          <line x1="9" y1="9" x2="15" y2="15"></line>
        </svg>
        <p>加载报告失败</p>
        <p style="font-size: 12px; margin-top: 8px; color: var(--text-tertiary);">${escapeHtml(error.message)}</p>
      </div>
    `;
    showToast("加载报告失败", "error");
  }
}

function showLoadingSkeleton() {
  reportViewer.style.opacity = "0.4";
  reportViewer.innerHTML = `
    <div class="skeleton-container">
      <div class="skeleton skeleton-title"></div>
      <div class="skeleton skeleton-text"></div>
      <div class="skeleton skeleton-text"></div>
      <div class="skeleton skeleton-text" style="width: 70%"></div>
      <div style="height: 24px"></div>
      <div class="skeleton skeleton-title"></div>
      <div class="skeleton skeleton-text"></div>
      <div class="skeleton skeleton-text"></div>
      <div class="skeleton skeleton-text" style="width: 60%"></div>
    </div>
  `;
}

const skeletonStyle = document.createElement("style");
skeletonStyle.textContent = `
  .skeleton-container {
    padding: 24px;
  }
  .skeleton {
    background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--bg-elevated) 50%, var(--bg-tertiary) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: var(--radius-md);
  }
  @keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
  .skeleton-text {
    height: 14px;
    margin-bottom: 12px;
  }
  .skeleton-title {
    height: 20px;
    width: 50%;
    margin-bottom: 20px;
  }
`;
document.head.appendChild(skeletonStyle);

function renderSummary(summary) {
  const values = summary
    ? [
        summary.is_final ? "最终报告" : "单品报告",
        summary.quality_feedback_applied ? "已应用" : "无",
        String(summary.sections || 0),
        formatCharCount(summary.chars || 0),
      ]
    : ["暂无", "暂无", "0", "0"];

  const cards = resultSummary.querySelectorAll("strong");
  cards.forEach((card, index) => {
    card.textContent = values[index];
  });
}

function formatCharCount(chars) {
  if (chars > 10000) {
    return `${(chars / 10000).toFixed(1)}万`;
  }
  return String(chars);
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
  navButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.page === page);
  });

  pagePanels.forEach((panel) => {
    if (panel.dataset.pagePanel === page) {
      panel.classList.add("active");
      panel.style.animation = "fadeInUp 0.4s ease-out";
    } else {
      panel.classList.remove("active");
    }
  });
}

function updateQualityPreview() {
  qualityModePreview.textContent = qualityMode.value;
  maxIterationPreview.textContent = maxIterations.value || "3";
  qualityLoopStatus.textContent = enableQualityLoop.checked ? "已启用" : "已关闭";
}

function loadSettings() {
  const settings = JSON.parse(localStorage.getItem("competitor_ai_settings") || "{}");
  llmProvider.value = settings.llm_provider || "0";
  arkApiKey.value = settings.ark_api_key || "";
  bochaApiKey.value = settings.bocha_api_key || "";
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
    llm_base_url: llmBaseUrl.value.trim(),
    llm_model: llmModel.value.trim(),
    top_n: settingsTopN.value,
    quality_mode: settingsQualityMode.value,
    max_iterations: settingsMaxIterations.value,
    enable_quality_loop: settingsEnableQualityLoop.checked,
  };

  localStorage.setItem("competitor_ai_settings", JSON.stringify(settings));
  syncSettingsToWorkspace();

  const originalHTML = saveSettingsBtn.innerHTML;
  saveSettingsBtn.innerHTML = `
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <polyline points="20 6 9 17 4 12"></polyline>
    </svg>
    已保存
  `;
  saveSettingsBtn.style.background = "var(--accent-success)";
  showToast("设置已保存", "success");

  setTimeout(() => {
    saveSettingsBtn.innerHTML = originalHTML;
    saveSettingsBtn.style.background = "";
  }, 2000);
}

function syncSettingsToWorkspace() {
  topN.value = settingsTopN.value || "5";
  qualityMode.value = settingsQualityMode.value || "rule";
  maxIterations.value = settingsMaxIterations.value || "3";
  enableQualityLoop.checked = settingsEnableQualityLoop.checked;
  updateQualityPreview();
}

function formatSize(value) {
  if (value > 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value > 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || response.statusText);
  }
  return data;
}

function markdownToHtml(markdown) {
  const lines = markdown.split("\n");
  const html = [];
  let inList = false;
  let inTable = false;

  for (const line of lines) {
    if (isTableLine(line)) {
      closeList();
      if (/^\s*\|?\s*:?-{3,}:?\s*\|/.test(line)) continue;

      const cells = line
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => escapeHtml(cell.trim()));

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
    } else if (line.startsWith("- ")) {
      closeTable();
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${inlineMarkdown(escapeHtml(line.slice(2)))}</li>`);
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
  return value
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
    showToast(`已加载文件: ${file.name}`, "success");
  };
  reader.onerror = () => {
    showToast("文件读取失败", "error");
  };
  reader.readAsText(file, "utf-8");
}

reportViewer.style.transition = "opacity 0.3s ease-out";
