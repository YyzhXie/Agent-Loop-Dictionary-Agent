"""Command-line interface and top-level error handling."""

from __future__ import annotations

import sys

try:
    from openai import OpenAI, OpenAIError
except ImportError as exc:  # pragma: no cover - depends on the local environment
    raise SystemExit(
        '缺少 openai 依赖，请先运行：python -m pip install "openai>=1.0"'
    ) from exc

from .config import BASE_URL
from .credentials import load_api_key
from .loop import run_agent

__all__ = ["main"]


def _configure_utf8() -> None:
    """Keep Chinese output readable in Windows terminals and redirected pipes."""
    if not hasattr(sys.stdout, "reconfigure"):
        return
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (OSError, ValueError):
        pass


def main() -> int:
    """Read one word, run the agent, and print its final answer."""
    _configure_utf8()

    try:
        word = input("请输入一个英语单词：").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        return 1

    if not word:
        print("请输入一个英语单词。")
        return 1

    try:
        client = OpenAI(api_key=load_api_key(), base_url=BASE_URL)
        print(run_agent(client, word))
    except RuntimeError as exc:
        print(f"配置错误：{exc}")
        return 1
    except OpenAIError as exc:
        print(f"模型调用失败：{exc}")
        return 1
    except KeyboardInterrupt:
        print("\n已取消。")
        return 1
    except Exception as exc:
        print(f"运行失败：{exc}")
        return 1

    return 0
