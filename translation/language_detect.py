"""Language detection utilities."""

from __future__ import annotations

import re

# Simple language detection patterns
LANG_PATTERNS = {
    "zh-CN": [
        r"[\u4e00-\u9fff]",  # CJK Unified Ideographs
    ],
    "ja": [
        r"[\u3040-\u309f]",  # Hiragana
        r"[\u30a0-\u30ff]",  # Katakana
    ],
    "ko": [
        r"[\uac00-\ud7af]",  # Korean Hangul Syllables
    ],
    "en": [
        r"^[a-zA-Z\s\p{P}]+$",  # Latin only
    ],
}

# Character ranges for detection
CJK_CHARS = re.compile(r"[\u4e00-\u9fff]")
HIRAGANA = re.compile(r"[\u3040-\u309f]")
KATAKANA = re.compile(r"[\u30a0-\u30ff]")
HANGUL = re.compile(r"[\uac00-\ud7af]")
LATIN_CHARS = re.compile(r"[a-zA-Z]")


def should_translate(
    text: str,
    target_lang: str,
    force_translate: bool = False,
) -> bool:
    """Determine if text should be translated.

    Args:
        text: Text to check
        target_lang: Target language code
        force_translate: If True, always translate

    Returns:
        True if should translate, False otherwise
    """
    if not text or not text.strip():
        return False

    if force_translate:
        return True

    text_sample = text[:500]  # Use first 500 chars for detection

    # Detect primary language
    detected = detect_language_simple(text_sample)

    if detected is None:
        # Could not detect, assume needs translation
        return True

    # Don't translate if already in target language
    if detected == target_lang:
        return False

    # For Chinese variants
    if target_lang in ("zh-CN", "zh-TW") and detected in ("zh-CN", "zh-TW"):
        return False

    return True


def detect_language_simple(text: str) -> str | None:
    """Simple rule-based language detection.

    Returns:
        Language code or None if unknown
    """
    if not text or not text.strip():
        return None

    # Count characters
    cjk_count = len(CJK_CHARS.findall(text))
    hiragana_count = len(HIRAGANA.findall(text))
    katakana_count = len(KATAKANA.findall(text))
    hangul_count = len(HANGUL.findall(text))
    latin_count = len(LATIN_CHARS.findall(text))
    total_chars = len(text.replace(" ", "").replace("\n", ""))

    if total_chars == 0:
        return None

    # Japanese: has hiragana or katakana
    if hiragana_count > 0 or katakana_count > 0:
        return "ja"

    # Korean: has hangul
    if hangul_count > 0:
        return "ko"

    # Chinese: has CJK characters (but no Japanese/Korean specific chars)
    if cjk_count > total_chars * 0.3:
        return "zh-CN"

    # English/Latin: mostly latin characters
    if latin_count > total_chars * 0.5:
        return "en"

    # Could not determine
    return None


def normalize_lang_code(lang_code: str) -> str:
    """Normalize language code to our standard format.

    Args:
        lang_code: Input language code

    Returns:
        Normalized language code
    """
    if not lang_code:
        return "zh-CN"

    lang_map = {
        "zh": "zh-CN",
        "zh-cn": "zh-CN",
        "zh_CN": "zh-CN",
        "zh-tw": "zh-TW",
        "zh_tw": "zh-TW",
        "zh-hans": "zh-CN",
        "zh-hant": "zh-TW",
        "en": "en",
        "en-us": "en",
        "en-gb": "en",
        "ja": "ja",
        "jp": "ja",
        "ko": "ko",
        "kr": "ko",
    }

    normalized = lang_code.lower().strip()
    return lang_map.get(normalized, lang_code)
