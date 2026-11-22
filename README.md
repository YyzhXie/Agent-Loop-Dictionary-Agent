# Agent Loop Dictionary Agent

English | [简体中文](README_zh.md)

A minimal, single-file dictionary agent built from scratch with Python and the
[OpenAI Python SDK](https://github.com/openai/openai-python). It demonstrates a
real tool-calling Agent Loop: the model receives one English word, calls the
`lookup_word` tool, reads the tool result, and writes a fixed-format Chinese
dictionary entry.

## Features

- **One source file** — all application code lives in `agent.py`.
- **Real Agent Loop** — up to 10 model turns, with tool results appended back
  into the conversation until the model stops requesting tools.
- **One tool** — `lookup_word(word)` queries Youdao Dictionary and returns a
  normalized JSON string.
- **Strict tool schema** — the function definition uses `strict: True`.
- **Deterministic output contract** — the final answer follows a fixed Chinese
  layout, and missing sections are written as `无` instead of being invented.
- **No hard-coded secret** — the API key is resolved at runtime and never
  printed.
- **Graceful failures** — network, HTTP, JSON, and model errors are reported
  without crashing the formatting contract.

## Requirements

- Python 3.12+ (the development machine used its local Python 3.14.10).
- The `openai` package (`openai>=1.0`).
- Network access to `https://api.deepseek.com` and
  `https://dict.youdao.com/jsonapi`.

## Setup

```powershell
# Create and activate a virtual environment (recommended)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install the only third-party dependency
python -m pip install "openai>=1.0"
```

On macOS/Linux, activate with `source .venv/bin/activate`.

## API key resolution

The script never stores an API key in the repository. It resolves the key in
this order:

1. `DEEPSEEK_API_KEY` environment variable.
2. `refs.DEEPSEEK_API_KEY` in the DeepSeek Harness credentials file
   (`%USERPROFILE%\.dsh\.credentials.yaml`, or `$DSH_HOME/.credentials.yaml`).
   This is the custom DeepSeek API key added in Harness.
3. `DEEPSEEK_ACCOUNT_API_KEY` environment variable (account API fallback).
4. The DeepSeek account token in the Harness credentials file
   (`deepseek-account-platform/default` → `payload.token`) as a last-resort
   fallback.

The custom Harness key is therefore used automatically when no environment
variable overrides it. If no key can be found, the script prints setup
instructions and exits.

> The key is only passed to the OpenAI client. It is not logged, written to
> disk, or included in tool output.

## Run

```powershell
python agent.py
```

Then enter one English word:

```text
请输入一个英语单词：apple
```

## Output format

```text
单词：<word>
音标：<if returned by the API; omit this line otherwise>
中文含义：
- <part of speech + definition, one per line>
例句：
- <English example>
  译文：<Chinese translation>
派生词：
- <inflection name: form, e.g. "复数：apples">
```

Rules:

- If a whole section is absent from the API response, print `无` for that
  section.
- If the phonetic field is absent, omit the `音标` line entirely.
- The model must not invent meanings, examples, phonetics, or inflections.
- If the tool returns `{"error": ...}`, the model reports the failure and its
  reason instead of fabricating a dictionary entry.

## How the Agent Loop works

1. Read one word from the command line.
2. Seed `messages` with a system prompt and the user's word.
3. Send the full conversation plus `tools` and `tool_choice: "auto"` to the
   model.
4. If the model returns `tool_calls`, run `lookup_word`, append an assistant
   message and one `role="tool"` message per call, then repeat.
5. If the model returns no tool calls, print the final answer and exit.
6. If 10 turns are exhausted, print `达到最大轮次，任务未完成` and exit.

## Tool result schema

`lookup_word` always returns a JSON string:

```json
{
  "word": "apple",
  "phonetic": "英 /ˈæp(ə)l/ 美 /ˈæp(ə)l/",
  "meanings": ["n. 苹果"],
  "examples": [{"en": "An apple a day keeps the doctor away.", "zh": "一天一苹果，医生远离我。"}],
  "derivatives": [{"name": "复数", "form": "apples"}]
}
```

Every field is always present. Missing data is represented by an empty string
or an empty list, never by an exception. On HTTP or JSON failure the tool
returns:

```json
{"error": "查询失败: <reason>"}
```

Data is extracted with this priority:

| Field | Primary source | Fallbacks |
| --- | --- | --- |
| Phonetic | `ec.word[0].usphone` / `ukphone` | `simple.word[0]` |
| Meanings | `ec.word[*].trs[*].tr[0].l.i[0]` | `simple`, then `web_trans` |
| Examples | `auth_sents_part.sent` | `blng_sents_part.sent` |
| Derivatives | `simple.wfs` | `ec.word[0].wfs` |

The Youdao response may start with a JSONP-like prefix such as `@(#)@`; the
tool strips everything before the first `{` and after the last `}` before
calling `json.loads`.

## Model

The model is `deepseek-flash`, with `base_url` set to
`https://api.deepseek.com`.

The original request specified `deepseek-v4.1-flash`. During integration the
available custom key rejected that name with HTTP 400 and stated that only
`deepseek-flash` and `deepseek-v4-pro` were supported, so `deepseek-flash` was
selected after confirmation. If your account later exposes
`deepseek-v4.1-flash`, update the `MODEL` constant in `agent.py`.

## Project structure

```text
.
├── agent.py
├── README.md
└── README_zh.md
```

## Notes

- Youdao's `jsonapi` endpoint is an unofficial public endpoint and may change
  without notice.
- This is an educational Agent Loop example, not a production dictionary
  service.
