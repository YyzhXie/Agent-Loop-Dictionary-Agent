"""A minimal Agent Loop dictionary agent built on the OpenAI Python SDK."""

from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from openai import OpenAI, OpenAIError
except ImportError as exc:  # pragma: no cover - only hit when dependencies are missing
    print("缺少 openai 依赖，请先运行：python -m pip install \"openai>=1.0\"", file=sys.stderr)
    raise SystemExit(1) from exc

MODEL = "deepseek-flash"
BASE_URL = "https://api.deepseek.com"
MAX_TURNS = 10

DICT_URL = "https://dict.youdao.com/jsonapi"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
HTTP_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.youdao.com/",
}

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


# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------


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
    path = (
        Path(dsh_home) / ".credentials.yaml"
        if dsh_home
        else Path.home() / ".dsh" / ".credentials.yaml"
    )
    try:
        return _parse_simple_yaml(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return {}


def load_api_key() -> str:
    """Resolve the custom Harness key first, then fall back to the account key."""
    credentials = _read_harness_credentials()
    refs = credentials.get("refs", {})
    records = credentials.get("records", {})
    account_record = (
        records.get("deepseek-account-platform/default", {})
        if isinstance(records, dict)
        else {}
    )
    account_payload = (
        account_record.get("payload", {}) if isinstance(account_record, dict) else {}
    )

    candidates = [
        refs.get("DEEPSEEK_API_KEY", "") if isinstance(refs, dict) else "",
        os.environ.get("DEEPSEEK_API_KEY", ""),
        os.environ.get("DEEPSEEK_ACCOUNT_API_KEY", ""),
        account_payload.get("token", "") if isinstance(account_payload, dict) else "",
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    raise RuntimeError(
        "未找到 DeepSeek API Key。请设置 DEEPSEEK_API_KEY，"
        "或在 DeepSeek Harness 中添加自定义 DeepSeek API。"
    )


# ---------------------------------------------------------------------------
# Youdao response extraction
# ---------------------------------------------------------------------------


def _clean_text(value: object) -> str:
    """Turn a scalar into clean plain text; never raise for missing data."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return ""
    text = html.unescape(value)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _as_list(value: object) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _word_entries(section: object) -> list[dict]:
    """Return the word entries of an `ec` / `simple` section."""
    if not isinstance(section, dict):
        return []
    raw_words = section.get("word")
    if isinstance(raw_words, dict):
        return [raw_words]
    entries = [item for item in _as_list(raw_words) if isinstance(item, dict)]
    if entries:
        return entries
    if any(key in section for key in ("trs", "wfs", "usphone", "ukphone")):
        return [section]
    return []


def _add_unique(target: list[str], value: str) -> None:
    if value and value not in target:
        target.append(value)


def _meanings_from_entries(entries: list[dict]) -> list[str]:
    meanings: list[str] = []
    for entry in entries:
        for trs in _as_list(entry.get("trs")):
            if isinstance(trs, str):
                _add_unique(meanings, _clean_text(trs))
                continue
            if not isinstance(trs, dict):
                continue
            for tr in _as_list(trs.get("tr")):
                if isinstance(tr, str):
                    _add_unique(meanings, _clean_text(tr))
                    continue
                if not isinstance(tr, dict):
                    continue
                level = tr.get("l")
                if not isinstance(level, dict):
                    continue
                for item in _as_list(level.get("i")):
                    if isinstance(item, str):
                        _add_unique(meanings, _clean_text(item))
                    elif isinstance(item, dict):
                        _add_unique(meanings, _clean_text(item.get("i")))
    return meanings


def _extract_meanings(data: dict) -> list[str]:
    meanings = _meanings_from_entries(_word_entries(data.get("ec")))
    if meanings:
        return meanings

    meanings = _meanings_from_entries(_word_entries(data.get("simple")))
    if meanings:
        return meanings

    web_trans = data.get("web_trans")
    if isinstance(web_trans, dict):
        translations = web_trans.get("web-translation") or web_trans.get(
            "web_translation"
        )
        for item in _as_list(translations):
            if not isinstance(item, dict):
                continue
            for trans in _as_list(item.get("trans")):
                if isinstance(trans, dict):
                    _add_unique(meanings, _clean_text(trans.get("value")))
    return meanings


def _format_phonetic(value: str) -> str:
    value = value.strip().strip("/")
    return f"/{value}/" if value else ""


def _extract_phonetic(data: dict) -> str:
    for section_name in ("ec", "simple"):
        for entry in _word_entries(data.get(section_name)):
            uk = _clean_text(
                entry.get("ukphone") or entry.get("ukphonetic") or entry.get("phonetic")
            )
            us = _clean_text(
                entry.get("usphone") or entry.get("usphonetic") or entry.get("phonetic")
            )
            if uk and us:
                return f"英 {_format_phonetic(uk)} 美 {_format_phonetic(us)}"
            if uk or us:
                return _format_phonetic(uk or us)
    return ""


def _first_text(item: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        text = _clean_text(item.get(key))
        if text:
            return text
    return ""


def _extract_examples(data: dict) -> list[dict[str, str]]:
    examples: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for section_name in ("auth_sents_part", "blng_sents_part"):
        section = data.get(section_name)
        if not isinstance(section, dict):
            continue
        sentences = (
            section.get("sent")
            or section.get("sentence-pair")
            or section.get("sentence_pair")
            or []
        )
        for sentence in _as_list(sentences):
            if not isinstance(sentence, dict):
                continue
            english = _first_text(
                sentence, ("en", "foreign", "sentence", "sentence-eng")
            )
            chinese = _first_text(
                sentence, ("zh", "sentence-translation", "translation")
            )
            if not english or not chinese:
                continue
            key = (english, chinese)
            if key not in seen:
                seen.add(key)
                examples.append({"en": english, "zh": chinese})
        if examples:
            return examples

    return examples


def _extract_derivatives(data: dict) -> list[dict[str, str]]:
    sources: list[object] = []
    simple = data.get("simple")
    if isinstance(simple, dict):
        sources.append(simple.get("wfs"))
        for entry in _word_entries(simple):
            sources.append(entry.get("wfs"))
    for entry in _word_entries(data.get("ec")):
        sources.append(entry.get("wfs"))

    for raw_items in sources:
        derivatives: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in _as_list(raw_items):
            name = ""
            form = ""
            if isinstance(item, dict):
                nested = item.get("wf")
                if isinstance(nested, dict):
                    name = _clean_text(nested.get("name"))
                    form = _clean_text(nested.get("value"))
                else:
                    name = _clean_text(item.get("name"))
                    form = _clean_text(
                        item.get("w") or item.get("form") or item.get("value")
                    )
            elif isinstance(item, str):
                form = _clean_text(item)
            if not form:
                continue
            derivative = {"name": name or "词形变化", "form": form}
            key = (derivative["name"], derivative["form"])
            if key not in seen:
                seen.add(key)
                derivatives.append(derivative)
        if derivatives:
            return derivatives

    return []


def _error_result(reason: str) -> str:
    return json.dumps({"error": f"查询失败: {reason}"}, ensure_ascii=False)


def lookup_word(word: str) -> str:
    """Query Youdao and return a normalized JSON string."""
    word = str(word or "").strip()
    if not word:
        return _error_result("单词不能为空")

    query = urllib.parse.urlencode({"q": word})
    request = urllib.request.Request(
        f"{DICT_URL}?{query}", headers=HTTP_HEADERS, method="GET"
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = response.getcode()
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read()
    except urllib.error.HTTPError as exc:
        return _error_result(f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        return _error_result(f"网络请求失败: {exc.reason}")
    except (TimeoutError, OSError) as exc:
        return _error_result(f"网络请求失败: {exc}")

    if status != 200:
        return _error_result(f"HTTP {status}")

    try:
        text = body.decode(charset, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return _error_result("响应中未找到 JSON")

    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        return _error_result(f"JSON 解析失败: {exc.msg}")
    if not isinstance(data, dict):
        return _error_result("JSON 顶层结构不是对象")

    try:
        result = {
            "word": word,
            "phonetic": _extract_phonetic(data),
            "meanings": _extract_meanings(data),
            "examples": _extract_examples(data),
            "derivatives": _extract_derivatives(data),
        }
    except Exception as exc:  # defensive: missing fields must not break the agent
        return _error_result(f"解析响应失败: {exc}")

    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Agent Loop
# ---------------------------------------------------------------------------


def build_messages(word: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": word},
    ]


def _tool_result(call) -> str:
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
    content = content.strip()
    if content.startswith("```") and content.endswith("```"):
        lines = content.splitlines()
        if len(lines) >= 2:
            content = "\n".join(lines[1:-1]).strip()
    return content


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
            answer = _clean_final_answer(message.content or "")
            print(answer or "无")
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
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": _tool_result(call),
                }
            )

    print("达到最大轮次，任务未完成")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass

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
        run_agent(client, word)
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


if __name__ == "__main__":
    sys.exit(main())
