"""写作 Agent 的 LLM 工具函数。

所有云端模型调用都集中在这里。业务节点只调用 `call_json_llm`，拿不到合法
JSON 时自动得到 None 并进入本地 fallback，因此 offline 测试不会触发网络。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

try:  # Package import.
    from .models import WritingAgentConfig
except ImportError:  # Direct script import from this directory.
    from report_agent.models import WritingAgentConfig


def can_use_llm(config: WritingAgentConfig) -> bool:
    """只有显式开启并且 key/base/model 都存在时才允许调用 LLM。"""

    return bool(
        config.use_llm
        and config.llm_api_key
        and config.llm_base_url
        and config.llm_model
    )


def parse_json_payload(content: str) -> Optional[Any]:
    """从模型输出中解析 JSON，兼容 ```json fenced block。"""

    if not content:
        return None

    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start_positions = [
        pos for pos in (cleaned.find("{"), cleaned.find("[")) if pos >= 0
    ]
    if not start_positions:
        return None
    start = min(start_positions)
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    if end < start:
        return None

    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None


def _load_chat_content():
    """加载共享 LLM client。

    优先走正常包导入；如果包导入因路径问题失败，则直接按文件路径加载
    `extracted_core/llm_client.py`，保证 report_agent 的独立测试可运行。
    """

    try:
        from extracted_core.llm_client import chat_content

        return chat_content
    except Exception:
        llm_path = (
            Path(__file__).resolve().parents[1]
            / "extracted_core"
            / "llm_client.py"
        )
        spec = importlib.util.spec_from_file_location(
            "_report_agent_llm_client", llm_path
        )
        if not spec or not spec.loader:
            raise
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.chat_content


def call_json_llm(
    *,
    config: WritingAgentConfig,
    system_prompt: str,
    user_prompt: str,
) -> Optional[Any]:
    """调用配置的 LLM 并解析 JSON。

    任何异常都返回 None，由各业务节点 fallback；这样不会因为模型波动阻塞整个
    报告链路。
    """

    if not can_use_llm(config):
        return None

    try:
        chat_content = _load_chat_content()
        content = chat_content(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=config.temperature,
            max_tokens=config.max_tokens if config.max_tokens > 0 else None,
            timeout=config.llm_timeout,
        )
        return parse_json_payload(content or "")
    except Exception as exc:
        if config.verbose and config.progress_printer:
            config.progress_printer(
                f"[writing-agent] LLM JSON call failed, using fallback: {exc}"
            )
        return None


def clean_text(value: Any, max_chars: int = 0) -> str:
    """统一做空值、空白和长度处理。"""

    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    no_truncate = os.getenv("REPORT_AGENT_NO_TRUNCATE", "1").strip().lower()
    truncate_enabled = no_truncate in {"0", "false", "no", "off"}
    if truncate_enabled and max_chars and len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text


def clamp_confidence(value: Any, default: float = 0.7) -> float:
    """把置信度限制在 0-1 范围内。"""

    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    return max(0.0, min(1.0, score))


def valid_ids(values: Any, allowed: set[str]) -> list[str]:
    """过滤出当前上下文允许的 id，并保持原顺序去重。"""

    if not isinstance(values, list):
        return []
    ids: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if item in allowed and item not in ids:
            ids.append(item)
    return ids
