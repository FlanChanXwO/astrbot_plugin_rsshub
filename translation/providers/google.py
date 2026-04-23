"""Google Translate provider using direct HTTP requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp

from ...utils.log_utils import logger
from .base import BaseTranslator

if TYPE_CHECKING:
    from ...config import TranslationConfig


class GoogleTranslator(BaseTranslator):
    """Google Translate provider using direct HTTP requests.

    This implementation avoids the googletrans library dependency conflict
    by making direct HTTP requests to Google Translate API.
    """

    NAME = "google"

    # Mapping from our lang codes to Google Translate lang codes
    LANG_MAP = {
        "zh-CN": "zh-CN",
        "zh-TW": "zh-TW",
        "en": "en",
        "ja": "ja",
        "ko": "ko",
        "fr": "fr",
        "de": "de",
        "es": "es",
        "ru": "ru",
        "pt": "pt",
        "it": "it",
    }

    # Google Translate API endpoint
    API_URL = "https://translate.googleapis.com/translate_a/single"

    def __init__(self, config: TranslationConfig | None = None):
        super().__init__(config)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str | None = None,
    ) -> str | None:
        """Translate text using Google Translate API.

        Args:
            text: Text to translate
            target_lang: Target language code
            source_lang: Source language code (auto-detect if None)

        Returns:
            Translated text or None if failed
        """
        if not text or not text.strip():
            return text

        try:
            dest = self._normalize_lang(target_lang)
            src = self._normalize_lang(source_lang) if source_lang else "auto"

            # Google Translate API parameters
            params = {
                "client": "gtx",
                "sl": src,
                "tl": dest,
                "dt": "t",
                "q": text,
            }

            session = await self._get_session()
            async with session.get(
                self.API_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Google API error: HTTP {resp.status}")
                    return None

                data = await resp.json()

                # Extract translation from response
                # Response format: [[[translated_text, original_text, ...], ...], ...]
                if not data or not isinstance(data, list):
                    return None

                translated_parts = []
                for item in data[0]:
                    if item and isinstance(item, list) and len(item) > 0:
                        translated_parts.append(item[0])

                return "".join(translated_parts) if translated_parts else None

        except Exception as e:
            logger.warning(f"Google translation failed: {e}")
            return None

    async def detect_language(self, text: str) -> str | None:
        """Detect language using Google Translate API.

        Returns:
            Language code or None if failed
        """
        if not text or not text.strip():
            return None

        try:
            # Use auto-detection by translating to same language
            params = {
                "client": "gtx",
                "sl": "auto",
                "tl": "en",
                "dt": "t",
                "q": text[:100],  # Use first 100 chars
            }

            session = await self._get_session()
            async with session.get(
                self.API_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return None

                data = await resp.json()

                # Response includes detected language in some cases
                # Format: [[...], "detected_lang_code", ...]
                if len(data) > 1 and isinstance(data[1], str):
                    detected = data[1]
                    return self._denormalize_lang(detected)

                return None

        except Exception as e:
            logger.warning(f"Google language detection failed: {e}")
            return None
