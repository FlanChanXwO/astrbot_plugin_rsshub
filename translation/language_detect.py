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

    # 混合语言检测：计算目标语言在文本中的比例
    # 即使主要检测语言是目标语言，但如果目标语言字符比例不够高，仍然需要翻译
    target_ratio = calculate_target_language_ratio(text_sample, target_lang)

    # 如果目标语言比例超过 85%，认为不需要翻译
    if target_ratio >= 0.85:
        return False

    # 如果目标语言比例在 50%-85% 之间，需要更仔细判断
    if target_ratio >= 0.50:
        # 检查是否包含明显的外语单词（拉丁字母连续出现）
        foreign_word_ratio = detect_foreign_words(text_sample, target_lang)
        if foreign_word_ratio < 0.10:  # 外语单词少于 10%
            return False

    return True


def calculate_target_language_ratio(text: str, target_lang: str) -> float:
    """计算文本中目标语言字符的比例。

    Args:
        text: 要分析的文本
        target_lang: 目标语言代码

    Returns:
        目标语言字符比例 (0.0 - 1.0)
    """
    if not text:
        return 0.0

    # 移除空白字符进行计算
    clean_text = text.replace(" ", "").replace("\n", "").replace("\t", "")
    total_chars = len(clean_text)

    if total_chars == 0:
        return 0.0

    target_count = 0

    if target_lang in ("zh-CN", "zh-TW", "zh"):
        # 中文目标：中文字符 + 常见中文标点
        target_count = len(CJK_CHARS.findall(clean_text))
        # 也计算常见中文标点
        chinese_punct = re.findall(r'[。，、；：""' "（）《》【】？！]", clean_text)
        target_count += len(chinese_punct)
    elif target_lang in ("ja", "jp"):
        # 日文目标：平假名 + 片假名 + 汉字（CJK）
        target_count = (
            len(HIRAGANA.findall(clean_text))
            + len(KATAKANA.findall(clean_text))
            + len(CJK_CHARS.findall(clean_text))
        )
    elif target_lang in ("ko", "kr"):
        # 韩文目标：韩文字符
        target_count = len(HANGUL.findall(clean_text))
    elif target_lang == "en":
        # 英文目标：拉丁字母
        target_count = len(LATIN_CHARS.findall(clean_text))

    return target_count / total_chars


def detect_foreign_words(text: str, target_lang: str) -> float:
    """检测文本中外语单词的比例。

    主要用于检测拉丁字母单词（英文等）在非拉丁目标语言文本中的比例。

    Args:
        text: 要分析的文本
        target_lang: 目标语言代码

    Returns:
        外语单词比例 (0.0 - 1.0)
    """
    if not text:
        return 0.0

    # 对于英文目标语言，不需要检测外语单词
    if target_lang == "en":
        return 0.0

    # 查找所有拉丁字母单词（2个字母以上）
    words = re.findall(r"[a-zA-Z]{2,}", text)
    total_words = len(words)

    if total_words == 0:
        return 0.0

    # 获取所有字符数（排除空白）
    clean_text = text.replace(" ", "").replace("\n", "").replace("\t", "")
    total_chars = len(clean_text)

    if total_chars == 0:
        return 0.0

    # 计算拉丁字母字符数
    latin_chars = len(LATIN_CHARS.findall(clean_text))

    return latin_chars / total_chars


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
