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
RUNNER = ROOT / "run_similar_product_reports.py"
DEFAULT_PORT = int(os.getenv("WEB_PORT", "8000"))


@dataclass
class Job:
    job_id: str
    product_description: str
    created_at: float = field(default_factory=time.time)
    status: str = "queued"
    stage: str = "prepare"
    logs: list[str] = field(default_factory=list)
    return_code: int | None = None
    report_path: str = ""
    error: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "product_description": self.product_description,
            "created_at": self.created_at,
            "status": self.status,
            "stage": self.stage,
            "return_code": self.return_code,
            "report_path": self.report_path,
            "report_name": Path(self.report_path).name if self.report_path else "",
            "error": self.error,
            "logs": self.logs[-500:],
        }


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
FINAL_REPORT_RE = re.compile(r"总总结已保存:\s*(.+)")


class AppHandler(BaseHTTPRequestHandler):
    server_version = "CompetitorWorkflowWeb/1.0"

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
            options = {
                "top_n": int(payload.get("top_n") or os.getenv("TOP_N", "5")),
                "quality_mode": str(payload.get("quality_mode") or "rule"),
                "max_iterations": int(payload.get("max_iterations") or 3),
                "enable_quality_loop": bool(payload.get("enable_quality_loop", True)),
                "llm_provider": str(payload.get("llm_provider") or ""),
                "ark_api_key": str(payload.get("ark_api_key") or "").strip(),
                "llm_base_url": str(payload.get("llm_base_url") or "").strip(),
                "llm_model": str(payload.get("llm_model") or "").strip(),
                "bocha_api_key": str(payload.get("bocha_api_key") or "").strip(),
                "known_param_text": str(payload.get("known_param_text") or ""),
                "questionnaire_analysis_text": str(
                    payload.get("questionnaire_analysis_text") or ""
                ),
            }
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        job = Job(job_id=uuid.uuid4().hex[:12], product_description=product_description)
        with JOBS_LOCK:
            JOBS[job.job_id] = job
        thread = threading.Thread(
            target=run_job,
            args=(job, options),
            daemon=True,
        )
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
        self._send_json(
            {
                "name": report_path.name,
                "path": str(report_path),
                "content": report_path.read_text(encoding="utf-8", errors="replace"),
                "summary": summarize_report(report_path),
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
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            file_path = FRONTEND_DIR / "index.html"
        else:
            file_path = (FRONTEND_DIR / unquote(path.lstrip("/"))).resolve()
            if FRONTEND_DIR.resolve() not in file_path.parents and file_path != FRONTEND_DIR.resolve():
                self._send_json({"error": "invalid path"}, HTTPStatus.BAD_REQUEST)
                return
        if not file_path.exists() or not file_path.is_file():
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type(file_path))
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_job(job: Job, options: dict[str, Any]) -> None:
    job.status = "running"
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
            "ENABLE_FINAL_QUALITY_LOOP": "true"
            if options["enable_quality_loop"]
            else "false",
            "FINAL_QUALITY_MODE": options["quality_mode"],
            "FINAL_QUALITY_MAX_ITERATIONS": str(options["max_iterations"]),
        }
    )
    apply_user_env(job, env, options)
    command = [sys.executable, "-u", str(RUNNER), job.product_description]
    append_log(job, "$ " + " ".join(command))
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
        if process.stdin:
            process.stdin.write("\n\n\n")
            process.stdin.flush()
            process.stdin.close()
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip("\r\n")
            append_log(job, line)
            update_stage_from_log(job, line)
            match = FINAL_REPORT_RE.search(line)
            if match:
                job.report_path = match.group(1).strip()
        job.return_code = process.wait()
        job.status = "completed" if job.return_code == 0 else "failed"
        if job.status == "completed":
            set_stage(job, "done")
        if job.return_code != 0:
            job.error = f"process exited with code {job.return_code}"
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        append_log(job, f"[backend-error] {exc}")


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

    input_dir = REPORT_DIR / "web_inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    if options["known_param_text"].strip():
        path = input_dir / f"{job.job_id}_known_params.txt"
        path.write_text(options["known_param_text"].strip(), encoding="utf-8")
        env["KNOWN_PRODUCT_PARAM_TXT"] = str(path)
    if options["questionnaire_analysis_text"].strip():
        path = input_dir / f"{job.job_id}_questionnaire.md"
        path.write_text(options["questionnaire_analysis_text"].strip(), encoding="utf-8")
        env["QUESTIONNAIRE_ANALYSIS_MD"] = str(path)


STAGE_ORDER = ["prepare", "discover", "analyze", "summarize", "quality", "done"]


def set_stage(job: Job, stage: str) -> None:
    with JOBS_LOCK:
        if STAGE_ORDER.index(stage) >= STAGE_ORDER.index(job.stage):
            job.stage = stage


def update_stage_from_log(job: Job, line: str) -> None:
    if any(token in line for token in ("LLM 改写后的搜索词", "搜索到的产品", "rewrite search queries")):
        set_stage(job, "discover")
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
    elif any(token in line for token in ("生成所选产品大总结", "FINAL COMPARISON")):
        set_stage(job, "summarize")
    elif any(token in line for token in ("最终报告质检闭环", "[quality-loop]")):
        set_stage(job, "quality")
    elif "总总结已保存" in line:
        set_stage(job, "done")


def append_log(job: Job, line: str) -> None:
    with JOBS_LOCK:
        job.logs.append(line)
        if len(job.logs) > 2000:
            del job.logs[: len(job.logs) - 2000]


def _jobs_sorted() -> list[Job]:
    with JOBS_LOCK:
        return sorted(JOBS.values(), key=lambda item: item.created_at, reverse=True)


def list_reports() -> list[dict[str, Any]]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    reports = sorted(REPORT_DIR.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    return [
        {
            "name": path.name,
            "path": str(path),
            "modified_at": path.stat().st_mtime,
            "size": path.stat().st_size,
            "summary": summarize_report(path),
        }
        for path in reports[:80]
    ]


def summarize_report(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    title = path.stem
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    return {
        "title": title,
        "is_final": "FINAL_COMPARISON" in path.name,
        "quality_feedback_applied": "===== QUALITY FEEDBACK APPLIED =====" in text,
        "sections": len(re.findall(r"^#{1,3}\s+", text, flags=re.MULTILINE)),
        "chars": len(text),
    }


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
