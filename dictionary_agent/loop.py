"""Agent Loop orchestration and tool-call handling."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .config import MAX_TURNS, MODEL, SYSTEM_PROMPT, TOOLS
from .youdao import lookup_word

if TYPE_CHECKING:
    from openai import OpenAI

__all__ = ["build_messages", "run_agent"]


def build_messages(word: str) -> list[dict]:
    """Seed the conversation with the system contract and the user's word."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": word},
    ]


def _tool_result(call: Any) -> str:
    """Validate a model tool call and execute the matching local tool."""
    if call.function.name != "lookup_word":
        return json.dumps(
            {"error": f"查询失败: 未知工具 {call.function.name}"}, ensure_ascii=False
        )

    try:
        arguments = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError as exc:
        return json.dumps(
            {"error": f"查询失败: 工具参数不是有效 JSON: {exc.msg}"},
            ensure_ascii=False,
        )

    if not isinstance(arguments, dict):
        return json.dumps(
            {"error": "查询失败: 工具参数必须是对象"}, ensure_ascii=False
        )

    word = arguments.get("word")
    if not isinstance(word, str) or not word.strip():
        return json.dumps(
            {"error": "查询失败: 缺少字符串参数 word"}, ensure_ascii=False
        )

    return lookup_word(word)


def _clean_final_answer(content: str) -> str:
    """Remove an accidental Markdown fence from the model's final answer."""
    content = content.strip()
    if content.startswith("```") and content.endswith("```"):
        lines = content.splitlines()
        if len(lines) >= 2:
            content = "\n".join(lines[1:-1]).strip()
    return content


def run_agent(client: "OpenAI", word: str) -> str:
    """Run at most MAX_TURNS model turns and return the text to display."""
    messages = build_messages(word)

    for _ in range(MAX_TURNS):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        message = response.choices[0].message

        # No tool call means the model has produced its final answer.
        if not message.tool_calls:
            answer = _clean_final_answer(message.content or "")
            return answer or "无"

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

        # Append one tool result per call, then continue the loop.
        for call in message.tool_calls:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": _tool_result(call),
                }
            )

    return "达到最大轮次，任务未完成"
