"""Prompt chunking helpers for report_agent.

The workflow keeps full upstream material in memory and on disk, but cloud LLM
APIs still have per-request context limits. These helpers split structured
objects into bounded prompt batches without mutating the original records.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable, List, Sequence, TypeVar

T = TypeVar("T")


def prompt_chunk_chars() -> int:
    return int(os.getenv("REPORT_AGENT_PROMPT_CHUNK_CHARS", "30000"))


def to_json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def chunk_by_json_size(items: Sequence[T], max_chars: int | None = None) -> List[List[T]]:
    """Split items so each chunk's JSON stays near max_chars.

    A single oversized item is still returned as its own chunk; the caller can
    decide whether to summarize it or let the provider reject it.
    """

    if not items:
        return []
    budget = max_chars if max_chars is not None else prompt_chunk_chars()
    if budget <= 0:
        return [list(items)]

    chunks: List[List[T]] = []
    current: List[T] = []
    current_size = 2
    for item in items:
        item_size = to_json_size(item)
        if current and current_size + item_size > budget:
            chunks.append(current)
            current = []
            current_size = 2
        current.append(item)
        current_size += item_size
    if current:
        chunks.append(current)
    return chunks


def compact_dicts(items: Iterable[Any], max_chars: int | None = None) -> List[Any]:
    """Return dict/list payloads clipped only for model prompting.

    This is intentionally separate from source normalization: original data is
    not changed, only the transient prompt payload is made bounded if one item is
    individually too large.
    """

    budget = max_chars if max_chars is not None else int(
        os.getenv("REPORT_AGENT_PROMPT_ITEM_CHARS", "50000")
    )
    if budget <= 0:
        return list(items)

    compacted: List[Any] = []
    for item in items:
        if isinstance(item, dict):
            next_item = {}
            for key, value in item.items():
                if isinstance(value, str) and len(value) > budget:
                    next_item[key] = value[:budget].rstrip()
                else:
                    next_item[key] = value
            compacted.append(next_item)
        else:
            compacted.append(item)
    return compacted


def evidence_prompt_payload(cards: Iterable[Any]) -> List[dict[str, Any]]:
    """Build a compact evidence payload for downstream LLM calls.

    Full raw excerpts remain on EvidenceCard and in ReportPackage. Downstream
    reasoning nodes usually need stable ids and claims, not the whole crawled
    paragraph repeated in every prompt.
    """

    include_excerpt = os.getenv("REPORT_AGENT_PROMPT_INCLUDE_RAW_EXCERPT", "0").strip()
    include_excerpt = include_excerpt.lower() not in {"0", "false", "no", "off"}
    payload: List[dict[str, Any]] = []
    for card in cards:
        item = {
            "evidence_id": getattr(card, "evidence_id", ""),
            "source_id": getattr(card, "source_id", ""),
            "competitor": getattr(card, "competitor", None),
            "dimension": getattr(card, "dimension", ""),
            "claim": getattr(card, "claim", ""),
            "confidence": getattr(card, "confidence", 0.0),
            "freshness": getattr(card, "freshness", "unknown"),
            "importance_for_pm": getattr(card, "importance_for_pm", ""),
        }
        if include_excerpt:
            item["raw_excerpt"] = getattr(card, "raw_excerpt", "")
        payload.append(item)
    return payload


def chunk_evidence_cards(cards: Sequence[T], max_chars: int | None = None) -> List[List[T]]:
    """Chunk EvidenceCard-like objects by the compact prompt payload size."""

    if not cards:
        return []
    budget = max_chars if max_chars is not None else prompt_chunk_chars()
    if budget <= 0:
        return [list(cards)]

    chunks: List[List[T]] = []
    current: List[T] = []
    current_size = 2
    for card in cards:
        item_size = to_json_size(evidence_prompt_payload([card])[0])
        if current and current_size + item_size > budget:
            chunks.append(current)
            current = []
            current_size = 2
        current.append(card)
        current_size += item_size
    if current:
        chunks.append(current)
    return chunks
