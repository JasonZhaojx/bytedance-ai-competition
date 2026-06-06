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
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.quality_agent.adapters.report_adapter import ReportAnalysis
from agent.quality_agent.inspectors.section_issue_inspector import (
    build_final_body_section_issues,
)
from skill_wiki_builder.build_skill_wiki import (
    MARKER as SKILL_WIKI_MARKER,
    apply_wiki_payload,
    call_wiki_llm,
    extract_article,
    prepare_article_notes,
    read_existing_wiki,
    write_source_memory_files,
)
from skill_wiki_builder.chat_with_skill_wiki import ask_wiki, load_wiki_docs

import generate_competitor_questionnaire as questionnaire_flow


FRONTEND_DIR = ROOT / "frontend"
REPORT_DIR = ROOT / "reports"
SKILL_WIKI_ROOT = REPORT_DIR / "skill_wikis"
LEGACY_SKILL_WIKI_DIR = REPORT_DIR / "skill_wiki"
QUESTIONNAIRE_DIR = ROOT / "questionnaires"
RUNNER = ROOT / "run_similar_product_reports_with_new_analyze_quality.py"
DEFAULT_PORT = int(os.getenv("WEB_PORT", "8000"))
DEFAULT_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "0")

# Optional local defaults for this web server. Keep these empty in shared code.
# You can fill them on your own machine, or set the matching environment variables.
LOCAL_ARK_API_KEY = "ARK_API_KEY_REDACTED"
LOCAL_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
LOCAL_ARK_MODEL = "ep-20260514111325-xjmj7"
LOCAL_BOCHA_API_KEY = ""#填写在这（博查）
LOCAL_GOOGLE_API_KEY = ""
LOCAL_GOOGLE_CX_ID = ""

DEFAULT_ARK_API_KEY = (
    LOCAL_ARK_API_KEY
    or os.getenv("REPORT_LLM_API_KEY")
    or os.getenv("LLM0_API_KEY")
    or os.getenv("ARK_API_KEY")
    or os.getenv("LLM_API_KEY")
    or ""
)
DEFAULT_ARK_BASE_URL = (
    LOCAL_ARK_BASE_URL
    or os.getenv("REPORT_LLM_BASE_URL")
    or os.getenv("LLM0_BASE_URL")
    or os.getenv("LLM_BASE_URL")
    or "https://ark.cn-beijing.volces.com/api/v3"
)
DEFAULT_ARK_MODEL = (
    LOCAL_ARK_MODEL
    or os.getenv("REPORT_LLM_MODEL")
    or os.getenv("LLM0_MODEL")
    or os.getenv("LLM_MODEL")
    or "ep-20260514111325-xjmj7"
)
DEFAULT_BOCHA_API_KEY = LOCAL_BOCHA_API_KEY or os.getenv("BOCHA_API_KEY", "")
DEFAULT_GOOGLE_API_KEY = LOCAL_GOOGLE_API_KEY or os.getenv("GOOGLE_API_KEY", "")
DEFAULT_GOOGLE_CX_ID = LOCAL_GOOGLE_CX_ID or os.getenv("GOOGLE_CX_ID", "")


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
    waiting_for_selection: bool = False
    selection_submitted: bool = False
    stdin_closed: bool = False
    selection_prompt_logged: bool = False
    terminate_requested: bool = False
    process: Any | None = field(default=None, repr=False, compare=False)
    process_stdin: Any | None = field(default=None, repr=False, compare=False)
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
            "waiting_for_selection": self.waiting_for_selection,
            "selection_submitted": self.selection_submitted,
            "stdin_closed": self.stdin_closed,
            "terminate_requested": self.terminate_requested,
            "process_pid": self.process_pid,
            "thread_name": self.thread_name,
            "thread_alive": self.status in {"queued", "running", "terminating"},
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
QUESTIONNAIRE_LOCK = threading.Lock()
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
        if path == "/api/questionnaires":
            self._send_json({"files": list_questionnaire_files()})
            return
        if path.startswith("/api/questionnaires/file/"):
            self._handle_get_questionnaire_file(path)
            return
        if path == "/api/skill-wikis":
            self._send_json({"skills": list_skill_wikis()})
            return
        if path.startswith("/api/skill-wikis/"):
            self._handle_get_skill_wiki(path)
            return
        if path == "/api/issues":
            params = parse_qs(parsed.query)
            task_id = (params.get("task") or [""])[0].strip()
            if task_id:
                self._send_json({"issues": list_issues(task_id=task_id)})
            else:
                self._send_json({"groups": list_issue_groups()})
            return
        if path.startswith("/api/reports/"):
            self._handle_get_report(path)
            return
        if path.startswith("/download/reports/"):
            self._handle_download_report(path)
            return
        if path.startswith("/download/questionnaires/"):
            self._handle_download_questionnaire_file(path)
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/jobs":
            self._handle_create_job()
            return
        if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/terminate"):
            self._handle_terminate_job(parsed.path)
            return
        if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/selection"):
            self._handle_product_selection(parsed.path)
            return
        if parsed.path == "/api/questionnaires/generate":
            self._handle_generate_questionnaire()
            return
        if parsed.path == "/api/questionnaires/simulate":
            self._handle_simulate_questionnaire()
            return
        if parsed.path == "/api/questionnaires/analyze":
            self._handle_analyze_questionnaire()
            return
        if parsed.path == "/api/skill-wikis/build":
            self._handle_build_skill_wiki()
            return
        if parsed.path == "/api/skill-wikis/chat":
            self._handle_skill_wiki_chat()
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

    def _handle_product_selection(self, path: str) -> None:
        parts = path.strip("/").split("/")
        if len(parts) != 4 or parts[0] != "api" or parts[1] != "jobs" or parts[3] != "selection":
            self._send_json({"error": "invalid selection path"}, HTTPStatus.BAD_REQUEST)
            return
        payload = self._read_json()
        selection = normalize_selection(str(payload.get("selection") or ""))
        if not selection:
            self._send_json({"error": "selection is required"}, HTTPStatus.BAD_REQUEST)
            return
        with JOBS_LOCK:
            job = JOBS.get(parts[2])
        if not job:
            self._send_json({"error": "job not found"}, HTTPStatus.NOT_FOUND)
            return
        ok, message = submit_product_selection(job, selection)
        if not ok:
            self._send_json({"error": message}, HTTPStatus.CONFLICT)
            return
        self._send_json(job.snapshot())

    def _handle_terminate_job(self, path: str) -> None:
        parts = path.strip("/").split("/")
        if len(parts) != 4 or parts[0] != "api" or parts[1] != "jobs" or parts[3] != "terminate":
            self._send_json({"error": "invalid terminate path"}, HTTPStatus.BAD_REQUEST)
            return
        with JOBS_LOCK:
            job = JOBS.get(parts[2])
        if not job:
            self._send_json({"error": "job not found"}, HTTPStatus.NOT_FOUND)
            return
        ok, message = terminate_job(job)
        if not ok:
            self._send_json({"error": message}, HTTPStatus.CONFLICT)
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

    def _handle_get_questionnaire_file(self, path: str) -> None:
        name = unquote(path.split("/api/questionnaires/file/", 1)[1])
        file_path = safe_questionnaire_path(name)
        if not file_path or not file_path.exists():
            self._send_json({"error": "questionnaire file not found"}, HTTPStatus.NOT_FOUND)
            return
        content = file_path.read_text(encoding="utf-8", errors="replace")
        self._send_json(
            {
                "file": questionnaire_file_info(file_path),
                "content": content,
            }
        )

    def _handle_download_questionnaire_file(self, path: str) -> None:
        name = unquote(path.split("/download/questionnaires/", 1)[1])
        file_path = safe_questionnaire_path(name)
        if not file_path or not file_path.exists():
            self._send_json({"error": "questionnaire file not found"}, HTTPStatus.NOT_FOUND)
            return
        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type(file_path))
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{file_path.name}"',
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_generate_questionnaire(self) -> None:
        try:
            payload = self._read_json()
            result = generate_questionnaire_from_payload(payload)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(result, HTTPStatus.CREATED)

    def _handle_simulate_questionnaire(self) -> None:
        try:
            payload = self._read_json()
            result = simulate_questionnaire_from_payload(payload)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(result, HTTPStatus.CREATED)

    def _handle_analyze_questionnaire(self) -> None:
        try:
            payload = self._read_json()
            result = analyze_questionnaire_from_payload(payload)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(result, HTTPStatus.CREATED)

    def _handle_get_skill_wiki(self, path: str) -> None:
        skill_id = unquote(path.split("/api/skill-wikis/", 1)[1]).strip("/")
        detail = skill_wiki_detail(skill_id, include_docs=True)
        if not detail:
            self._send_json({"error": "skill wiki not found"}, HTTPStatus.NOT_FOUND)
            return
        self._send_json({"skill": detail})

    def _handle_build_skill_wiki(self) -> None:
        try:
            detail = build_skill_wiki_from_report(self._read_json())
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"skill": detail}, HTTPStatus.CREATED)

    def _handle_skill_wiki_chat(self) -> None:
        try:
            payload = self._read_json()
            answer = answer_skill_wiki(payload)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(answer)

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
        "top_n": clamp_int(payload.get("top_n"), 1, 20, int(os.getenv("TOP_N", "3"))),
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
        "quality_mode": "rule",
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


def looks_like_secret(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if re.match(r"^(ark|sk)-[A-Za-z0-9_-]{16,}$", text):
        return True
    return False


def sanitize_llm_model(value: str, api_key: str = "") -> tuple[str, str]:
    model = str(value or "").strip()
    if not model:
        return "", ""
    key = str(api_key or "").strip()
    if key and model == key:
        return "", "LLM Model/Endpoint is identical to the API key; ignored."
    if looks_like_secret(model):
        return "", "LLM Model/Endpoint looks like an API key; ignored."
    return model, ""


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
    with JOBS_LOCK:
        if job.terminate_requested:
            job.status = "terminated"
            job.finished_at = time.time()
            should_skip = True
        else:
            job.status = "running"
            job.thread_name = threading.current_thread().name
            job.started_at = time.time()
            job.last_output_at = job.started_at
            should_skip = False
    if should_skip:
        append_runtime_log(job, "worker skipped because termination was already requested")
        return
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
            "FINAL_QUALITY_MODE": "rule",
            "FINAL_QUALITY_MAX_ITERATIONS": str(options["max_iterations"]),
            "REPORT_AGENT_QUALITY_ENABLED": "1" if options["enable_quality_loop"] else "0",
            "REPORT_AGENT_QUALITY_MAX_ROUNDS": str(options["max_iterations"]),
            "REPORT_AGENT_QUALITY_RETRY_ON_MINOR": "1" if options["retry_on_minor"] else "0",
            "REPORT_AGENT_QUALITY_MAX_FEEDBACK_QUERIES": str(options["feedback_queries"]),
            "QUALITY_FEEDBACK_SEARCH_BACKEND": str(options["quality_feedback_search_backend"]),
            "REPORT_AGENT_EVIDENCE_MODE": str(options["evidence_mode"]),
            "REPORT_AGENT_QUALITY_CHECK_SCOPE": "acceptance",
            "INSPECTION_MODE": "rule_only",
        }
    )
    apply_user_env(job, env, options)
    command = [sys.executable, "-u", str(RUNNER), job.product_description]
    append_log(job, "$ " + " ".join(command))
    append_runtime_log(job, "launch main workflow process")
    try:
        if job.terminate_requested:
            with JOBS_LOCK:
                job.status = "terminated"
                job.finished_at = time.time()
            append_runtime_log(job, "workflow terminated before process launch")
            return
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
        with JOBS_LOCK:
            job.process = process
            job.process_pid = process.pid
            job.process_stdin = process.stdin
            should_stop_after_launch = job.terminate_requested
        append_runtime_log(job, f"process started pid={process.pid}")
        if should_stop_after_launch:
            terminate_process_tree(process)
            with JOBS_LOCK:
                job.status = "terminated"
                job.finished_at = time.time()
                job.process = None
                job.process_stdin = None
                job.waiting_for_selection = False
            append_runtime_log(job, "workflow terminated immediately after process launch")
            return
        append_runtime_log(job, "stdin product selection deferred until candidates are chosen")
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
        if job.terminate_requested:
            job.status = "terminated"
        else:
            job.status = "completed" if job.return_code == 0 else "failed"
        job.process = None
        job.process_stdin = None
        job.waiting_for_selection = False
        append_runtime_log(job, f"process exited code={job.return_code}")
        if job.status == "completed":
            set_stage(job, "done")
        if job.status == "failed" and job.return_code != 0:
            job.error = f"process exited with code {job.return_code}"
    except Exception as exc:
        job.status = "terminated" if job.terminate_requested else "failed"
        job.finished_at = time.time()
        job.waiting_for_selection = False
        job.process = None
        job.process_stdin = None
        if job.status == "failed":
            job.error = str(exc)
            append_log(job, f"[backend-error] {exc}")
            append_runtime_log(job, f"backend exception: {exc}")
        else:
            append_runtime_log(job, "workflow terminated by user")


def terminate_job(job: Job) -> tuple[bool, str]:
    with JOBS_LOCK:
        if job.status not in {"queued", "running", "terminating"}:
            return False, f"job is not running: {job.status}"
        job.terminate_requested = True
        job.status = "terminating"
        job.waiting_for_selection = False
        process = job.process
        pid = job.process_pid
        stdin = job.process_stdin
        job.process_stdin = None
        job.stdin_closed = True

    append_log(job, "[web-input] 用户请求终止工作流")
    append_runtime_log(job, "terminate requested from web UI")

    if stdin is not None:
        try:
            stdin.close()
        except Exception:
            pass

    if process is None and not pid:
        with JOBS_LOCK:
            job.status = "terminated"
            job.finished_at = time.time()
        mark_running_subtasks(job, "terminated")
        append_runtime_log(job, "workflow terminated before process start")
        return True, ""

    try:
        if os.name == "nt" and pid:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
            )
        elif process is not None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
    except Exception as exc:
        with JOBS_LOCK:
            job.error = str(exc)
        append_runtime_log(job, f"terminate warning: {exc}")
        return False, f"failed to terminate workflow: {exc}"

    mark_running_subtasks(job, "terminated")
    append_runtime_log(job, "terminate signal sent to workflow process tree")
    return True, ""


def terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    pid = process.pid
    if os.name == "nt" and pid:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
    else:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()


def submit_product_selection(job: Job, selection: str) -> tuple[bool, str]:
    with JOBS_LOCK:
        if job.status not in {"queued", "running"}:
            return False, "job is not running"
        if job.selection_submitted:
            return False, "selection already submitted"
        stdin = job.process_stdin
        if stdin is None or job.stdin_closed:
            return False, "workflow is not waiting for product selection"
        job.manual_product_selection = selection
        job.selection_submitted = True
        job.waiting_for_selection = False
        job.stdin_closed = True
    try:
        stdin.write(selection + "\n")
        stdin.flush()
        stdin.close()
    except Exception as exc:
        with JOBS_LOCK:
            job.selection_submitted = False
            job.waiting_for_selection = True
            job.stdin_closed = False
            job.error = str(exc)
        return False, f"failed to submit selection: {exc}"
    append_log(job, f"[web-input] 产品选择: {selection}")
    append_runtime_log(job, f"stdin product selection sent: {selection}")
    return True, ""


def apply_user_env(job: Job, env: dict[str, str], options: dict[str, Any]) -> None:
    llm_model, llm_model_warning = sanitize_llm_model(
        options["llm_model"],
        options["ark_api_key"],
    )
    provider = options["llm_provider"] or DEFAULT_LLM_PROVIDER
    env["LLM_PROVIDER"] = provider

    if provider == "0":
        env["ARK_API_KEY"] = options["ark_api_key"] or DEFAULT_ARK_API_KEY
        env["LLM0_API_KEY"] = options["ark_api_key"] or DEFAULT_ARK_API_KEY
        env["LLM0_BASE_URL"] = options["llm_base_url"] or DEFAULT_ARK_BASE_URL
        env["LLM0_MODEL"] = llm_model or DEFAULT_ARK_MODEL
        env["LLM_BASE_URL"] = options["llm_base_url"] or DEFAULT_ARK_BASE_URL
        env["LLM_MODEL"] = llm_model or DEFAULT_ARK_MODEL
    else:
        if options["ark_api_key"]:
            env["ARK_API_KEY"] = options["ark_api_key"]
            env["LLM_API_KEY"] = options["ark_api_key"]
            env["LLM0_API_KEY"] = options["ark_api_key"]
        if options["llm_base_url"]:
            env["LLM_BASE_URL"] = options["llm_base_url"]
            env["LLM0_BASE_URL"] = options["llm_base_url"]
        if llm_model:
            env["LLM_MODEL"] = llm_model
            env["LLM0_MODEL"] = llm_model

    if llm_model_warning:
        append_log(job, f"[backend-warn] {llm_model_warning}")
        append_runtime_log(job, llm_model_warning)
    bocha_api_key = options["bocha_api_key"] or DEFAULT_BOCHA_API_KEY
    google_api_key = options["google_api_key"] or DEFAULT_GOOGLE_API_KEY
    google_cx_id = options["google_cx_id"] or DEFAULT_GOOGLE_CX_ID
    if bocha_api_key:
        env["BOCHA_API_KEY"] = bocha_api_key
    if google_api_key:
        env["GOOGLE_API_KEY"] = google_api_key
    if google_cx_id:
        env["GOOGLE_CX_ID"] = google_cx_id

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
            mark_waiting_for_selection(job)
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


def mark_waiting_for_selection(job: Job) -> None:
    with JOBS_LOCK:
        if (
            job.status == "running"
            and job.candidate_products
            and not job.selection_submitted
            and not job.stdin_closed
        ):
            job.waiting_for_selection = True
            if not job.selection_prompt_logged:
                job.selection_prompt_logged = True
                job.runtime_logs.append(
                    f"{time.strftime('%H:%M:%S')} waiting for web product selection"
                )
    set_stage(job, "select")


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
        if is_report_markdown_path(path)
    ]
    reports = sorted(reports, key=lambda path: path.stat().st_mtime, reverse=True)
    return [
        {
            "name": report_display_name(path),
            "path": str(path),
            "modified_at": path.stat().st_mtime,
            "size": path.stat().st_size,
            "summary": summarize_report(path, include_issues=False),
        }
        for path in reports[:200]
    ]


def report_paths_for_issue_scan() -> list[Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_paths = [
        path
        for path in REPORT_DIR.rglob("*.md")
        if is_report_markdown_path(path)
    ]
    return sorted(report_paths, key=lambda path: path.stat().st_mtime, reverse=True)[:200]


def is_report_markdown_path(path: Path) -> bool:
    try:
        parts = path.relative_to(REPORT_DIR).parts
    except ValueError:
        return False
    excluded_roots = {"web_inputs", "skill_wikis", "skill_wiki"}
    return bool(parts) and parts[0] not in excluded_roots


def list_questionnaire_files() -> list[dict[str, Any]]:
    QUESTIONNAIRE_DIR.mkdir(parents=True, exist_ok=True)
    files = [
        path
        for path in QUESTIONNAIRE_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in {".jsonl", ".csv", ".md"}
    ]
    files = sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)
    return [questionnaire_file_info(path) for path in files[:300]]


def questionnaire_file_info(path: Path) -> dict[str, Any]:
    return {
        "name": questionnaire_display_name(path),
        "path": str(path),
        "title": questionnaire_file_title(path),
        "kind": questionnaire_file_kind(path),
        "kind_label": questionnaire_file_kind_label(questionnaire_file_kind(path)),
        "modified_at": path.stat().st_mtime,
        "size": path.stat().st_size,
        "record_count": questionnaire_file_record_count(path),
    }


def questionnaire_display_name(path: Path) -> str:
    try:
        return path.relative_to(QUESTIONNAIRE_DIR).as_posix()
    except ValueError:
        return path.name


def questionnaire_file_kind(path: Path) -> str:
    name = path.name.lower()
    if name.endswith("_responses.jsonl"):
        return "response_jsonl"
    if name.endswith("_responses.csv"):
        return "response_csv"
    if name.endswith("_analysis.md"):
        return "analysis"
    if name.endswith(".jsonl"):
        return "questionnaire"
    if name.endswith(".csv"):
        return "response_csv"
    if name.endswith(".md"):
        return "analysis"
    return "file"


def questionnaire_file_kind_label(kind: str) -> str:
    return {
        "questionnaire": "问卷",
        "response_jsonl": "回答 JSONL",
        "response_csv": "回答 CSV",
        "analysis": "分析报告",
    }.get(kind, "文件")


def questionnaire_file_title(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"^\d{8}_\d{6}_", "", stem)
    stem = re.sub(r"_responses$", "", stem)
    stem = re.sub(r"_analysis$", "", stem)
    title = re.sub(r"_+", " ", stem).strip()
    return title or path.stem


def questionnaire_file_record_count(path: Path) -> int:
    suffix = path.suffix.lower()
    try:
        if suffix == ".jsonl":
            with path.open("r", encoding="utf-8", errors="replace") as file:
                return sum(1 for line in file if line.strip())
        if suffix == ".csv":
            with path.open("r", encoding="utf-8-sig", errors="replace") as file:
                rows = sum(1 for line in file if line.strip())
            return max(0, rows - 1)
    except OSError:
        return 0
    return 0


def safe_questionnaire_path(name: str) -> Path | None:
    name = str(name or "").strip().replace("\\", "/")
    if not name:
        return None
    path = (QUESTIONNAIRE_DIR / name).resolve()
    root = QUESTIONNAIRE_DIR.resolve()
    if root not in path.parents and path != root:
        return None
    if path == root or path.is_dir():
        return None
    return path


def generate_questionnaire_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    product_description = str(payload.get("product_description") or "").strip()
    if not product_description:
        raise RuntimeError("产品/竞品方向不能为空")
    own_param_text = truncate_text(
        str(payload.get("own_param_text") or ""),
        clamp_int(payload.get("own_param_max_chars"), 0, 100000, 12000),
    )
    manual_competitors = parse_name_list(payload.get("competitor_names"))
    skip_search = bool(payload.get("skip_search", False))

    with QUESTIONNAIRE_LOCK:
        warning = apply_questionnaire_config(payload)
        if skip_search:
            product_names = manual_competitors
            search_results = []
            queries = []
        else:
            search_result = questionnaire_flow.find_competitors(product_description)
            product_names = unique_names(
                manual_competitors + list(getattr(search_result, "product_names", []) or [])
            )
            search_results = list(getattr(search_result, "search_results", []) or [])
            queries = list(getattr(search_result, "queries", []) or [])
        items = questionnaire_flow.generate_questionnaire(
            product_description=product_description,
            own_param_text=own_param_text,
            competitor_names=product_names,
            search_results=search_results,
        )
        if not items:
            raise RuntimeError("模型没有生成有效问卷题目")
        output_path = questionnaire_flow.write_jsonl(items, product_description)

    return {
        "questionnaire": questionnaire_file_info(output_path),
        "items": items,
        "competitors": product_names,
        "queries": queries,
        "warning": warning,
        "files": list_questionnaire_files(),
    }


def simulate_questionnaire_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    questionnaire_path = questionnaire_path_from_payload(payload, "questionnaire_name")
    product_description = questionnaire_product_description(payload, questionnaire_path)
    own_param_text = truncate_text(
        str(payload.get("own_param_text") or ""),
        clamp_int(payload.get("own_param_max_chars"), 0, 100000, 12000),
    )
    competitor_names = parse_name_list(payload.get("competitor_names"))
    total_count = clamp_int(payload.get("simulated_count"), 1, 300, 25)

    with QUESTIONNAIRE_LOCK:
        warning = apply_questionnaire_config(payload)
        questionnaire_flow.SIMULATED_RESPONSE_COUNT = total_count
        items = questionnaire_flow.normalize_questionnaire_items(
            questionnaire_flow.read_jsonl(questionnaire_path)
        )
        if not items:
            raise RuntimeError("问卷文件没有有效题目")
        responses = questionnaire_flow.simulate_responses(
            product_description=product_description,
            own_param_text=own_param_text,
            competitor_names=competitor_names,
            questionnaire_items=items,
            total_count=total_count,
        )
        response_jsonl_path = questionnaire_flow.write_response_jsonl(
            responses,
            product_description,
        )
        response_csv_path = questionnaire_flow.write_response_csv(
            responses,
            items,
            product_description,
        )

    return {
        "questionnaire": questionnaire_file_info(questionnaire_path),
        "response_jsonl": questionnaire_file_info(response_jsonl_path),
        "response_csv": questionnaire_file_info(response_csv_path),
        "response_count": len(responses),
        "responses_preview": responses[:5],
        "warning": warning,
        "files": list_questionnaire_files(),
    }


def analyze_questionnaire_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    questionnaire_path = questionnaire_path_from_payload(payload, "questionnaire_name")
    responses_path = questionnaire_path_from_payload(payload, "responses_name")
    if questionnaire_file_kind(responses_path) != "response_jsonl":
        raise RuntimeError("问卷分析请选择 responses.jsonl 文件")
    product_description = questionnaire_product_description(payload, questionnaire_path)

    with QUESTIONNAIRE_LOCK:
        warning = apply_questionnaire_config(payload)
        items = questionnaire_flow.normalize_questionnaire_items(
            questionnaire_flow.read_jsonl(questionnaire_path)
        )
        responses = questionnaire_flow.read_jsonl(responses_path)
        if not items:
            raise RuntimeError("问卷文件没有有效题目")
        if not responses:
            raise RuntimeError("回答文件没有有效数据")
        code_analysis = questionnaire_flow.build_code_analysis(items, responses)
        analysis_markdown = questionnaire_flow.analyze_survey_with_llm(
            product_description,
            items,
            responses,
            code_analysis,
        )
        analysis_path = questionnaire_flow.write_analysis_markdown(
            analysis_markdown,
            product_description,
            code_analysis,
        )

    return {
        "questionnaire": questionnaire_file_info(questionnaire_path),
        "responses": questionnaire_file_info(responses_path),
        "analysis": questionnaire_file_info(analysis_path),
        "analysis_markdown": analysis_markdown,
        "code_analysis": code_analysis,
        "warning": warning,
        "files": list_questionnaire_files(),
    }


def questionnaire_path_from_payload(payload: dict[str, Any], key: str) -> Path:
    name = str(payload.get(key) or payload.get(key.replace("_name", "_path")) or "").strip()
    path = safe_questionnaire_path(name)
    if not path or not path.exists():
        raise RuntimeError("问卷文件不存在")
    return path


def questionnaire_product_description(payload: dict[str, Any], questionnaire_path: Path) -> str:
    value = str(payload.get("product_description") or "").strip()
    if value:
        return value
    return questionnaire_file_title(questionnaire_path)


def apply_questionnaire_config(payload: dict[str, Any]) -> str:
    provider = clamp_int(payload.get("llm_provider"), 0, 2, int(DEFAULT_LLM_PROVIDER))
    api_key = str(payload.get("ark_api_key") or DEFAULT_ARK_API_KEY or "").strip()
    base_url = str(payload.get("llm_base_url") or "").strip()
    llm_model, llm_model_warning = sanitize_llm_model(
        str(payload.get("llm_model") or ""),
        api_key,
    )

    questionnaire_flow.LLM_PROVIDER = provider
    if provider == 0:
        questionnaire_flow.LLM0_API_KEY = api_key or DEFAULT_ARK_API_KEY
        questionnaire_flow.LLM0_BASE_URL = base_url or DEFAULT_ARK_BASE_URL
        questionnaire_flow.LLM0_MODEL = llm_model or DEFAULT_ARK_MODEL
    elif provider == 1:
        questionnaire_flow.LLM1_API_KEY = api_key or questionnaire_flow.LLM1_API_KEY
        if base_url:
            questionnaire_flow.LLM1_BASE_URL = base_url
        if llm_model:
            questionnaire_flow.LLM1_MODEL = llm_model
    else:
        questionnaire_flow.LLM2_API_KEY = api_key or questionnaire_flow.LLM2_API_KEY
        if base_url:
            questionnaire_flow.LLM2_BASE_URL = base_url
        if llm_model:
            questionnaire_flow.LLM2_MODEL = llm_model

    questionnaire_flow.BOCHA_API_KEY = str(
        payload.get("bocha_api_key") or DEFAULT_BOCHA_API_KEY or questionnaire_flow.BOCHA_API_KEY or ""
    ).strip()
    questionnaire_flow.GOOGLE_API_KEY = str(
        payload.get("google_api_key") or DEFAULT_GOOGLE_API_KEY or questionnaire_flow.GOOGLE_API_KEY or ""
    ).strip()
    questionnaire_flow.GOOGLE_CX_ID = str(
        payload.get("google_cx_id") or DEFAULT_GOOGLE_CX_ID or questionnaire_flow.GOOGLE_CX_ID or ""
    ).strip()
    questionnaire_flow.SEARCH_SOURCE = str(
        payload.get("questionnaire_search_source")
        or payload.get("search_source")
        or questionnaire_flow.SEARCH_SOURCE
        or "bocha"
    ).strip().lower()
    questionnaire_flow.QUERY_COUNT = clamp_int(payload.get("query_count"), 1, 10, questionnaire_flow.QUERY_COUNT)
    questionnaire_flow.SEARCH_COUNT = clamp_int(payload.get("search_count"), 1, 20, questionnaire_flow.SEARCH_COUNT)
    questionnaire_flow.COMPETITOR_LIMIT = clamp_int(
        payload.get("competitor_limit") or payload.get("top_n"),
        1,
        30,
        questionnaire_flow.COMPETITOR_LIMIT,
    )
    questionnaire_flow.QUESTION_COUNT = clamp_int(payload.get("question_count"), 3, 80, questionnaire_flow.QUESTION_COUNT)
    questionnaire_flow.SIMULATED_RESPONSE_COUNT = clamp_int(
        payload.get("simulated_count"),
        1,
        300,
        questionnaire_flow.SIMULATED_RESPONSE_COUNT,
    )
    questionnaire_flow.SIMULATION_BATCH_SIZE = clamp_int(
        payload.get("simulation_batch_size"),
        1,
        30,
        questionnaire_flow.SIMULATION_BATCH_SIZE,
    )
    questionnaire_flow.MAX_SEARCH_EVIDENCE_CHARS = clamp_int(
        payload.get("max_search_evidence_chars"),
        1000,
        100000,
        questionnaire_flow.MAX_SEARCH_EVIDENCE_CHARS,
    )
    questionnaire_flow.OWN_PRODUCT_PARAM_MAX_CHARS = clamp_int(
        payload.get("own_param_max_chars"),
        0,
        100000,
        questionnaire_flow.OWN_PRODUCT_PARAM_MAX_CHARS,
    )
    questionnaire_flow.LLM_TIMEOUT = clamp_int(
        payload.get("llm_timeout"),
        30,
        1800,
        questionnaire_flow.LLM_TIMEOUT,
    )
    return llm_model_warning


def truncate_text(value: str, max_chars: int) -> str:
    text = str(value or "")
    if max_chars and len(text) > max_chars:
        return text[:max_chars]
    return text


def parse_name_list(value: Any) -> list[str]:
    if isinstance(value, list):
        parts = [str(item).strip() for item in value]
    else:
        parts = re.split(r"[,，、;\n]+", str(value or ""))
    return unique_names([part.strip() for part in parts if part and part.strip()])


def unique_names(values: list[str]) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for value in values:
        name = str(value or "").strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return names


def build_skill_wiki_from_report(payload: dict[str, Any]) -> dict[str, Any]:
    marker = str(payload.get("marker", SKILL_WIKI_MARKER))
    report_bundle = skill_report_bundle_from_payload(payload, marker=marker)
    article = report_bundle["article"]
    source_label = report_bundle["source_label"]
    report_summary = report_bundle["summary"]
    primary_path = report_bundle["primary_path"]
    skill_name = str(
        payload.get("skill_name")
        or report_summary.get("title")
        or primary_path.stem
    ).strip()
    skill_id = sanitize_skill_id(skill_name) or sanitize_skill_id(primary_path.stem)
    output_dir = safe_skill_wiki_write_path(skill_id)
    if not output_dir:
        raise RuntimeError("invalid skill name")

    domain = str(payload.get("domain") or "").strip()
    llm_config = skill_llm_config_from_payload(payload)
    if not article.strip():
        raise RuntimeError("selected report has no readable article content")

    existing_files = read_existing_wiki(output_dir)
    article_notes = prepare_article_notes(
        article=article,
        existing_files=existing_files,
        output_dir=output_dir,
        domain=domain,
        chunk_chars=clamp_int(payload.get("chunk_chars"), 4000, 100000, 24000),
        chunk_overlap=clamp_int(payload.get("chunk_overlap"), 0, 20000, 1200),
        chunk_workers=clamp_int(payload.get("chunk_workers"), 1, 8, 4),
        max_existing_chars=clamp_int(payload.get("max_existing_chars"), 1000, 200000, 80000),
        temperature=float_value(payload.get("temperature"), 0.2),
        timeout=clamp_int(payload.get("timeout"), 30, 1800, 300),
        llm_config=llm_config,
    )
    wiki_payload = call_wiki_llm(
        article_notes=article_notes,
        existing_files=existing_files,
        output_dir=output_dir,
        domain=domain,
        max_notes_chars=clamp_int(payload.get("max_notes_chars"), 1000, 300000, 120000),
        max_existing_chars=clamp_int(payload.get("max_existing_chars"), 1000, 200000, 80000),
        temperature=float_value(payload.get("temperature"), 0.2),
        timeout=clamp_int(payload.get("timeout"), 30, 1800, 300),
        llm_config=llm_config,
    )
    written = apply_wiki_payload(wiki_payload, output_dir)
    written.extend(
        write_source_memory_files(
            article=article,
            article_notes=article_notes,
            output_dir=output_dir,
            source_label=source_label,
        )
    )
    update_skill_wiki_manifest(
        output_dir=output_dir,
        skill_id=skill_id,
        skill_name=skill_name,
        source_report=source_label,
        domain=domain,
        written=written,
    )
    detail = skill_wiki_detail(skill_id, include_docs=True)
    if not detail:
        raise RuntimeError("skill wiki was written but cannot be loaded")
    return detail


def skill_report_bundle_from_payload(
    payload: dict[str, Any],
    *,
    marker: str,
) -> dict[str, Any]:
    task_id = str(payload.get("task_id") or "").strip()
    report_name = str(payload.get("report_name") or "").strip()
    report_path = safe_report_path(report_name) if report_name else None
    if report_path and report_path.exists() and is_report_markdown_path(report_path):
        task_id = task_id or task_id_for_report(report_path)
    if not task_id:
        raise RuntimeError("请选择报告任务")

    final_path, agent_path = skill_source_reports_for_task(task_id)
    final_summary = summarize_report(final_path, include_issues=False)
    agent_summary = summarize_report(agent_path, include_issues=False)
    article_parts = [
        "# Skill 来源报告包",
        "",
        f"- 任务: {task_id}",
        f"- 最终报告: {report_display_name(final_path)}",
        f"- 分析总报告: {report_display_name(agent_path)}",
        "",
        "## 最终报告",
        "",
        extract_article(final_path, marker=marker),
        "",
        "## 分析总报告",
        "",
        extract_article(agent_path, marker=marker),
        "",
    ]
    title = final_summary.get("title") or agent_summary.get("title") or task_id
    return {
        "article": "\n".join(article_parts).strip(),
        "source_label": (
            f"{task_id} · {title} · 最终报告+分析总报告"
        ),
        "summary": final_summary,
        "primary_path": final_path,
        "final_path": final_path,
        "agent_path": agent_path,
    }


def skill_source_reports_for_task(task_id: str) -> tuple[Path, Path]:
    task_id = str(task_id or "").strip()
    if not re.match(r"^\d{8}_\d{6}$", task_id):
        raise RuntimeError("invalid report task")
    task_dir = (REPORT_DIR / task_id).resolve()
    report_root = REPORT_DIR.resolve()
    if report_root not in task_dir.parents and task_dir != report_root:
        raise RuntimeError("invalid report task")
    if not task_dir.exists() or not task_dir.is_dir():
        raise RuntimeError("report task not found")

    report_paths = [
        path
        for path in task_dir.glob("*.md")
        if path.is_file() and is_report_markdown_path(path)
    ]
    final_paths = [path for path in report_paths if report_type_for(path) == "final"]
    agent_paths = [path for path in report_paths if report_type_for(path) == "report_agent"]
    if not final_paths or not agent_paths:
        raise RuntimeError("生成 Skill 需要同一任务下同时存在最终报告和分析总报告")
    final_path = max(final_paths, key=lambda path: path.stat().st_mtime)
    agent_path = max(agent_paths, key=lambda path: path.stat().st_mtime)
    return final_path, agent_path


def answer_skill_wiki(payload: dict[str, Any]) -> dict[str, Any]:
    skill_id = str(payload.get("skill_id") or "").strip()
    question = str(payload.get("question") or "").strip()
    if not question:
        raise RuntimeError("question is required")
    wiki_dir = safe_skill_wiki_read_path(skill_id)
    if not wiki_dir or not wiki_dir.exists():
        raise RuntimeError("skill wiki not found")
    docs = load_wiki_docs(wiki_dir)
    if not docs:
        raise RuntimeError("skill wiki has no readable docs")
    answer = ask_wiki(
        docs=docs,
        question=question,
        domain_hints=str(payload.get("domain_hints") or ""),
        max_context_chars=clamp_int(payload.get("max_context_chars"), 1000, 200000, 120000),
        temperature=float_value(payload.get("temperature"), 0.2),
        timeout=clamp_int(payload.get("timeout"), 30, 1800, 180),
        debug_context=False,
        llm_config=skill_llm_config_from_payload(payload),
    )
    return {
        "answer": answer,
        "skill_id": skill_id,
        "docs_loaded": len(docs),
    }


def list_skill_wikis() -> list[dict[str, Any]]:
    return [
        detail
        for detail in (
            skill_wiki_detail(skill_id, include_docs=False)
            for skill_id, _path in skill_wiki_dirs()
        )
        if detail
    ]


def skill_wiki_detail(skill_id: str, *, include_docs: bool) -> dict[str, Any] | None:
    wiki_dir = safe_skill_wiki_read_path(skill_id)
    if not wiki_dir or not wiki_dir.exists():
        return None
    docs = load_wiki_docs(wiki_dir)
    if not docs and not (wiki_dir / "SKILL.md").exists():
        return None
    manifest = load_skill_manifest(wiki_dir)
    modified_at = max(
        (path.stat().st_mtime for path in wiki_dir.rglob("*") if path.is_file()),
        default=wiki_dir.stat().st_mtime,
    )
    resolved_id = skill_id_for_path(wiki_dir)
    detail: dict[str, Any] = {
        "id": resolved_id,
        "name": manifest.get("skill_name") or wiki_dir.name,
        "path": str(wiki_dir),
        "relative_path": skill_wiki_display_path(wiki_dir),
        "source_report": manifest.get("source_report", ""),
        "domain": manifest.get("domain", ""),
        "modified_at": modified_at,
        "file_count": len(docs),
        "summary": manifest.get("summary", ""),
        "files": [
            {
                "path": doc["path"],
                "chars": len(doc["content"]),
                "preview": doc["content"][:500],
            }
            for doc in docs
        ],
    }
    if include_docs:
        detail["docs"] = [
            {
                "path": doc["path"],
                "content": doc["content"][:skill_doc_content_limit(doc["path"])],
                "chars": len(doc["content"]),
            }
            for doc in docs
        ]
    return detail


def skill_doc_content_limit(path: str) -> int:
    lower = path.lower()
    if lower.endswith("source_report_full.md") or lower.endswith("source_report_tables.md"):
        return 120000
    if lower.endswith("source_chunk_facts_and_gaps.md"):
        return 60000
    return 30000


def skill_wiki_dirs() -> list[tuple[str, Path]]:
    items: list[tuple[str, Path]] = []
    if SKILL_WIKI_ROOT.exists():
        for path in sorted(SKILL_WIKI_ROOT.iterdir(), key=lambda item: item.name.lower()):
            if path.is_dir() and is_skill_wiki_dir(path):
                items.append((path.name, path.resolve()))
    if LEGACY_SKILL_WIKI_DIR.exists() and is_skill_wiki_dir(LEGACY_SKILL_WIKI_DIR):
        items.append(("__legacy_skill_wiki", LEGACY_SKILL_WIKI_DIR.resolve()))
    items.sort(key=lambda item: item[1].stat().st_mtime, reverse=True)
    return items


def is_skill_wiki_dir(path: Path) -> bool:
    if (path / "SKILL.md").exists():
        return True
    return any(
        child.is_file() and child.suffix.lower() in {".md", ".txt", ".json"}
        for child in path.rglob("*")
        if "_build" not in child.relative_to(path).parts
    )


def safe_skill_wiki_write_path(skill_id: str) -> Path | None:
    skill_id = sanitize_skill_id(skill_id)
    if not skill_id:
        return None
    candidate = (SKILL_WIKI_ROOT / skill_id).resolve()
    root = SKILL_WIKI_ROOT.resolve()
    if root not in candidate.parents and candidate != root:
        return None
    return candidate


def safe_skill_wiki_read_path(skill_id: str) -> Path | None:
    if skill_id == "__legacy_skill_wiki":
        return LEGACY_SKILL_WIKI_DIR.resolve()
    return safe_skill_wiki_write_path(skill_id)


def sanitize_skill_id(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("._-")
    return text[:80]


def skill_id_for_path(path: Path) -> str:
    if path.resolve() == LEGACY_SKILL_WIKI_DIR.resolve():
        return "__legacy_skill_wiki"
    return path.name


def skill_wiki_display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPORT_DIR.resolve()).as_posix()
    except ValueError:
        return path.name


def load_skill_manifest(wiki_dir: Path) -> dict[str, Any]:
    path = wiki_dir / "wiki_manifest.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def update_skill_wiki_manifest(
    *,
    output_dir: Path,
    skill_id: str,
    skill_name: str,
    source_report: str,
    domain: str,
    written: list[Path],
) -> None:
    manifest = load_skill_manifest(output_dir)
    manifest.update(
        {
            "skill_id": skill_id,
            "skill_name": skill_name,
            "source_report": source_report,
            "domain": domain,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": [path.relative_to(output_dir).as_posix() for path in written],
        }
    )
    (output_dir / "wiki_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def skill_llm_config_from_payload(payload: dict[str, Any]) -> tuple[str, str, str]:
    provider = str(payload.get("llm_provider") or os.getenv("LLM_PROVIDER") or DEFAULT_LLM_PROVIDER)
    raw_key = str(payload.get("ark_api_key") or "").strip()
    raw_base = str(payload.get("llm_base_url") or "").strip()
    model, _warning = sanitize_llm_model(str(payload.get("llm_model") or ""), raw_key)
    if provider == "0":
        return (
            raw_key or os.getenv("REPORT_LLM_API_KEY") or os.getenv("LLM0_API_KEY") or os.getenv("ARK_API_KEY") or DEFAULT_ARK_API_KEY,
            raw_base or os.getenv("REPORT_LLM_BASE_URL") or os.getenv("LLM0_BASE_URL") or DEFAULT_ARK_BASE_URL,
            model or os.getenv("REPORT_LLM_MODEL") or os.getenv("LLM0_MODEL") or DEFAULT_ARK_MODEL,
        )
    if provider == "1":
        return (
            raw_key or os.getenv("REPORT_LLM_API_KEY") or os.getenv("LLM_API_KEY", ""),
            raw_base or os.getenv("REPORT_LLM_BASE_URL") or os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1/chat/completions"),
            model or os.getenv("REPORT_LLM_MODEL") or os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
        )
    if provider == "2":
        return (
            raw_key or os.getenv("REPORT_LLM_API_KEY") or os.getenv("LLM2_API_KEY") or os.getenv("MIMO_API_KEY", ""),
            raw_base or os.getenv("REPORT_LLM_BASE_URL") or os.getenv("LLM2_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1"),
            model or os.getenv("REPORT_LLM_MODEL") or os.getenv("LLM2_MODEL", "mimo-v2.5-pro"),
        )
    raise RuntimeError(f"unsupported LLM provider: {provider}")


def float_value(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def list_issue_groups() -> list[dict[str, Any]]:
    quality_paths = quality_report_paths_for_issue_scan()
    quality_task_ids = {task_id_for_report(path) for path in quality_paths}
    report_paths = report_paths_for_issue_scan()
    title_by_task = report_display_titles_by_task(report_paths)
    quality_groups = list_quality_issue_groups(quality_paths, title_by_task) if quality_paths else []

    groups: dict[str, dict[str, Any]] = {}
    for path in report_paths:
        if task_id_for_report(path) in quality_task_ids:
            continue
        summary = summarize_report(path, include_issues=False)
        issue_count = summary["issue_count"]
        if not issue_count:
            continue
        task_id = summary["task_id"]
        group = groups.setdefault(
            task_id,
            {
                "taskId": task_id,
                "displayTitle": title_by_task.get(task_id, task_id),
                "modifiedAt": 0,
                "issueCount": 0,
                "reportCount": 0,
                "typeCounts": {},
            },
        )
        group["modifiedAt"] = max(group["modifiedAt"], path.stat().st_mtime)
        group["issueCount"] += issue_count
        group["reportCount"] += 1
        label = report_type_label(summary["type"])
        group["typeCounts"][label] = group["typeCounts"].get(label, 0) + issue_count
    return sorted(
        [*quality_groups, *groups.values()],
        key=lambda item: item["modifiedAt"],
        reverse=True,
    )


def report_display_titles_by_task(paths: list[Path]) -> dict[str, str]:
    priority = {"final": 0, "report_agent": 1, "single": 2, "quality": 3}
    candidates: dict[str, tuple[int, float, str]] = {}
    for path in paths:
        task_id = task_id_for_report(path)
        if not task_id:
            continue
        summary = summarize_report(path, include_issues=False)
        rank = priority.get(str(summary.get("type") or ""), 9)
        item = (rank, -path.stat().st_mtime, str(summary.get("title") or task_id))
        current = candidates.get(task_id)
        if current is None or item < current:
            candidates[task_id] = item
    return {task_id: item[2] for task_id, item in candidates.items()}


def list_issues(task_id: str = "") -> list[dict[str, Any]]:
    quality_paths = quality_report_paths_for_issue_scan(task_id)
    quality_task_ids = {task_id_for_report(path) for path in quality_paths}
    issues = list_quality_issues(quality_paths) if quality_paths else []

    report_paths = report_paths_for_issue_scan()
    report_names = {report_display_name(path) for path in report_paths[:200]}
    for path in report_paths:
        if task_id and task_id_for_report(path) != task_id:
            continue
        if task_id_for_report(path) in quality_task_ids:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        summary = summarize_report(path, text, include_issues=True)
        report_name = report_display_name(path)
        for issue in summary["issues"]:
            issues.append(
                {
                    "taskId": summary["task_id"],
                    "report": report_name,
                    "reportTitle": summary["title"],
                    "reportType": report_type_label(summary["type"]),
                    "modifiedAt": path.stat().st_mtime,
                    "sourceExists": report_name in report_names,
                    "title": issue.get("title") or summary["title"],
                    "detail": issue.get("detail") or "",
                    "reason": issue.get("reason") or "",
                    "evidence": issue.get("evidence") or "",
                    "suggestion": issue.get("suggestion") or "",
                    "severity": issue.get("severity") or "medium",
                    "lineNumber": issue.get("line_number") or 0,
                    "section": issue.get("section") or "",
                    "context": issue.get("context") or "",
                }
            )
    return issues


def list_quality_issue_groups(
    quality_paths: list[Path],
    title_by_task: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    title_by_task = title_by_task or {}
    groups: dict[str, dict[str, Any]] = {}
    for path in quality_paths:
        data = load_quality_report_json(path)
        payloads = quality_issue_payloads(path, data)
        issue_count = len(payloads)
        if not issue_count:
            continue
        task_id = quality_task_id_for_report(path, data)
        group = groups.setdefault(
            task_id,
            {
                "taskId": task_id,
                "displayTitle": title_by_task.get(task_id, task_id),
                "modifiedAt": 0,
                "issueCount": 0,
                "reportCount": 0,
                "typeCounts": {},
            },
        )
        group["modifiedAt"] = max(group["modifiedAt"], path.stat().st_mtime)
        group["issueCount"] += issue_count
        group["reportCount"] += 1
        label = report_type_label("quality")
        group["typeCounts"][label] = group["typeCounts"].get(label, 0) + issue_count
    return sorted(groups.values(), key=lambda item: item["modifiedAt"], reverse=True)


def list_quality_issues(quality_paths: list[Path]) -> list[dict[str, Any]]:
    report_names = {report_display_name(path) for path in report_paths_for_issue_scan()}
    issues: list[dict[str, Any]] = []
    for quality_path in quality_paths:
        data = load_quality_report_json(quality_path)
        task_id = quality_task_id_for_report(quality_path, data)
        source_path = quality_source_report_path(quality_path, data)
        source_exists = bool(source_path and source_path.exists())
        report_name = report_display_name(source_path) if source_path else ""
        if source_path and source_path.exists():
            summary = summarize_report(source_path, include_issues=False)
            modified_at = source_path.stat().st_mtime
        else:
            summary = {
                "title": str(data.get("source_report") or quality_path.stem),
                "type": "quality",
            }
            modified_at = quality_path.stat().st_mtime
        for issue in quality_issue_payloads(quality_path, data):
            issues.append(
                {
                    "taskId": task_id,
                    "report": report_name,
                    "reportTitle": summary["title"],
                    "reportType": report_type_label(summary["type"]),
                    "modifiedAt": modified_at,
                    "sourceExists": source_exists and report_name in report_names,
                    "title": issue.get("title") or summary["title"],
                    "detail": issue.get("detail") or "",
                    "reason": issue.get("reason") or "",
                    "evidence": issue.get("evidence") or "",
                    "suggestion": issue.get("suggestion") or "",
                    "severity": issue.get("severity") or "medium",
                    "lineNumber": issue.get("line_number") or 0,
                    "section": issue.get("section") or "",
                    "context": issue.get("context") or "",
                }
            )
    return issues


def summarize_report(
    path: Path,
    text: str | None = None,
    include_issues: bool = True,
) -> dict[str, Any]:
    text = text if text is not None else path.read_text(encoding="utf-8", errors="replace")
    title = path.stem
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    title = display_report_title(title, text)
    report_type = report_type_for(path)
    quality_issues = quality_issues_for_report(path, report_type)
    issues = quality_issues if include_issues and quality_issues else []
    if include_issues and not issues:
        issues = extract_issues(text)
    issue_count = len(issues) if include_issues else (
        len(quality_issues) if quality_issues else count_issue_lines(text)
    )
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
        "issue_count": issue_count,
        "issues": issues,
    }


def display_report_title(title: str, text: str) -> str:
    subject = report_subject_from_markdown(text)
    if not subject:
        return title
    if title == "所选产品横向对比报告":
        return f"{subject}类似产品横向对比报告"
    if title.startswith("Report Agent 标准竞品分析报告"):
        return title.replace(
            "Report Agent 标准竞品分析报告",
            f"Report Agent 标准{subject}竞品分析报告",
            1,
        )
    return title


def report_subject_from_markdown(text: str) -> str:
    match = re.search(r"(?m)^原始需求[:：]\s*(.+?)\s*$", text)
    if not match:
        return ""
    return normalize_report_subject(match.group(1))


def normalize_report_subject(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.splitlines()[0].strip() if text else ""
    text = re.sub(r"^(?:请|帮我|请帮我|麻烦|需要|生成|做一份|做|分析|关于)+", "", text).strip()
    text = re.sub(
        r"(?:的)?(?:竞品分析报告|竞品对比报告|竞品分析|竞品对比|类似产品横向对比报告|横向对比报告|横向对比|类似产品|对比报告|分析报告|报告|推荐)$",
        "",
        text,
    ).strip(" ，,。；;：:")
    return text[:42].strip()


def quality_report_paths_for_issue_scan(task_id: str = "") -> list[Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    latest_by_task: dict[str, Path] = {}
    for path in REPORT_DIR.rglob("quality_report.json"):
        try:
            relative = path.relative_to(REPORT_DIR)
        except ValueError:
            continue
        if "web_inputs" in relative.parts:
            continue
        path_task_id = task_id_for_report(path)
        if task_id and path_task_id != task_id:
            continue
        current = latest_by_task.get(path_task_id)
        if current is None or path.stat().st_mtime > current.stat().st_mtime:
            latest_by_task[path_task_id] = path
    return sorted(latest_by_task.values(), key=lambda item: item.stat().st_mtime, reverse=True)


def latest_quality_report_json_for_task(task_id: str) -> Path | None:
    paths = quality_report_paths_for_issue_scan(task_id)
    return paths[0] if paths else None


def load_quality_report_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def quality_issues_for_report(path: Path, report_type: str = "") -> list[dict[str, Any]]:
    report_type = report_type or report_type_for(path)
    if report_type not in {"final", "report_agent", "quality"}:
        return []

    quality_path: Path | None = None
    if report_type == "quality":
        if path.name == "quality_report.md":
            quality_path = path.with_suffix(".json")
        else:
            candidate = path.parent / "quality_report.json"
            quality_path = candidate if candidate.exists() else None
    if quality_path is None:
        quality_path = latest_quality_report_json_for_task(task_id_for_report(path))
    if not quality_path or not quality_path.exists():
        return []
    return quality_issue_payloads(quality_path, load_quality_report_json(quality_path))


def quality_issue_payloads(quality_path: Path, data: dict[str, Any]) -> list[dict[str, Any]]:
    refreshed = refreshed_quality_section_issues(quality_path, data)
    if refreshed:
        return [quality_issue_to_payload(issue, quality_path) for issue in refreshed]

    raw_issues = data.get("issues")
    if not isinstance(raw_issues, list):
        return []
    payloads: list[dict[str, Any]] = []
    for raw_issue in raw_issues:
        if isinstance(raw_issue, dict):
            payloads.append(quality_issue_to_payload(raw_issue, quality_path))
    return payloads


def refreshed_quality_section_issues(
    quality_path: Path,
    data: dict[str, Any],
) -> list[dict[str, Any]]:
    source_path = quality_source_report_path(quality_path, data)
    if not source_path or not source_path.exists():
        return []
    try:
        markdown = source_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    analysis = ReportAnalysis(
        task_id=quality_task_id_for_report(quality_path, data),
        product_name="",
        evidence_list=[],
        claims=[],
        pm_insights=[],
        swot={},
        recommendations=[],
        report_markdown=markdown,
    )
    return [
        {
            "type": issue.type.value,
            "severity": issue.severity.value,
            "description": issue.description,
            "suggestion": issue.suggestion,
            "explanation": issue.explanation,
            "impact": issue.impact,
            "confidence": issue.confidence,
            "affected_fields": issue.affected_fields,
        }
        for issue in build_final_body_section_issues(analysis, [])
    ]


def quality_issue_to_payload(issue: dict[str, Any], quality_path: Path) -> dict[str, Any]:
    title = str(
        issue.get("description")
        or issue.get("suggestion")
        or issue.get("type")
        or "Quality Agent Issue"
    ).strip()
    suggestion = str(issue.get("suggestion") or title).strip()
    explanation = str(issue.get("explanation") or "").strip()
    impact = str(issue.get("impact") or "").strip()
    affected_fields = [
        str(item).strip()
        for item in issue.get("affected_fields", [])
        if str(item).strip()
    ]
    section = next(
        (item for item in affected_fields if item != "table_manual_search"),
        "",
    )
    context_parts = [
        f"Quality report: {report_display_name(quality_path)}",
    ]
    if explanation:
        context_parts.append(explanation)
    if impact:
        context_parts.append(impact)
    return {
        "severity": normalize_quality_severity(str(issue.get("severity") or "")),
        "title": title[:100],
        "detail": explanation or suggestion or title,
        "reason": impact or explanation,
        "evidence": ", ".join(affected_fields),
        "suggestion": suggestion or title,
        "line_number": 0,
        "section": section,
        "context": "\n".join(context_parts)[:1200],
    }


def normalize_quality_severity(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"critical", "high", "severe"}:
        return "high"
    if lowered in {"major", "medium"}:
        return "medium"
    if lowered in {"minor", "low", "info"}:
        return "low"
    return "medium"


def quality_task_id_for_report(path: Path, data: dict[str, Any]) -> str:
    task_id = task_id_for_report(path)
    if task_id:
        return task_id
    raw_task_id = str(data.get("task_id") or "")
    match = re.match(r"^(\d{8}_\d{6})", raw_task_id)
    return match.group(1) if match else raw_task_id


def quality_source_report_path(quality_path: Path, data: dict[str, Any]) -> Path | None:
    source_report = str(data.get("source_report") or "").strip()
    if source_report:
        direct = (REPORT_DIR / source_report).resolve()
        report_root = REPORT_DIR.resolve()
        if direct.exists() and (report_root in direct.parents or direct == report_root):
            return direct
        if source_report.lower().endswith(".md"):
            named = (REPORT_DIR / source_report).resolve()
            if named.exists() and (report_root in named.parents or named == report_root):
                return named

    task_id = task_id_for_report(quality_path)
    task_dir = REPORT_DIR / task_id
    candidates = [
        quality_path.parent / "report.md",
        task_dir / f"{task_id}_REPORT_AGENT_ANALYSIS.md",
        task_dir / f"{task_id}_FINAL_COMPARISON.md",
        quality_path.with_suffix(".md"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def report_type_label(report_type: str) -> str:
    if report_type == "quality":
        return "质检报告"
    if report_type == "final":
        return "最终报告"
    if report_type == "report_agent":
        return "分析总报告"
    return "单品报告"


def count_issue_lines(text: str) -> int:
    count = 0
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
            count += 1
    return count


def extract_issues(text: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    issue_block = False
    current_section = ""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            current_section = heading.group(2).strip()
        if re.match(r"^#{1,4}\s+.*(issue|问题|风险|缺口|不足|待修复)", stripped, re.I):
            issue_block = True
            continue
        if issue_block and stripped.startswith("#"):
            issue_block = False
        if not issue_block and not re.search(r"(issue|问题|风险|缺口|不足|待修复)", stripped, re.I):
            continue
        if stripped.startswith(("-", "*")) or re.match(r"^\d+[.)、]\s+", stripped):
            normalized = re.sub(r"^[-*\d.)、\s]+", "", stripped)
            issues.append(
                issue_to_payload(
                    normalized,
                    line_number=index + 1,
                    section=current_section,
                    context=context_snippet(lines, index),
                )
            )
    return issues


def context_snippet(lines: list[str], index: int, radius: int = 2) -> str:
    start = max(0, index - radius)
    end = min(len(lines), index + radius + 1)
    snippet = [line.strip() for line in lines[start:end] if line.strip()]
    return "\n".join(snippet)[:1200]


def issue_to_payload(
    value: str,
    line_number: int = 0,
    section: str = "",
    context: str = "",
) -> dict[str, Any]:
    severity = "medium"
    lowered = value.lower()
    if any(token in lowered for token in ("critical", "严重", "高风险", "major")):
        severity = "high"
    elif any(token in lowered for token in ("minor", "轻微", "low")):
        severity = "low"
    parts = split_issue_parts(value)
    return {
        "severity": severity,
        "title": parts["title"][:100],
        "detail": value,
        "reason": parts["reason"],
        "evidence": parts["evidence"],
        "suggestion": parts["suggestion"],
        "line_number": line_number,
        "section": section,
        "context": context,
    }


def split_issue_parts(value: str) -> dict[str, str]:
    markers = {
        "evidence": r"(?:证据|来源参考点|来源|参考点)[:：]\s*",
        "suggestion": r"(?:建议修正|修复要求|建议|运营动作|对\s*PM\s*的启发|对PM的启发)[:：]\s*",
        "reason": r"(?:原因|为什么重要|风险|影响)[:：]\s*",
    }
    first_marker = re.search(
        r"(?:证据|来源参考点|来源|参考点|建议修正|修复要求|建议|运营动作|对\s*PM\s*的启发|对PM的启发|原因|为什么重要|风险|影响)[:：]",
        value,
    )
    title = value[: first_marker.start()].strip(" ；;，,。") if first_marker else value

    def extract(marker: str) -> str:
        pattern = markers[marker]
        match = re.search(pattern, value)
        if not match:
            return ""
        rest = value[match.end() :]
        next_match = re.search(
            r"\s+(?:证据|来源参考点|来源|参考点|建议修正|修复要求|建议|运营动作|对\s*PM\s*的启发|对PM的启发|原因|为什么重要|风险|影响)[:：]",
            rest,
        )
        return rest[: next_match.start()].strip(" ；;，,。") if next_match else rest.strip()

    return {
        "title": title or value[:100],
        "reason": extract("reason"),
        "evidence": extract("evidence"),
        "suggestion": extract("suggestion"),
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
    if suffix == ".md":
        return "text/markdown; charset=utf-8"
    if suffix == ".jsonl":
        return "application/x-ndjson; charset=utf-8"
    if suffix == ".csv":
        return "text/csv; charset=utf-8"
    return "application/octet-stream"


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
    print(f"Web console: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
