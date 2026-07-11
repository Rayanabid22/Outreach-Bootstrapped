"""Shared Claude API helper: web-search-enabled calls, JSON parsing,
response logging, and usage accounting.

Shared module — identical to ic_pipeline/claude_client.py in the funded
pipeline (Rayanabid22/IC-Outreach). Keep the two in sync.
"""

import json
import os
import re
import time
from datetime import datetime

import anthropic

import config
from .models import RunStats

_client = anthropic.Anthropic()

_MAX_CONTINUATIONS = 5  # pause_turn resumes for server-side tool loops


def _log_response(tag: str, response) -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = os.path.join(config.LOG_DIR, f"{stamp}_{tag}.json")
    try:
        with open(path, "w") as fh:
            fh.write(response.to_json())
    except Exception as exc:
        print(f"    [claude] failed to write log {path}: {exc}")


def _account(stats: RunStats, response) -> None:
    stats.api_calls += 1
    stats.input_tokens += response.usage.input_tokens
    stats.output_tokens += response.usage.output_tokens
    stats.web_searches += sum(
        1
        for block in response.content
        if block.type == "server_tool_use" and block.name == "web_search"
    )


def call_claude(prompt: str, stats: RunStats, max_searches: int, tag: str) -> str:
    """One web-search-enabled Claude call. Returns the response text.

    Handles pause_turn continuations (server-side tool iteration limit) and
    retries rate limits / transient server errors with backoff.
    """
    messages = [{"role": "user", "content": prompt}]
    tools = [
        {
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": max_searches,
        }
    ]

    response = None
    for continuation in range(_MAX_CONTINUATIONS + 1):
        response = _create_with_retry(messages=messages, tools=tools)
        _log_response(tag, response)
        _account(stats, response)
        if response.stop_reason != "pause_turn":
            break
        # Server-side tool loop paused; append assistant turn and resume.
        messages = messages + [{"role": "assistant", "content": response.content}]

    return "".join(block.text for block in response.content if block.type == "text")


def _create_with_retry(**kwargs):
    delay = 5
    last_exc = None
    for attempt in range(5):
        try:
            return _client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=8000,
                **kwargs,
            )
        except anthropic.RateLimitError as exc:
            last_exc = exc
            retry_after = int(exc.response.headers.get("retry-after", delay))
            print(f"    [claude] rate limited, waiting {retry_after}s...")
            time.sleep(retry_after)
        except anthropic.APIStatusError as exc:
            if exc.status_code < 500:
                raise
            last_exc = exc
            print(f"    [claude] server error {exc.status_code}, retrying in {delay}s...")
            time.sleep(delay)
        delay = min(delay * 2, 60)
    raise last_exc


def parse_json_block(text: str):
    """Extract the first JSON array or object from a model response."""
    # Strip markdown fences if present.
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None
