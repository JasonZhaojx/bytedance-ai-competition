"""Build and maintain a skill-like wiki folder from a final comparison report.

The LLM owns the information architecture and file contents. This script only:
1. extracts the report article before STRUCTURED ANALYSIS JSON,
2. chunks long articles and asks the LLM to make maintenance notes per chunk,
3. sends current wiki files + chunk notes to the configured LLM,
4. safely writes the LLM-proposed file updates into the output folder.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from extracted_core.llm_client import chat_content


MARKER = "===== STRUCTURED ANALYSIS JSON ====="
DEFAULT_REPORT = PROJECT_ROOT / "reports" / "20260528_232538_FINAL_COMPARISON.md"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports" / "skill_wiki"
BUILD_DIR_NAME = "_build"


@dataclass(frozen=True)
class ArticleChunk:
    chunk_id: str
    title: str
    content: str


def main() -> None:
    args = parse_args()
    report_path = Path(args.report).resolve()
    output_dir = Path(args.output_dir).resolve()
    article = extract_article(report_path, marker=args.marker)
    if not article.strip():
        raise RuntimeError(f"No article content found before marker: {MARKER}")

    existing_files = read_existing_wiki(output_dir)
    article_notes = prepare_article_notes(
        article=article,
        existing_files=existing_files,
        output_dir=output_dir,
        domain=args.domain,
        chunk_chars=args.chunk_chars,
        chunk_overlap=args.chunk_overlap,
        chunk_workers=args.chunk_workers,
        max_existing_chars=args.max_existing_chars,
        temperature=args.temperature,
        timeout=args.timeout,
    )
    payload = call_wiki_llm(
        article_notes=article_notes,
        existing_files=existing_files,
        output_dir=output_dir,
        domain=args.domain,
        max_notes_chars=args.max_notes_chars,
        max_existing_chars=args.max_existing_chars,
        temperature=args.temperature,
        timeout=args.timeout,
    )
    writes = apply_wiki_payload(payload, output_dir)
    print(f"[skill-wiki] report: {report_path}", flush=True)
    print(f"[skill-wiki] output_dir: {output_dir}", flush=True)
    print(f"[skill-wiki] files_written: {len(writes)}", flush=True)
    for path in writes:
        print(f"[skill-wiki] wrote: {path}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Use an LLM to maintain a skill-like wiki folder from FINAL_COMPARISON.md.",
    )
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="FINAL_COMPARISON.md path.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Target wiki folder.")
    parser.add_argument(
        "--marker",
        default=os.getenv("SKILL_WIKI_MARKER", MARKER),
        help="Optional split marker. Text before this marker is used; empty means read the whole file.",
    )
    parser.add_argument(
        "--domain",
        default=os.getenv("SKILL_WIKI_DOMAIN", ""),
        help="Optional domain/topic hint for the source document. Empty by default.",
    )
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=int(os.getenv("SKILL_WIKI_CHUNK_CHARS", "24000")),
        help="Approximate max chars per article chunk before LLM note extraction.",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=int(os.getenv("SKILL_WIKI_CHUNK_OVERLAP", "1200")),
        help="Character overlap when a single section must be hard-split.",
    )
    parser.add_argument(
        "--chunk-workers",
        type=int,
        default=int(os.getenv("SKILL_WIKI_CHUNK_WORKERS", "4")),
        help="Concurrent LLM calls for independent chunk-note extraction.",
    )
    parser.add_argument(
        "--max-notes-chars",
        type=int,
        default=int(os.getenv("SKILL_WIKI_MAX_NOTES_CHARS", "120000")),
        help="Max aggregated chunk-note chars sent to the final wiki-maintenance call.",
    )
    parser.add_argument(
        "--max-existing-chars",
        type=int,
        default=int(os.getenv("SKILL_WIKI_MAX_EXISTING_CHARS", "80000")),
        help="Max existing wiki chars sent to each LLM call.",
    )
    parser.add_argument("--temperature", type=float, default=float(os.getenv("SKILL_WIKI_TEMPERATURE", "0.2")))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("SKILL_WIKI_LLM_TIMEOUT", "300")))
    return parser.parse_args()


def extract_article(report_path: Path, marker: str = MARKER) -> str:
    text = report_path.read_text(encoding="utf-8", errors="replace")
    if marker and marker in text:
        text = text.split(marker, 1)[0]
    return text.strip()


def read_existing_wiki(output_dir: Path) -> List[Dict[str, str]]:
    if not output_dir.exists():
        return []
    files: List[Dict[str, str]] = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".json", ".txt"}:
            continue
        if BUILD_DIR_NAME in path.relative_to(output_dir).parts:
            continue
        if path.name == "wiki_manifest.json":
            continue
        rel = path.relative_to(output_dir).as_posix()
        content = path.read_text(encoding="utf-8", errors="replace")
        files.append({"path": rel, "content": content})
    return files


def prepare_article_notes(
    *,
    article: str,
    existing_files: List[Dict[str, str]],
    output_dir: Path,
    domain: str,
    chunk_chars: int,
    chunk_overlap: int,
    chunk_workers: int,
    max_existing_chars: int,
    temperature: float,
    timeout: int,
) -> List[Dict[str, Any]]:
    chunks = split_article_into_chunks(article, max_chars=chunk_chars, overlap=chunk_overlap)
    workers = max(1, min(chunk_workers, len(chunks) or 1))
    print(
        f"[skill-wiki] article chars={len(article)}, chunks={len(chunks)}, "
        f"chunk_chars={chunk_chars}, workers={workers}",
        flush=True,
    )
    notes_by_index: Dict[int, Dict[str, Any]] = {}

    def summarize_one(index: int, chunk: ArticleChunk) -> tuple[int, Dict[str, Any]]:
        started = time.time()
        print(
            f"[skill-wiki] chunk {index}/{len(chunks)} summarize start: "
            f"{chunk.chunk_id}, chars={len(chunk.content)}, title={chunk.title[:60]}",
            flush=True,
        )
        note = call_chunk_llm(
            chunk=chunk,
            existing_files=existing_files,
            domain=domain,
            max_existing_chars=max_existing_chars,
            temperature=temperature,
            timeout=timeout,
        )
        print(
            f"[skill-wiki] chunk {index}/{len(chunks)} summarize done in {time.time() - started:.1f}s",
            flush=True,
        )
        return index, note

    if workers == 1:
        for index, chunk in enumerate(chunks, start=1):
            note_index, note = summarize_one(index, chunk)
            notes_by_index[note_index] = note
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(summarize_one, index, chunk): index
                for index, chunk in enumerate(chunks, start=1)
            }
            for future in as_completed(futures):
                note_index, note = future.result()
                notes_by_index[note_index] = note

    notes = [notes_by_index[index] for index in sorted(notes_by_index)]
    write_build_notes(notes, output_dir)
    return notes


def split_article_into_chunks(article: str, *, max_chars: int, overlap: int) -> List[ArticleChunk]:
    max_chars = max(4000, max_chars)
    overlap = max(0, min(overlap, max_chars // 3))
    sections = split_markdown_sections(article)
    chunks: List[ArticleChunk] = []
    current_parts: List[str] = []
    current_title = "article-start"
    current_len = 0

    def flush() -> None:
        nonlocal current_parts, current_title, current_len
        content = "\n\n".join(part.strip() for part in current_parts if part.strip()).strip()
        if content:
            chunks.append(
                ArticleChunk(
                    chunk_id=f"chunk_{len(chunks) + 1:03d}",
                    title=current_title,
                    content=content,
                )
            )
        current_parts = []
        current_title = "article-start"
        current_len = 0

    for title, section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) > max_chars:
            flush()
            for part in hard_split_text(section, max_chars=max_chars, overlap=overlap):
                chunks.append(
                    ArticleChunk(
                        chunk_id=f"chunk_{len(chunks) + 1:03d}",
                        title=title,
                        content=part,
                    )
                )
            continue
        separator_len = 2 if current_parts else 0
        projected_len = current_len + len(section) + separator_len
        if current_parts and projected_len > max_chars:
            flush()
            separator_len = 0
        if not current_parts:
            current_title = title
        current_parts.append(section)
        current_len += len(section) + separator_len
    flush()
    return chunks


def split_markdown_sections(article: str) -> List[tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^#{1,4}\s+.+$", article))
    if not matches:
        return [("article", article)]
    sections: List[tuple[str, str]] = []
    if matches[0].start() > 0:
        preface = article[: matches[0].start()].strip()
        if preface:
            sections.append(("preface", preface))
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(article)
        heading = match.group(0).lstrip("#").strip()
        sections.append((heading, article[start:end].strip()))
    return sections


def hard_split_text(text: str, *, max_chars: int, overlap: int) -> List[str]:
    parts: List[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            break_at = max(
                text.rfind("\n", start, end),
                text.rfind("\u3002", start, end),
                text.rfind(".", start, end),
            )
            if break_at > start + max_chars // 2:
                end = break_at + 1
        part = text[start:end].strip()
        if part:
            parts.append(part)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return parts


def call_chunk_llm(
    *,
    chunk: ArticleChunk,
    existing_files: List[Dict[str, str]],
    domain: str,
    max_existing_chars: int,
    temperature: float,
    timeout: int,
) -> Dict[str, Any]:
    api_key, base_url, model = llm_config_from_env()
    if not api_key or not base_url or not model:
        raise RuntimeError("Missing LLM config. Set LLM_PROVIDER and provider API env vars.")

    existing_payload = truncate_existing_files(existing_files, max_existing_chars)
    prompt = f"""
You are a knowledge-base maintenance agent for a Codex-style skill/wiki.
Read one chunk of a source document. Do not write final files yet.
Produce dense maintenance notes for the later wiki-maintenance step.
Optional document domain/topic hint: {domain or "not provided"}

Rules:
- Use only facts present in this chunk. Do not invent information.
- Preserve reusable stable knowledge that matters for this document type, such as entities, product or service profiles, capabilities, users, scenarios, pricing, compliance, evidence, comparisons, risks, decisions, and strategy implications.
- Suggest target files when useful, such as SKILL.md, references/, tables/, playbooks/, notes/, or params/. The final structure will be decided later.
- Remove fluff, repeated paragraphs, rendering-failure messages, and pure formatting noise.
- Output JSON only. Do not wrap it in a Markdown code fence.
- Write notes in the source document's primary language by default.

Return JSON:
{{
  "chunk_id": "{chunk.chunk_id}",
  "title": "{chunk.title}",
  "source_headings": ["..."],
  "wiki_notes": "high-density notes for later wiki maintenance",
  "facts": ["fact 1", "fact 2"],
  "suggested_files": ["SKILL.md", "tables/example.md"],
  "open_questions": ["missing evidence or follow-up item"]
}}

Existing wiki files:
{json.dumps(existing_payload, ensure_ascii=False, indent=2)}

Source chunk:
{chunk.content}
""".strip()
    raw = chat_content(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            {"role": "system", "content": "You are a strict chunk summarization agent. Return parseable JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        timeout=timeout,
        retries=1,
    )
    data = parse_json_object(raw)
    if not isinstance(data, dict):
        raise RuntimeError(f"Chunk LLM did not return a JSON object: {chunk.chunk_id}")
    data.setdefault("chunk_id", chunk.chunk_id)
    data.setdefault("title", chunk.title)
    return data


def call_wiki_llm(
    *,
    article_notes: List[Dict[str, Any]],
    existing_files: List[Dict[str, str]],
    output_dir: Path,
    domain: str,
    max_notes_chars: int,
    max_existing_chars: int,
    temperature: float,
    timeout: int,
) -> Dict[str, Any]:
    api_key, base_url, model = llm_config_from_env()
    if not api_key or not base_url or not model:
        raise RuntimeError("Missing LLM config. Set LLM_PROVIDER and provider API env vars.")

    notes_payload = truncate_text(json.dumps(article_notes, ensure_ascii=False, indent=2), max_notes_chars)
    existing_payload = truncate_existing_files(existing_files, max_existing_chars)
    print(
        f"[skill-wiki] final wiki maintenance start: notes_chars={len(notes_payload)}, existing_files={len(existing_payload)}",
        flush=True,
    )
    prompt = f"""
You are a knowledge-base maintenance agent for a Codex-style skill/wiki.
You will receive chunk-level notes extracted by an LLM from a source document, plus existing wiki files.
Decide the information architecture and maintain the wiki folder yourself.
Optional document domain/topic hint: {domain or "not provided"}

Tasks:
- Create or update SKILL.md as a progressive-disclosure entry file.
- You may create references/, playbooks/, tables/, notes/, params/, or other useful subfolders.
- Keep SKILL.md short: when to use this wiki, how to read it, core index, and where to go next.
- Put detailed knowledge in subfiles rather than dumping it all into SKILL.md.
- If files already exist, incrementally maintain them: merge, rewrite, supplement, and deduplicate.
- Content should be reusable by later LLMs and humans, like a stable wiki.
- Output JSON only. Do not wrap it in a Markdown code fence.
- Write wiki file content in the source document's primary language by default.

Safety and format:
- Paths must be relative. Do not use absolute paths or include ..
- Use forward slashes in file paths.
- You must output at least SKILL.md.
- Return JSON:
{{
  "summary": "what changed in this maintenance run",
  "files": [
    {{"path": "SKILL.md", "content": "..."}},
    {{"path": "references/example.md", "content": "..."}}
  ]
}}

Target output dir:
{output_dir}

Existing wiki files:
{json.dumps(existing_payload, ensure_ascii=False, indent=2)}

Chunk-level report notes:
{notes_payload}
""".strip()
    raw = chat_content(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            {"role": "system", "content": "You are a strict wiki maintenance agent. Return parseable JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        timeout=timeout,
        retries=1,
    )
    data = parse_json_object(raw)
    if not isinstance(data, dict):
        raise RuntimeError("LLM did not return a JSON object")
    return data


def write_build_notes(notes: List[Dict[str, Any]], output_dir: Path) -> None:
    build_dir = output_dir / BUILD_DIR_NAME
    build_dir.mkdir(parents=True, exist_ok=True)
    notes_path = build_dir / "chunk_notes.jsonl"
    with notes_path.open("w", encoding="utf-8") as handle:
        for note in notes:
            handle.write(json.dumps(note, ensure_ascii=False) + "\n")
    manifest = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chunks": len(notes),
        "notes_file": notes_path.relative_to(output_dir).as_posix(),
    }
    (build_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[skill-wiki] build notes: {notes_path}", flush=True)


def truncate_existing_files(files: List[Dict[str, str]], max_chars: int) -> List[Dict[str, str]]:
    remaining = max(0, max_chars)
    output: List[Dict[str, str]] = []
    for item in files:
        content = item.get("content", "")
        if remaining <= 0:
            content = ""
        else:
            content = content[:remaining]
            remaining -= len(content)
        output.append({"path": item.get("path", ""), "content": content})
    return output


def truncate_text(text: str, max_chars: int) -> str:
    max_chars = max(1000, max_chars)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[TRUNCATED: increase SKILL_WIKI_MAX_NOTES_CHARS or --max-notes-chars]"


def apply_wiki_payload(payload: Dict[str, Any], output_dir: Path) -> List[Path]:
    files = payload.get("files")
    if not isinstance(files, list):
        raise RuntimeError("LLM JSON missing files list")
    output_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        rel_path = safe_relative_path(str(item.get("path") or ""))
        content = str(item.get("content") or "")
        if not rel_path or not content.strip():
            continue
        target = (output_dir / rel_path).resolve()
        if not is_relative_to(target, output_dir):
            raise RuntimeError(f"Unsafe output path: {rel_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.rstrip() + "\n", encoding="utf-8")
        written.append(target)
    if not any(path.name == "SKILL.md" for path in written):
        raise RuntimeError("LLM did not write SKILL.md")
    manifest = {
        "summary": payload.get("summary", ""),
        "files": [path.relative_to(output_dir).as_posix() for path in written],
    }
    (output_dir / "wiki_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return written


def safe_relative_path(value: str) -> str:
    value = value.replace("\\", "/").strip().lstrip("/")
    parts = [part for part in value.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        return ""
    return "/".join(parts)


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def parse_json_object(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def llm_config_from_env() -> tuple[str, str, str]:
    provider = int(os.getenv("LLM_PROVIDER", "0"))
    if provider == 0:
        return (
            os.getenv("REPORT_LLM_API_KEY") or os.getenv("LLM0_API_KEY") or os.getenv("ARK_API_KEY", "ARK_API_KEY_REDACTED"),
            os.getenv("REPORT_LLM_BASE_URL") or os.getenv("LLM0_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
            os.getenv("REPORT_LLM_MODEL") or os.getenv("LLM0_MODEL", "ep-20260514111325-xjmj7"),
        )
    if provider == 1:
        return (
            os.getenv("REPORT_LLM_API_KEY") or os.getenv("LLM_API_KEY", ""),
            os.getenv("REPORT_LLM_BASE_URL") or os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1/chat/completions"),
            os.getenv("REPORT_LLM_MODEL") or os.getenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
        )
    if provider == 2:
        return (
            os.getenv("REPORT_LLM_API_KEY") or os.getenv("LLM2_API_KEY") or os.getenv("MIMO_API_KEY", ""),
            os.getenv("REPORT_LLM_BASE_URL") or os.getenv("LLM2_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1"),
            os.getenv("REPORT_LLM_MODEL") or os.getenv("LLM2_MODEL", "mimo-v2.5-pro"),
        )
    raise RuntimeError(f"Unsupported LLM_PROVIDER: {provider}")


if __name__ == "__main__":
    main()
