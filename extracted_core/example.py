"""Minimal CLI example for the extracted core package."""

from __future__ import annotations

import os
import sys
from pathlib import Path


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extracted_core import AgentConfig, SearchConfig, SearchSource, run_agent_generator


def main() -> None:
    question = os.getenv("QUESTION", "What is the latest USD to CNY exchange rate?")
    source = SearchSource(os.getenv("SEARCH_SOURCE", SearchSource.DUCKDUCKGO.value))

    search_config = SearchConfig(
        source=source,
        bocha_api_key=os.getenv("BOCHA_API_KEY", ""),
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        google_cx_id=os.getenv("GOOGLE_CX_ID", ""),
        proxy=os.getenv("HTTP_PROXY") or None,
        count=int(os.getenv("SEARCH_COUNT", "3")),
    )

    agent_config = AgentConfig(
        api_key=os.getenv("LLM_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        model=os.getenv("LLM_MODEL", "Doubao-Seed-2.0-lite"),
        search=search_config,
        max_steps=int(os.getenv("MAX_STEPS", "8")),
    )

    for event in run_agent_generator(question, agent_config):
        print(f"[{event.type}] {event.content}\n")


if __name__ == "__main__":
    main()
