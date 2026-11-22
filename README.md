# Agent Loop Dictionary Agent

English | [简体中文](README_zh.md)

A minimal, modular dictionary agent built from scratch with Python and the [OpenAI Python SDK](https://github.com/openai/openai-python). It demonstrates a real tool-calling Agent Loop: the model receives one English word, calls the `lookup_word` tool, reads the tool result, and writes a fixed-format Chinese dictionary entry.

## Features

- **Modular package** — `agent.py` is a thin entry point; configuration, credentials, Youdao integration, the Agent Loop, and the CLI live in separate modules.
- **Real Agent Loop** — up to 10 model turns, with tool results appended back into the conversation until the model stops requesting tools.
- **One tool** — `lookup_word(word)` queries Youdao Dictionary and returns a normalized JSON string.
- **Strict tool schema** — the function definition uses `strict: True`.
- **Deterministic output contract** — the final answer follows a fixed Chinese layout, and missing sections are written as `无` instead of being invented.
- **No hard-coded secret** — the API key is resolved at runtime and never printed.
- **Graceful failures** — network, HTTP, JSON, and model errors are reported without crashing the formatting contract.

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

1. `refs.DEEPSEEK_API_KEY` in the DeepSeek Harness credentials file (`%USERPROFILE%\.dsh\.credentials.yaml`, or `$DSH_HOME/.credentials.yaml`). This is the custom DeepSeek API key added in Harness.
2. `DEEPSEEK_API_KEY` environment variable.
3. `DEEPSEEK_ACCOUNT_API_KEY` environment variable (account API fallback).
4. The DeepSeek account token in the Harness credentials file (`deepseek-account-platform/default` → `payload.token`) as a last-resort fallback.

The custom Harness key is therefore preferred whenever it can be read. If the Harness credentials are unavailable, the environment and account fallbacks are tried next. If no key can be found, the script prints setup instructions and exits.

> The key is only passed to the OpenAI client. It is not logged, written to disk, or included in tool output.

## Run

```powershell
# Standard entry point
python agent.py

# Equivalent package entry point
python -m dictionary_agent
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

- If a whole section is absent from the API response, print `无` for that section.
- If the phonetic field is absent, omit the `音标` line entirely.
- The model must not invent meanings, examples, phonetics, or inflections.
- If the tool returns `{"error": ...}`, the model reports the failure and its reason instead of fabricating a dictionary entry.

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

Every field is always present. Missing data is represented by an empty string or an empty list, never by an exception. On HTTP or JSON failure the tool returns:

```json
{"error": "查询失败: <reason>"}
```

Data is extracted with this priority:

| Field | Primary source | Fallbacks |
| --- | --- | --- |
| Phonetic | `ec.word[0].usphone` / `ukphone` | `simple.word[0]` |
| Meanings | `ec.word[*].trs[*].tr[0].l.i[0]` | `simple`, then `web_trans` |
| Examples | `auth_sents_part.sent` | `blng_sents_part.sent` or `sentence-pair` |
| Derivatives | `simple.wfs` | `ec.word[0].wfs` |

The live Youdao response often returns authoritative sentences with only an English `foreign` field and no Chinese `zh` field. The tool skips such incomplete pairs and falls back to the bilingual `blng_sents_part` entries (`sentence` / `sentence-translation`), so it never invents a translation. It also accepts the flat `{"w": ..., "name": ...}` derivative form from the task spec and the live nested `{"wf": {"name": ..., "value": ...}}` form.

The Youdao response may start with a JSONP-like prefix such as `@(#)@`; the tool strips everything before the first `{` and after the last `}` before calling `json.loads`.

## Model

The model is `deepseek-flash`, with `base_url` set to `https://api.deepseek.com`.

The original request specified `deepseek-v4.1-flash`. During integration the available custom key rejected that name with HTTP 400 and stated that only `deepseek-flash` and `deepseek-v4-pro` were supported, so `deepseek-flash` was selected after confirmation. If your account later exposes `deepseek-v4.1-flash`, update the `MODEL` constant in `dictionary_agent/config.py`.

## Verification

Tested on 2026-11-22 with the local Python 3.14.10, `openai` 3.57.0, the Harness custom key, and `deepseek-flash`:

| Check | Result |
| --- | --- |
| `lookup_word("apple")` | Live Youdao data: phonetic, one meaning, three bilingual examples, `复数：apples` |
| `python agent.py` with `apple` | Exact fixed-format dictionary output through the thin entry point |
| `python -m dictionary_agent` | Package entry point starts and prints the expected dictionary format |
| Modular imports | All package modules compile and import under the PyCharm `.venv` |
| Unknown word | Phonetic line omitted; `中文含义`, `例句`, and `派生词` each show `无` |
| JSONP and fallback schemas | `@(#)@` prefix stripped; flat/nested derivatives and `web_trans` fallback parsed |
| Simulated tool error | `查询失败: 模拟网络故障` with no duplicated prefix |
| Ten-turn loop stub | Returned `达到最大轮次，任务未完成` after exactly 10 model calls |
| HTTP error path | `{"error": "查询失败: HTTP 404"}` |
| Non-JSON path | `{"error": "查询失败: JSON 解析失败: ..."}` |

No API key was printed or committed during verification.

## Project structure

```text
.
├── agent.py
├── dictionary_agent/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── credentials.py
│   ├── loop.py
│   └── youdao.py
├── README.md
└── README_zh.md
```

| Module | Responsibility |
| --- | --- |
| `agent.py` | Thin executable entry point; delegates to the CLI. |
| `dictionary_agent/__main__.py` | Enables `python -m dictionary_agent`. |
| `dictionary_agent/cli.py` | Reads one word, builds the client, prints the answer, and handles user-facing errors. |
| `dictionary_agent/config.py` | Model, endpoint, turn limit, system prompt, and strict tool schema. |
| `dictionary_agent/credentials.py` | Reads Harness credentials and resolves the API key fallback order. |
| `dictionary_agent/loop.py` | Runs the Agent Loop, dispatches tool calls, and returns the final text. |
| `dictionary_agent/youdao.py` | Calls Youdao, strips JSONP, and normalizes dictionary data. |

## Notes

- Youdao's `jsonapi` endpoint is an unofficial public endpoint and may change without notice.
- This is an educational Agent Loop example, not a production dictionary service.
