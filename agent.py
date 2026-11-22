"""A minimal Agent Loop dictionary agent built on the OpenAI Python SDK."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from openai import OpenAI

MODEL = "deepseek-flash"
BASE_URL = "https://api.deepseek.com"
MAX_TURNS = 10

SYSTEM_PROMPT = """你是一个英语词典助手。用户给出一个英语单词后，你必须调用 `lookup_word` 工具查询，然后严格按以下格式输出：

单词：<word>
音标：<如果接口返回则展示，否则省略此行>
中文含义：
- <词性 + 释义，每条一行>
例句：
- <英文例句>
  译文：<中文翻译>
派生词：
- <词形变化名称：形式，例如“复数：apples”>

输出规则：
1. 音标行只在工具返回的 phonetic 非空时输出，否则整行省略。
2. 中文含义、例句、派生词中某一类为空时，在对应标题下写“无”。
3. 不得编造释义、音标、例句、翻译或词形变化。
4. 如果工具返回 error，只回复“查询失败：<原因>”，不要输出词典格式，也不要猜测。
5. 只输出最终词典内容，不要输出 Markdown 代码块或额外解释。"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_word",
            "description": "查询一个英语单词的有道词典音标、中文释义、双语例句和派生词。",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "word": {
                        "type": "string",
                        "description": "要查询的英语单词。",
                    }
                },
                "required": ["word"],
                "additionalProperties": False,
            },
        },
    }
]


def _parse_simple_yaml(text: str) -> dict:
    """Parse the small mapping-only YAML subset used by DSH credentials."""
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
    dsh_home = os.environ.get("DSH_HOME")
    path = Path(dsh_home) / ".credentials.yaml" if dsh_home else Path.home() / ".dsh" / ".credentials.yaml"
    try:
        return _parse_simple_yaml(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return {}


def load_api_key() -> str:
    """Resolve the custom Harness key first, then fall back to the account key."""
    credentials = _read_harness_credentials()
    refs = credentials.get("refs", {})
    records = credentials.get("records", {})
    account = records.get("deepseek-account-platform/default", {}).get("payload", {})

    candidates = [
        os.environ.get("DEEPSEEK_API_KEY", ""),
        refs.get("DEEPSEEK_API_KEY", "") if isinstance(refs, dict) else "",
        os.environ.get("DEEPSEEK_ACCOUNT_API_KEY", ""),
        account.get("token", "") if isinstance(account, dict) else "",
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    raise RuntimeError("未找到 DeepSeek API Key。")


def lookup_word(word: str) -> str:
    """Query Youdao and return a normalized JSON string."""
    # The dictionary integration is added in the next stage.
    raise NotImplementedError


def build_messages(word: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": word},
    ]


def run_agent(client: OpenAI, word: str) -> None:
    messages = build_messages(word)
    for _ in range(MAX_TURNS):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        message = response.choices[0].message
        if not message.tool_calls:
            print((message.content or "").strip())
            return

        messages.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in message.tool_calls
                ],
            }
        )
        for call in message.tool_calls:
            arguments = json.loads(call.function.arguments or "{}")
            result = lookup_word(arguments["word"])
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                }
            )

    print("达到最大轮次，任务未完成")


def main() -> int:
    word = input("请输入一个英语单词：").strip()
    if not word:
        print("请输入一个英语单词。")
        return 1
    try:
        api_key = load_api_key()
        client = OpenAI(api_key=api_key, base_url=BASE_URL)
        run_agent(client, word)
    except Exception as exc:
        print(f"运行失败：{exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
