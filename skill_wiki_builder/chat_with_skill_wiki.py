"""Chat with an LLM over a generated skill/wiki folder."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from extracted_core.llm_client import chat_content
from skill_wiki_builder.build_skill_wiki import BUILD_DIR_NAME, llm_config_from_env


DEFAULT_WIKI_DIR = PROJECT_ROOT / "reports" / "skill_wiki"


def main() -> None:
    args = parse_args()
    wiki_dir = resolve_wiki_dir(args.wiki_dir)
    print(f"[skill-wiki-chat] wiki_dir: {wiki_dir}", flush=True)

    docs = load_wiki_docs(wiki_dir)
    print(f"[skill-wiki-chat] loaded docs: {len(docs)}", flush=True)
    if not docs:
        raise RuntimeError(f"No wiki docs found in {wiki_dir}. Run build_skill_wiki.py first.")

    if args.question:
        print("[skill-wiki-chat] asking LLM...", flush=True)
        answer = ask_wiki(
            docs=docs,
            question=args.question,
            domain_hints=args.domain_hints,
            max_context_chars=args.max_context_chars,
            temperature=args.temperature,
            timeout=args.timeout,
            debug_context=args.debug_context,
        )
        print(answer, flush=True)
        return

    print("[skill-wiki-chat] Input a question. Type exit / quit / q to leave.", flush=True)
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("", flush=True)
            break
        if not question:
            continue
        if question.lower() in {"exit", "quit", "q"}:
            break
        print("[skill-wiki-chat] asking LLM...", flush=True)
        answer = ask_wiki(
            docs=docs,
            question=question,
            domain_hints=args.domain_hints,
            max_context_chars=args.max_context_chars,
            temperature=args.temperature,
            timeout=args.timeout,
            debug_context=args.debug_context,
        )
        print(answer, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ask questions over the generated skill/wiki folder.")
    parser.add_argument("--wiki-dir", default=str(DEFAULT_WIKI_DIR), help="Generated wiki folder.")
    parser.add_argument("--question", "-q", default="", help="Single question mode.")
    parser.add_argument(
        "--domain-hints",
        default=os.getenv("SKILL_WIKI_CHAT_DOMAIN_HINTS", ""),
        help="Optional comma/space separated domain terms to improve retrieval. Empty by default.",
    )
    parser.add_argument(
        "--max-context-chars",
        type=int,
        default=int(os.getenv("SKILL_WIKI_CHAT_CONTEXT_CHARS", "60000")),
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=float(os.getenv("SKILL_WIKI_CHAT_TEMPERATURE", "0.2")),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("SKILL_WIKI_CHAT_TIMEOUT", "180")),
    )
    parser.add_argument(
        "--debug-context",
        action="store_true",
        default=os.getenv("SKILL_WIKI_CHAT_DEBUG_CONTEXT", "").lower() in {"1", "true", "yes"},
        help="Print selected wiki files before asking the LLM.",
    )
    return parser.parse_args()


def resolve_wiki_dir(value: str) -> Path:
    path = Path(value)
    candidates: List[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.extend([Path.cwd() / path, PROJECT_ROOT / path])
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[-1].resolve()


def load_wiki_docs(wiki_dir: Path) -> List[Dict[str, str]]:
    docs: List[Dict[str, str]] = []
    for path in sorted(wiki_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt", ".json"}:
            continue
        rel_parts = path.relative_to(wiki_dir).parts
        if BUILD_DIR_NAME in rel_parts:
            continue
        if path.name == "wiki_manifest.json":
            continue
        rel = path.relative_to(wiki_dir).as_posix()
        content = path.read_text(encoding="utf-8", errors="replace").strip()
        if content:
            docs.append({"path": rel, "content": content})
    docs.sort(key=wiki_doc_order_key)
    return docs


def wiki_doc_order_key(doc: Dict[str, str]) -> tuple[int, str]:
    path = doc["path"].lower()
    if path == "skill.md":
        return (0, path)
    if path.endswith("source_report_tables.md"):
        return (1, path)
    if path.endswith("source_chunk_facts_and_gaps.md"):
        return (2, path)
    if path.endswith("source_report_full.md"):
        return (3, path)
    return (4, path)


def ask_wiki(
    *,
    docs: List[Dict[str, str]],
    question: str,
    domain_hints: str,
    max_context_chars: int,
    temperature: float,
    timeout: int,
    debug_context: bool,
    llm_config: tuple[str, str, str] | None = None,
) -> str:
    api_key, base_url, model = llm_config or llm_config_from_env()
    if not api_key or not base_url or not model:
        raise RuntimeError("Missing LLM config. Set LLM_PROVIDER and provider API env vars.")
    context, selected_paths = build_context(
        docs,
        question,
        domain_hints=domain_hints,
        max_context_chars=max_context_chars,
    )
    query_hint = build_query_hint(question, domain_hints)
    if debug_context:
        print(f"[skill-wiki-chat] selected docs: {', '.join(selected_paths)}", flush=True)
        print(f"[skill-wiki-chat] context chars: {len(context)}", flush=True)

    prompt = f"""
You are a Q&A assistant over a local skill/wiki knowledge base.

Answer rules:
- Answer only from the wiki content below.
- Treat source-memory files as highest authority: source_report_tables.md for table facts, source_report_full.md for original wording, and source_chunk_facts_and_gaps.md for missing information. If generated wiki files conflict with source-memory files, trust the source-memory files.
- For questions about parameters, comparison rows, evidence IDs, missing fields, or table content, inspect source_report_tables.md and source_report_full.md before summarizing.
- Normalize only generic product-category wording. Terms like product, tool, platform, service, vendor, competitor, solution, and their Chinese equivalents can refer to the same broad category when the wiki uses equivalent terms.
- Also use the optional domain hints below when they are provided. If no domain hints are provided, do not assume a specific industry.
- If the user asks how many tools/products are in the wiki, count distinct product or competitor names explicitly present in the wiki. Do not require the user's wording to appear verbatim.
- If the wiki contains equivalent information but not the user's exact term, answer based on the equivalent wiki term and briefly state the normalization.
- Only say "current wiki does not cover this" when no equivalent information exists in the wiki content.
- Prefer citing wiki file paths, for example [SKILL.md] or [references/foo.md].
- Be direct and structured. Do not invent facts.

User question:
{question}

Query normalization hint:
{query_hint}

Wiki content:
{context}
""".strip()
    return chat_content(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are a careful local-wiki Q&A assistant. Prefer Chinese when the user asks in Chinese.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
        timeout=timeout,
        retries=1,
    ).strip()


def build_context(
    docs: List[Dict[str, str]],
    question: str,
    *,
    domain_hints: str,
    max_context_chars: int,
) -> tuple[str, List[str]]:
    max_context_chars = max(1000, max_context_chars)
    chunks: List[str] = []
    selected_paths: List[str] = []
    added_keys: set[str] = set()
    used = 0

    def add_block(label: str, content: str, *, key: str, max_chars: int | None = None) -> None:
        nonlocal used
        if key in added_keys:
            return
        body = content.strip()
        if not body:
            return
        if max_chars is not None:
            body = body[:max_chars]
        header = f"\n\n--- {label} ---\n"
        budget = max_context_chars - used - len(header)
        if budget <= 0:
            return
        piece = body[:budget]
        chunks.append(header + piece)
        selected_paths.append(label)
        used += len(header) + len(piece)
        added_keys.add(key)

    by_path = {doc["path"].lower(): doc for doc in docs}
    source_tables = next((doc for doc in docs if doc["path"].lower().endswith("source_report_tables.md")), None)
    source_facts = next((doc for doc in docs if doc["path"].lower().endswith("source_chunk_facts_and_gaps.md")), None)
    source_full = next((doc for doc in docs if doc["path"].lower().endswith("source_report_full.md")), None)

    skill_doc = by_path.get("skill.md")
    if skill_doc:
        add_block(skill_doc["path"], skill_doc["content"], key=skill_doc["path"], max_chars=6000)
    if source_tables:
        add_block(source_tables["path"], source_tables["content"], key=source_tables["path"], max_chars=40000)
    if source_facts:
        add_block(source_facts["path"], source_facts["content"], key=source_facts["path"], max_chars=30000)

    generated_docs = [
        doc
        for doc in select_relevant_docs(docs, question, domain_hints=domain_hints)
        if not doc["path"].lower().endswith(
            ("source_report_full.md", "source_report_tables.md", "source_chunk_facts_and_gaps.md")
        )
    ]
    for doc in generated_docs[:6]:
        add_block(doc["path"], doc["content"], key=doc["path"], max_chars=14000)
        if used >= max_context_chars:
            break

    if source_full and used < max_context_chars:
        for section_label, section_body in select_relevant_source_sections(
            source_full,
            question,
            domain_hints=domain_hints,
            limit=8,
        ):
            add_block(section_label, section_body, key=section_label, max_chars=12000)
            if used >= max_context_chars:
                break
    return "".join(chunks).strip(), selected_paths


def select_relevant_source_sections(
    doc: Dict[str, str],
    question: str,
    *,
    domain_hints: str,
    limit: int,
) -> List[tuple[str, str]]:
    terms = tokenize(expand_query_for_retrieval(question, domain_hints))
    sections = split_markdown_sections(doc["content"])
    scored: List[tuple[int, int, str, str]] = []
    for index, (title, body) in enumerate(sections):
        value = score_text_for_terms(title + "\n" + body, terms)
        if value <= 0:
            value = 1 if index < 3 else 0
        if value > 0:
            label = f"{doc['path']}#{title or index + 1}"
            scored.append((-value, index, label, body))
    scored.sort()
    return [(label, body) for _score, _index, label, body in scored[:limit]]


def split_markdown_sections(content: str) -> List[tuple[str, str]]:
    sections: List[tuple[str, List[str]]] = []
    current_title = "开头"
    current_lines: List[str] = []
    for line in content.splitlines():
        heading = re.match(r"^(#{1,4})\s+(.+?)\s*$", line)
        if heading and current_lines:
            sections.append((current_title, current_lines))
            current_title = heading.group(2).strip()
            current_lines = [line]
            continue
        if heading:
            current_title = heading.group(2).strip()
        current_lines.append(line)
    if current_lines:
        sections.append((current_title, current_lines))

    expanded: List[tuple[str, str]] = []
    for title, lines in sections:
        body = "\n".join(lines).strip()
        if len(body) <= 14000:
            expanded.append((title, body))
            continue
        for index in range(0, len(body), 10000):
            expanded.append((f"{title} part {index // 10000 + 1}", body[index : index + 12000]))
    return expanded


def select_relevant_docs(docs: List[Dict[str, str]], question: str, *, domain_hints: str = "") -> List[Dict[str, str]]:
    terms = tokenize(expand_query_for_retrieval(question, domain_hints))

    def score(doc: Dict[str, str]) -> tuple[int, int, str]:
        path = doc["path"].lower()
        content = doc["content"].lower()
        value = 0
        if path == "skill.md":
            value += 100
        if path.endswith("source_report_tables.md"):
            value += 160
        elif path.endswith("source_chunk_facts_and_gaps.md"):
            value += 120
        elif path.endswith("source_report_full.md"):
            value += 80
        value += score_text_for_terms(path, terms, path_weight=15)
        value += score_text_for_terms(content, terms)
        return (-value, len(content), doc["path"])

    return sorted(docs, key=score)


def score_text_for_terms(text: str, terms: List[str], *, path_weight: int = 1) -> int:
    lowered = text.lower()
    value = 0
    for term in terms:
        if term in lowered:
            value += path_weight if path_weight > 1 else min(lowered.count(term), 8)
    return value


def tokenize(text: str) -> List[str]:
    raw = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
    terms: List[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        term = term.strip()
        if len(term) <= 1 or term in seen:
            return
        seen.add(term)
        terms.append(term)

    for item in raw:
        add(item)
        if re.search(r"[\u4e00-\u9fff]", item):
            for size in (2, 3, 4):
                for index in range(0, max(0, len(item) - size + 1)):
                    add(item[index : index + size])
    return terms[:240]


def expand_query_for_retrieval(question: str, domain_hints: str = "") -> str:
    additions: List[str] = parse_domain_hints(domain_hints)
    if is_product_category_question(question):
        additions.extend(generic_category_terms())
    return " ".join([question, *additions])


def build_query_hint(question: str, domain_hints: str = "") -> str:
    expanded = expand_query_for_retrieval(question, domain_hints)
    if expanded == question:
        return "No extra normalization hint."
    return expanded


def parse_domain_hints(value: str) -> List[str]:
    if not value.strip():
        return []
    return [item for item in re.split(r"[,;\uFF0C\uFF1B\s]+", value.strip()) if item]


def generic_category_terms() -> List[str]:
    return [
        "product",
        "tool",
        "platform",
        "service",
        "vendor",
        "competitor",
        "solution",
        "offering",
        "\u7ade\u54c1",
        "\u4ea7\u54c1",
        "\u5de5\u5177",
        "\u5e73\u53f0",
        "\u670d\u52a1",
        "\u5382\u5546",
        "\u65b9\u6848",
        "\u4ea7\u54c1\u5b9a\u4f4d",
        "\u5bf9\u6bd4",
    ]


def is_product_category_question(question: str) -> bool:
    lowered = question.lower()
    trigger_words = [
        "\u51e0\u4e2a",
        "\u591a\u5c11",
        "\u54ea\u4e9b",
        "\u6709\u54ea",
        "\u4ea7\u54c1",
        "\u5de5\u5177",
        "\u5e73\u53f0",
        "\u670d\u52a1",
        "\u7ade\u54c1",
        "\u5382\u5546",
        "\u65b9\u6848",
        "how many",
        "which",
        "what",
        "list",
        "count",
        "product",
        "tool",
        "platform",
        "service",
        "vendor",
        "competitor",
        "solution",
    ]
    return any(word in lowered or word in question for word in trigger_words)


if __name__ == "__main__":
    main()
