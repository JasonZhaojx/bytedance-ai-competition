"""Core web page fetching and text extraction."""

from __future__ import annotations

import html
import json
import re
from typing import Optional

from bs4 import BeautifulSoup
import requests
import trafilatura


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}


def _normalize_text(text: str, max_chars: int) -> str:
    normalized = " ".join(text.split())
    return normalized[:max_chars] if max_chars and max_chars > 0 else normalized


def _walk_json_strings(value) -> list[str]:
    texts = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in {"content", "articlebody", "description", "summary", "abstract", "text"}:
                if isinstance(child, str):
                    texts.append(child)
            texts.extend(_walk_json_strings(child))
    elif isinstance(value, list):
        for child in value:
            texts.extend(_walk_json_strings(child))
    return texts


def _fallback_extract_text(downloaded: str, max_chars: int) -> str:
    candidates: list[str] = []
    soup = BeautifulSoup(downloaded, "lxml")

    for selector in [
        {"property": "og:description"},
        {"name": "description"},
        {"name": "Description"},
    ]:
        tag = soup.find("meta", attrs=selector)
        if tag and tag.get("content"):
            candidates.append(str(tag["content"]))

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates.extend(_walk_json_strings(data))

    for pattern in [
        r'"articleContent"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"content"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"abstract"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"description"\s*:\s*"((?:\\.|[^"\\])*)"',
    ]:
        for match in re.finditer(pattern, downloaded):
            raw = match.group(1)
            try:
                candidates.append(json.loads(f'"{raw}"'))
            except json.JSONDecodeError:
                candidates.append(raw)

    cleaned = []
    seen = set()
    for text in candidates:
        text = html.unescape(str(text))
        text = re.sub(r"<[^>]+>", " ", text)
        text = _normalize_text(text, 0)
        if len(text) < 40 or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return _normalize_text("\n".join(cleaned), max_chars)


def fetch_page_text(
    url: str,
    *,
    proxy: Optional[str] = None,
    timeout: int = 10,
    max_chars: int = 5000,
    target_language: Optional[str] = None,
    verify_ssl: Optional[bool] = None,
) -> str:
    """Fetch a URL and extract readable main text.

    The function downloads with requests so the caller-provided timeout always
    applies, then uses trafilatura/BeautifulSoup to extract readable text.
    """
    if not url:
        return ""

    proxies = {"http": proxy, "https": proxy} if proxy else None
    should_verify_ssl = (not bool(proxy)) if verify_ssl is None else verify_ssl

    try:
        response = requests.get(
            url,
            headers=DEFAULT_HEADERS,
            proxies=proxies,
            timeout=timeout,
            verify=should_verify_ssl,
        )
        if response.status_code != 200:
            return ""
        response.encoding = response.apparent_encoding
        downloaded = response.text

        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            target_language=target_language,
        )
        if text:
            return _normalize_text(text, max_chars)
        return _fallback_extract_text(downloaded, max_chars)
    except Exception:
        return ""
