"""Resolve the DeepSeek API key, preferring credentials stored by DSH."""

from __future__ import annotations

import os
from pathlib import Path


def _parse_simple_yaml(text: str) -> dict:
    """Parse the small mapping-only YAML subset used by DSH credentials.

    The credentials file contains nested mappings and scalar values, but no
    lists or anchors, so a tiny indentation-based parser avoids PyYAML.
    """
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            continue

        key, _, value = line.partition(":")
        key = key.strip().strip("'\"")
        value = value.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if not value:
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            parent[key] = value

    return root


def _read_harness_credentials() -> dict:
    """Read DSH's credentials file; return an empty mapping when unavailable."""
    dsh_home = os.environ.get("DSH_HOME")
    path = (
        Path(dsh_home) / ".credentials.yaml"
        if dsh_home
        else Path.home() / ".dsh" / ".credentials.yaml"
    )
    try:
        return _parse_simple_yaml(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return {}


def _as_mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def load_api_key() -> str:
    """Return the first usable key in the documented fallback order."""
    credentials = _read_harness_credentials()
    refs = _as_mapping(credentials.get("refs"))
    records = _as_mapping(credentials.get("records"))
    account = _as_mapping(records.get("deepseek-account-platform/default"))
    account_payload = _as_mapping(account.get("payload"))

    candidates = [
        refs.get("DEEPSEEK_API_KEY", ""),
        os.environ.get("DEEPSEEK_API_KEY", ""),
        os.environ.get("DEEPSEEK_ACCOUNT_API_KEY", ""),
        account_payload.get("token", ""),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    raise RuntimeError(
        "未找到 DeepSeek API Key。请设置 DEEPSEEK_API_KEY，"
        "或在 DeepSeek Harness 中添加自定义 DeepSeek API。"
    )
