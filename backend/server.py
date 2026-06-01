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
    waiting_for_selection: bool = False
    selection_submitted: bool = False
    stdin_closed: bool = False
    selection_prompt_logged: bool = False
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
        self._serve_static(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/jobs":
            self._handle_create_job()
            return
        if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/selection"):
            self._handle_product_selection(parsed.path)
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
        job.process_stdin = process.stdin
        append_runtime_log(job, f"process started pid={process.pid}")
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
        job.status = "completed" if job.return_code == 0 else "failed"
        job.process_stdin = None
        job.waiting_for_selection = False
        append_runtime_log(job, f"process exited code={job.return_code}")
        if job.status == "completed":
            set_stage(job, "done")
        if job.return_code != 0:
            job.error = f"process exited with code {job.return_code}"
    except Exception as exc:
        job.status = "failed"
        job.finished_at = time.time()
        job.waiting_for_selection = False
        job.process_stdin = None
        job.error = str(exc)
        append_log(job, f"[backend-error] {exc}")
        append_runtime_log(job, f"backend exception: {exc}")


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
        if "web_inputs" not in path.relative_to(REPORT_DIR).parts
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
        if "web_inputs" not in path.relative_to(REPORT_DIR).parts
    ]
    return sorted(report_paths, key=lambda path: path.stat().st_mtime, reverse=True)[:200]


def list_issue_groups() -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for path in report_paths_for_issue_scan():
        summary = summarize_report(path, include_issues=False)
        issue_count = summary["issue_count"]
        if not issue_count:
            continue
        task_id = summary["task_id"]
        group = groups.setdefault(
            task_id,
            {
                "taskId": task_id,
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
    return sorted(groups.values(), key=lambda item: item["modifiedAt"], reverse=True)


def list_issues(task_id: str = "") -> list[dict[str, Any]]:
    report_paths = report_paths_for_issue_scan()
    report_names = {report_display_name(path) for path in report_paths[:200]}
    issues: list[dict[str, Any]] = []
    for path in report_paths:
        if task_id and task_id_for_report(path) != task_id:
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
    report_type = report_type_for(path)
    issues = extract_issues(text) if include_issues else []
    issue_count = len(issues) if include_issues else count_issue_lines(text)
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
    return "application/octet-stream"


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
    print(f"Web console: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
