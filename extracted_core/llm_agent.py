"""OpenAI-compatible recursive search agent core."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Dict, Generator, List, Optional

from .llm_client import chat_content
from .search import SearchConfig, unified_search


@dataclass
class AgentConfig:
    api_key: str
    base_url: str
    model: str
    search: SearchConfig
    max_steps: int = 8
    temperature: float = 0.3
    max_tokens: int = 2000


@dataclass
class AgentEvent:
    type: str
    content: str
    step: Optional[int] = None


def _parse_json_object(content: str) -> Dict[str, str]:
    cleaned = content.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned)


def _build_system_prompt(search_source: str) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""
You are a research assistant with web search access.
Current search engine: {search_source}
Current time: {now}

Work loop:
1. Decide whether more web search is needed.
2. If needed, output a precise search query.
3. After receiving search results, decide whether to search again or finish.

Return strict JSON only:
{{
  "thought": "Briefly explain what is known, what is missing, and the next decision.",
  "action": "search or finish",
  "query": "Search query, only when action is search",
  "answer": "Final answer, only when action is finish. Include source URLs when useful."
}}
""".strip()


def run_agent_generator(
    question: str,
    config: AgentConfig,
) -> Generator[AgentEvent, None, None]:
    """Run the recursive search loop and yield progress events."""
    messages: List[Dict[str, str]] = [
        {
            "role": "system",
            "content": _build_system_prompt(config.search.source.value),
        },
        {"role": "user", "content": f"Please answer this question: {question}"},
    ]

    for step in range(1, config.max_steps + 1):
        yield AgentEvent("status", f"Running reasoning step {step}", step)

        try:
            content = chat_content(
                api_key=config.api_key,
                base_url=config.base_url,
                model=config.model,
                messages=messages,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
            decision = _parse_json_object(content)
        except Exception as exc:
            yield AgentEvent("error", f"LLM call or JSON parse failed: {exc}", step)
            return

        thought = decision.get("thought", "")
        action = decision.get("action", "")
        yield AgentEvent("thought", thought, step)

        if action == "search":
            query = decision.get("query", "").strip()
            if not query:
                yield AgentEvent("error", "LLM returned an empty search query", step)
                continue

            yield AgentEvent("action", query, step)
            try:
                tool_output = unified_search(query, config.search)
            except Exception as exc:
                tool_output = f"Search failed: {exc}"

            yield AgentEvent("tool_output", tool_output, step)
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": f"Search tool output:\n{tool_output}"})
            continue

        if action == "finish":
            yield AgentEvent("final_answer", decision.get("answer", ""), step)
            return

        yield AgentEvent("error", f"Unknown action: {action}", step)
        return

    yield AgentEvent(
        "final_answer",
        "Reached max_steps before the model produced a final answer.",
        config.max_steps,
    )


def run_agent(question: str, config: AgentConfig) -> str:
    """Run the agent and return only the final answer."""
    final_answer = ""
    for event in run_agent_generator(question, config):
        if event.type == "final_answer":
            final_answer = event.content
        elif event.type == "error" and not final_answer:
            final_answer = event.content
    return final_answer
