"""Configuration and model-facing prompts for the dictionary agent."""

from __future__ import annotations

# DeepSeek exposes an OpenAI-compatible chat completions API.
MODEL = "deepseek-flash"
BASE_URL = "https://api.deepseek.com"
MAX_TURNS = 10

# The prompt owns the output contract; the loop only routes tool results.
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
2. 中文含义、例句、派生词中某一类为空时，在对应标题后直接写“无”（例如“中文含义：无”），不要加项目符号。
3. 不得编造释义、音标、例句、翻译或词形变化。
4. 如果工具返回 error，直接原样输出 error 字段的内容；它已经以“查询失败:”开头，不要重复添加前缀，也不要输出词典格式或猜测。
5. 只输出最终词典内容，不要输出 Markdown 代码块或额外解释。"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_word",
            "description": "查询一个英语单词的有道词典音标、中文释义、双语例句和派生词。",
            # Strict mode requires the additionalProperties flag below.
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
