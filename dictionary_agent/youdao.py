"""Youdao dictionary integration and response normalization."""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

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

__all__ = ["lookup_word"]


# ---------------------------------------------------------------------------
# Response extraction helpers
# ---------------------------------------------------------------------------


def _clean_text(value: object) -> str:
    """Turn a scalar into clean plain text; never raise for missing data."""
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
    """Return word entries from an `ec` or `simple` section."""
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
    # Prefer the English-Chinese dictionary, then simple data and web translations.
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

    # Authoritative examples are preferred, but only complete bilingual pairs
    # are useful. The live API often omits their Chinese translation, so the
    # second section is the practical fallback.
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


# ---------------------------------------------------------------------------
# Public tool
# ---------------------------------------------------------------------------


def lookup_word(word: str) -> str:
    """Query Youdao and return the normalized tool-result JSON string."""
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

    # Youdao may wrap the JSON in a JSONP-like prefix/suffix such as @(#)@.
    # Keeping only the outermost object also tolerates a trailing callback.
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
    except Exception as exc:  # Defensive: bad fields must not break the Agent Loop.
        return _error_result(f"解析响应失败: {exc}")

    return json.dumps(result, ensure_ascii=False)
