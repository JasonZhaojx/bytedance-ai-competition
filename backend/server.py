"""Small standard-library web backend for running analysis jobs."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
REPORT_DIR = ROOT / "reports"
RUNNER = ROOT / "run_similar_product_reports_with_new_analyze_quality.py"
DEFAULT_PORT = int(os.getenv("WEB_PORT", "8000"))


@dataclass
class Job:
    job_id: str
    product_description: str
    created_at: float = field(default_factory=time.time)
    status: str = "queued"
    stage: str = "prepare"
    logs: list[str] = field(default_factory=list)
    runtime_logs: list[str] = field(default_factory=list)
    log_section: str = ""
    search_queries: list[str] = field(default_factory=list)
    candidate_products: list[str] = field(default_factory=list)
    subtasks: list[dict[str, Any]] = field(default_factory=list)
    return_code: int | None = None
    report_path: str = ""
    error: str = ""
    manual_product_selection: str = ""
    process_pid: int | None = None
    thread_name: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    last_output_at: float | None = None

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        return {
            "job_id": self.job_id,
            "product_description": self.product_description,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "stage": self.stage,
            "return_code": self.return_code,
            "report_path": self.report_path,
            "report_name": report_display_name(Path(self.report_path))
            if self.report_path
            else "",
            "error": self.error,
            "manual_product_selection": self.manual_product_selection,
            "process_pid": self.process_pid,
            "thread_name": self.thread_name,
            "thread_alive": self.status in {"queued", "running"},
            "last_output_at": self.last_output_at,
            "idle_seconds": round(now - self.last_output_at, 1)
            if self.last_output_at
            else None,
            "logs": self.logs[-500:],
            "runtime_logs": self.runtime_logs[-200:],
            "search_queries": self.search_queries,
            "candidate_products": self.candidate_products,
            "subtasks": self.subtasks,
        }


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
FINAL_REPORT_RE = re.compile(
    r"(?:总总结已保存|Markdown 已保存|Report Agent Markdown 已保存):\s*(.+\.md)"
)


class AppHandler(BaseHTTPRequestHandler):
    server_version = "CompetitorWorkflowWeb/1.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/jobs":
            self._send_json({"jobs": [job.snapshot() for job in _jobs_sorted()]})
            return
        if path.startswith("/api/jobs/"):
            self._handle_get_job(path)
            return
        if path == "/api/reports":
            self._send_json({"reports": list_reports()})
            return
        if path.startswith("/api/reports/"):
            self._handle_get_report(path)
            return
        if path.startswith("/download/reports/"):
            self._handle_download_report(path)
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/jobs":
            self._handle_create_job()
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _handle_create_job(self) -> None:
        try:
            payload = self._read_json()
            product_description = str(payload.get("product_description", "")).strip()
            if not product_description:
                self._send_json(
                    {"error": "product_description is required"},
                    HTTPStatus.BAD_REQUEST,
                )
                return
            options = normalize_options(payload)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        job = Job(
            job_id=uuid.uuid4().hex[:12],
            product_description=product_description,
            manual_product_selection=options["manual_product_selection"],
        )
        with JOBS_LOCK:
            JOBS[job.job_id] = job
        thread = threading.Thread(target=run_job, args=(job, options), daemon=True)
        thread.start()
        self._send_json(job.snapshot(), HTTPStatus.CREATED)

    def _handle_get_job(self, path: str) -> None:
        parts = path.strip("/").split("/")
        if len(parts) < 3:
            self._send_json({"error": "job id required"}, HTTPStatus.BAD_REQUEST)
            return
        job_id = parts[2]
        with JOBS_LOCK:
            job = JOBS.get(job_id)
        if not job:
            self._send_json({"error": "job not found"}, HTTPStatus.NOT_FOUND)
            return
        self._send_json(job.snapshot())

    def _handle_get_report(self, path: str) -> None:
        name = unquote(path.split("/api/reports/", 1)[1])
        report_path = safe_report_path(name)
        if not report_path or not report_path.exists():
            self._send_json({"error": "report not found"}, HTTPStatus.NOT_FOUND)
            return
        content = report_path.read_text(encoding="utf-8", errors="replace")
        self._send_json(
            {
                "name": report_display_name(report_path),
                "path": str(report_path),
                "modified_at": report_path.stat().st_mtime,
                "size": report_path.stat().st_size,
                "content": content,
                "summary": summarize_report(report_path, content),
            }
        )

    def _handle_download_report(self, path: str) -> None:
        name = unquote(path.split("/download/reports/", 1)[1])
        report_path = safe_report_path(name)
        if not report_path or not report_path.exists():
            self._send_json({"error": "report not found"}, HTTPStatus.NOT_FOUND)
            return
        data = report_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/markdown; charset=utf-8")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{report_path.name}"',
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            file_path = FRONTEND_DIR / "index.html"
        else:
            file_path = (FRONTEND_DIR / unquote(path.lstrip("/"))).resolve()
            frontend_root = FRONTEND_DIR.resolve()
            if frontend_root not in file_path.parents and file_path != frontend_root:
                self._send_json({"error": "invalid path"}, HTTPStatus.BAD_REQUEST)
                return
        if not file_path.exists() or not file_path.is_file():
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type(file_path))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def normalize_options(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "top_n": clamp_int(payload.get("top_n"), 1, 20, int(os.getenv("TOP_N", "5"))),
        "query_count": clamp_int(payload.get("query_count"), 1, 10, int(os.getenv("QUERY_COUNT", "3"))),
        "search_count": clamp_int(payload.get("search_count"), 1, 10, int(os.getenv("SEARCH_COUNT", "3"))),
        "search_backend": clamp_int(payload.get("search_backend"), 0, 2, int(os.getenv("SEARCH_BACKEND", "2"))),
        "analyze_timeout": clamp_int(payload.get("analyze_timeout"), 60, 7200, int(os.getenv("ANALYZE_TIMEOUT", "1200"))),
        "final_summary_timeout": clamp_int(payload.get("final_summary_timeout"), 60, 7200, int(os.getenv("FINAL_SUMMARY_TIMEOUT", "900"))),
        "known_param_max_chars": clamp_int(payload.get("known_param_max_chars"), 0, 100000, int(os.getenv("KNOWN_PRODUCT_PARAM_MAX_CHARS", "0"))),
        "questionnaire_max_chars": clamp_int(payload.get("questionnaire_max_chars"), 0, 100000, int(os.getenv("QUESTIONNAIRE_ANALYSIS_MAX_CHARS", "0"))),
        "evidence_mode": clamp_int(payload.get("evidence_mode"), 0, 2, int(os.getenv("REPORT_AGENT_EVIDENCE_MODE", "2"))),
        "feedback_queries": clamp_int(payload.get("feedback_queries"), 0, 10, int(os.getenv("REPORT_AGENT_QUALITY_MAX_FEEDBACK_QUERIES", "2"))),
        "quality_feedback_search_backend": clamp_int(payload.get("quality_feedback_search_backend"), 0, 2, int(os.getenv("QUALITY_FEEDBACK_SEARCH_BACKEND", "0"))),
        "retry_on_minor": bool(payload.get("retry_on_minor", False)),
        "quality_mode": str(payload.get("quality_mode") or "rule"),
        "max_iterations": clamp_int(payload.get("max_iterations"), 1, 10, 3),
        "enable_quality_loop": bool(payload.get("enable_quality_loop", True)),
        "llm_provider": str(payload.get("llm_provider") or ""),
        "ark_api_key": str(payload.get("ark_api_key") or "").strip(),
        "llm_base_url": str(payload.get("llm_base_url") or "").strip(),
        "llm_model": str(payload.get("llm_model") or "").strip(),
        "bocha_api_key": str(payload.get("bocha_api_key") or "").strip(),
        "google_api_key": str(payload.get("google_api_key") or "").strip(),
        "google_cx_id": str(payload.get("google_cx_id") or "").strip(),
        "known_param_text": str(payload.get("known_param_text") or ""),
        "questionnaire_analysis_text": str(payload.get("questionnaire_analysis_text") or ""),
        "manual_product_selection": normalize_selection(
            str(payload.get("manual_product_selection") or "")
        ),
    }


def clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def normalize_selection(value: str) -> str:
    parts = [part.strip() for part in re.split(r"[,，、;\n]+", value) if part.strip()]
    return ", ".join(dict.fromkeys(parts))


def run_job(job: Job, options: dict[str, Any]) -> None:
    job.status = "running"
    job.thread_name = threading.current_thread().name
    job.started_at = time.time()
    job.last_output_at = job.started_at
    append_runtime_log(job, f"worker thread started: {job.thread_name}")
    set_stage(job, "prepare")
    env = os.environ.copy()
    if env.get("USE_NETWORK_PROXY", "false").lower() not in {"1", "true", "yes", "on"}:
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            env.pop(name, None)
    env.update(
        {
            "PYTHONUNBUFFERED": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "DISABLE_ANALYZE_CONSOLES": "1",
            "TOP_N": str(options["top_n"]),
            "QUERY_COUNT": str(options["query_count"]),
            "SEARCH_COUNT": str(options["search_count"]),
            "SEARCH_BACKEND": str(options["search_backend"]),
            "ANALYZE_TIMEOUT": str(options["analyze_timeout"]),
            "FINAL_SUMMARY_TIMEOUT": str(options["final_summary_timeout"]),
            "KNOWN_PRODUCT_PARAM_MAX_CHARS": str(options["known_param_max_chars"]),
            "QUESTIONNAIRE_ANALYSIS_MAX_CHARS": str(options["questionnaire_max_chars"]),
            "ENABLE_FINAL_QUALITY_LOOP": "true"
            if options["enable_quality_loop"]
            else "false",
            "FINAL_QUALITY_MODE": options["quality_mode"],
            "FINAL_QUALITY_MAX_ITERATIONS": str(options["max_iterations"]),
            "REPORT_AGENT_QUALITY_ENABLED": "1" if options["enable_quality_loop"] else "0",
            "REPORT_AGENT_QUALITY_MAX_ROUNDS": str(options["max_iterations"]),
            "REPORT_AGENT_QUALITY_RETRY_ON_MINOR": "1" if options["retry_on_minor"] else "0",
            "REPORT_AGENT_QUALITY_MAX_FEEDBACK_QUERIES": str(options["feedback_queries"]),
            "QUALITY_FEEDBACK_SEARCH_BACKEND": str(options["quality_feedback_search_backend"]),
            "REPORT_AGENT_EVIDENCE_MODE": str(options["evidence_mode"]),
            "INSPECTION_MODE": quality_mode_to_env(options["quality_mode"]),
        }
    )
    apply_user_env(job, env, options)
    command = [sys.executable, "-u", str(RUNNER), job.product_description]
    append_log(job, "$ " + " ".join(command))
    append_runtime_log(job, "launch main workflow process")
    try:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        job.process_pid = process.pid
        append_runtime_log(job, f"process started pid={process.pid}")
        if process.stdin:
            selection = options["manual_product_selection"]
            selection_label = selection or f"默认前 {options['top_n']} 个"
            append_log(
                job,
                f"[web-input] 产品选择: {selection_label}",
            )
            append_runtime_log(job, f"stdin product selection sent: {selection_label}")
            process.stdin.write(selection + "\n")
            process.stdin.flush()
            process.stdin.close()
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip("\r\n")
            append_log(job, line)
            job.last_output_at = time.time()
            update_stage_from_log(job, line)
            update_runtime_from_log(job, line)
            match = FINAL_REPORT_RE.search(line)
            if match:
                job.report_path = match.group(1).strip()
        job.return_code = process.wait()
        job.finished_at = time.time()
        job.status = "completed" if job.return_code == 0 else "failed"
        append_runtime_log(job, f"process exited code={job.return_code}")
        if job.status == "completed":
            set_stage(job, "done")
        if job.return_code != 0:
            job.error = f"process exited with code {job.return_code}"
    except Exception as exc:
        job.status = "failed"
        job.finished_at = time.time()
        job.error = str(exc)
        append_log(job, f"[backend-error] {exc}")
        append_runtime_log(job, f"backend exception: {exc}")


def apply_user_env(job: Job, env: dict[str, str], options: dict[str, Any]) -> None:
    if options["llm_provider"]:
        env["LLM_PROVIDER"] = options["llm_provider"]
    if options["ark_api_key"]:
        env["ARK_API_KEY"] = options["ark_api_key"]
        env["LLM_API_KEY"] = options["ark_api_key"]
        env["LLM0_API_KEY"] = options["ark_api_key"]
    if options["llm_base_url"]:
        env["LLM_BASE_URL"] = options["llm_base_url"]
        env["LLM0_BASE_URL"] = options["llm_base_url"]
    if options["llm_model"]:
        env["LLM_MODEL"] = options["llm_model"]
        env["LLM0_MODEL"] = options["llm_model"]
    if options["bocha_api_key"]:
        env["BOCHA_API_KEY"] = options["bocha_api_key"]
    if options["google_api_key"]:
        env["GOOGLE_API_KEY"] = options["google_api_key"]
    if options["google_cx_id"]:
        env["GOOGLE_CX_ID"] = options["google_cx_id"]

    input_dir = REPORT_DIR / "web_inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    known_path = input_dir / f"{job.job_id}_known_params.txt"
    known_path.write_text(options["known_param_text"].strip(), encoding="utf-8")
    env["KNOWN_PRODUCT_PARAM_TXT"] = str(known_path)

    questionnaire_path = input_dir / f"{job.job_id}_questionnaire.md"
    questionnaire_path.write_text(
        options["questionnaire_analysis_text"].strip(),
        encoding="utf-8",
    )
    env["QUESTIONNAIRE_ANALYSIS_MD"] = str(questionnaire_path)


def quality_mode_to_env(value: str) -> str:
    mapping = {
        "rule": "rule_only",
        "hybrid": "hybrid_voting",
        "llm": "llm_fallback",
    }
    return mapping.get(str(value or "").strip().lower(), "rule_only")


STAGE_ORDER = ["prepare", "discover", "select", "analyze", "summarize", "quality", "done"]


def set_stage(job: Job, stage: str) -> None:
    with JOBS_LOCK:
        if stage in STAGE_ORDER and STAGE_ORDER.index(stage) >= STAGE_ORDER.index(job.stage):
            if stage != job.stage:
                job.runtime_logs.append(
                    f"{time.strftime('%H:%M:%S')} stage {job.stage} -> {stage}"
                )
            job.stage = stage


def update_stage_from_log(job: Job, line: str) -> None:
    if any(
        token in line
        for token in (
            "LLM 改写后的搜索词",
            "搜索到的产品",
            "rewrite search queries",
            "find_product_names",
        )
    ):
        set_stage(job, "discover")
    elif any(token in line for token in ("请选择", "[web-input] 产品选择")):
        set_stage(job, "select")
    elif any(
        token in line
        for token in (
            "将要分析的产品",
            "启动独立命令行窗口分析",
            "等待所选产品分析报告完成",
            "分析窗口已经启动",
        )
    ):
        set_stage(job, "analyze")
    elif any(
        token in line
        for token in (
            "生成所选产品大总结",
            "Report Agent 标准分析链路",
            "FINAL COMPARISON",
        )
    ):
        set_stage(job, "summarize")
    elif any(token in line for token in ("Quality Agent 质检", "最终报告质检闭环", "[quality-loop]")):
        set_stage(job, "quality")
    elif "总总结已保存" in line or "Markdown 已保存" in line:
        set_stage(job, "done")


def update_runtime_from_log(job: Job, line: str) -> None:
    stripped = line.strip()
    if not stripped:
        return
    section_match = re.match(r"^=+\s*(.+?)\s*=+$", stripped)
    if section_match:
        job.log_section = section_match.group(1)
        append_runtime_log(job, f"section: {job.log_section}")
        return

    if job.log_section == "LLM 改写后的搜索词" and stripped.startswith("- "):
        query = stripped[2:].strip()
        if query and query not in job.search_queries:
            job.search_queries.append(query)
            append_runtime_log(job, f"search query queued: {query}")
        return

    if job.log_section == "搜索到的产品":
        match = re.match(r"^\d+[.)、]\s*(.+)$", stripped)
        if match:
            product = match.group(1).strip()
            if product and product not in job.candidate_products:
                job.candidate_products.append(product)
                append_runtime_log(job, f"candidate product found: {product}")
        return

    if job.log_section == "将要分析的产品":
        match = re.match(r"^\d+[.)、]\s*(.+)$", stripped)
        if match:
            ensure_subtask(job, match.group(1).strip(), "queued")
        return

    if stripped.startswith("[started]"):
        match = re.match(r"^\[started\]\s+(.+?)\s+provider=", stripped)
        product = match.group(1).strip() if match else stripped.replace("[started]", "").strip()
        ensure_subtask(job, product, "running")
        append_runtime_log(job, f"analysis subtask started: {product}")
        return

    if stripped.startswith("[failed]"):
        product = stripped.replace("[failed]", "", 1).split(":", 1)[0].strip()
        ensure_subtask(job, product, "failed")
        append_runtime_log(job, f"analysis subtask failed: {product}")
        return

    if "报告写入" in stripped or "Report Agent Markdown 已保存" in stripped:
        mark_running_subtasks(job, "done")


def ensure_subtask(job: Job, product: str, status: str) -> None:
    if not product:
        return
    with JOBS_LOCK:
        for item in job.subtasks:
            if item.get("name") == product:
                item["status"] = status
                item["updated_at"] = time.time()
                return
        job.subtasks.append(
            {
                "name": product,
                "status": status,
                "updated_at": time.time(),
            }
        )


def mark_running_subtasks(job: Job, status: str) -> None:
    with JOBS_LOCK:
        for item in job.subtasks:
            if item.get("status") == "running":
                item["status"] = status
                item["updated_at"] = time.time()


def append_log(job: Job, line: str) -> None:
    with JOBS_LOCK:
        job.logs.append(line)
        if len(job.logs) > 2000:
            del job.logs[: len(job.logs) - 2000]


def append_runtime_log(job: Job, line: str) -> None:
    with JOBS_LOCK:
        job.runtime_logs.append(f"{time.strftime('%H:%M:%S')} {line}")
        if len(job.runtime_logs) > 500:
            del job.runtime_logs[: len(job.runtime_logs) - 500]


def _jobs_sorted() -> list[Job]:
    with JOBS_LOCK:
        return sorted(JOBS.values(), key=lambda item: item.created_at, reverse=True)


def list_reports() -> list[dict[str, Any]]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    reports = [
        path
        for path in REPORT_DIR.rglob("*.md")
        if "web_inputs" not in path.relative_to(REPORT_DIR).parts
    ]
    reports = sorted(reports, key=lambda path: path.stat().st_mtime, reverse=True)
    return [
        {
            "name": report_display_name(path),
            "path": str(path),
            "modified_at": path.stat().st_mtime,
            "size": path.stat().st_size,
            "summary": summarize_report(path),
        }
        for path in reports[:200]
    ]


def summarize_report(path: Path, text: str | None = None) -> dict[str, Any]:
    text = text if text is not None else path.read_text(encoding="utf-8", errors="replace")
    title = path.stem
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    report_type = report_type_for(path)
    issues = extract_issues(text)
    references = sorted(set(re.findall(r"\[(?:[^]\[]+\])?\[?参考点\d+\]?", text)))
    return {
        "title": title,
        "task_id": task_id_for_report(path),
        "round": quality_round_for(path),
        "type": report_type,
        "is_final": report_type == "final",
        "is_report_agent": report_type == "report_agent",
        "is_single": report_type == "single",
        "is_quality": report_type == "quality",
        "quality_feedback_applied": (
            "===== QUALITY AGENT SUMMARY =====" in text
            or "===== QUALITY AGENT REPORT =====" in text
            or "===== QUALITY FEEDBACK APPLIED =====" in text
        ),
        "relative_name": report_display_name(path),
        "sections": len(re.findall(r"^#{1,3}\s+", text, flags=re.MULTILINE)),
        "chars": len(text),
        "reference_count": len(references),
        "issue_count": len(issues),
        "issues": issues[:8],
    }


def extract_issues(text: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    issue_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^#{1,4}\s+.*(issue|问题|风险|缺口|不足|待修复)", stripped, re.I):
            issue_block = True
            continue
        if issue_block and stripped.startswith("#"):
            issue_block = False
        if not issue_block and not re.search(r"(issue|问题|风险|缺口|不足|待修复)", stripped, re.I):
            continue
        if stripped.startswith(("-", "*")) or re.match(r"^\d+[.)、]\s+", stripped):
            normalized = re.sub(r"^[-*\d.)、\s]+", "", stripped)
            issues.append(issue_to_payload(normalized))
    return issues


def issue_to_payload(value: str) -> dict[str, str]:
    severity = "medium"
    lowered = value.lower()
    if any(token in lowered for token in ("critical", "严重", "高风险", "major")):
        severity = "high"
    elif any(token in lowered for token in ("minor", "轻微", "low")):
        severity = "low"
    return {
        "severity": severity,
        "title": value[:80],
        "detail": value,
    }


def report_display_name(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPORT_DIR.resolve()).as_posix()
    except ValueError:
        return path.name


def task_id_for_report(path: Path) -> str:
    try:
        relative = path.resolve().relative_to(REPORT_DIR.resolve())
    except ValueError:
        return path.stem
    if relative.parts[:1] == ("quality_workflow",) and len(relative.parts) >= 2:
        match = re.match(r"^(\d{8}_\d{6})", relative.parts[1])
        return match.group(1) if match else relative.parts[1]
    first = relative.parts[0]
    if len(relative.parts) > 1 and re.match(r"^\d{8}_\d{6}$", first):
        return first
    match = re.match(r"^(\d{8}_\d{6})", path.name)
    return match.group(1) if match else path.stem


def quality_round_for(path: Path) -> str:
    try:
        relative = path.resolve().relative_to(REPORT_DIR.resolve())
    except ValueError:
        return ""
    for part in relative.parts:
        if re.match(r"^round_\d+$", part):
            return part
    return ""


def report_type_for(path: Path) -> str:
    try:
        relative = path.resolve().relative_to(REPORT_DIR.resolve())
    except ValueError:
        relative = Path(path.name)
    if "quality_workflow" in relative.parts:
        return "quality"
    name = path.name.upper()
    if "FINAL_COMPARISON" in name:
        return "final"
    if "REPORT_AGENT_ANALYSIS" in name:
        return "report_agent"
    return "single"


def safe_report_path(name: str) -> Path | None:
    candidate = (REPORT_DIR / name).resolve()
    report_root = REPORT_DIR.resolve()
    if report_root not in candidate.parents and candidate != report_root:
        return None
    if candidate.suffix.lower() != ".md":
        return None
    return candidate


def content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".html":
        return "text/html; charset=utf-8"
    if suffix == ".css":
        return "text/css; charset=utf-8"
    if suffix == ".js":
        return "application/javascript; charset=utf-8"
    return "application/octet-stream"


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
    print(f"Web console: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
