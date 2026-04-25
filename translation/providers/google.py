"""Google Translate provider using direct HTTP requests."""

from __future__ import annotations

import aiohttp

from ...utils.log_utils import logger
from .base import BaseTranslator


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

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
    ):
        super().__init__(session)

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
        logger.info(
            f"GoogleTranslator.translate 被调用：text={text[:30]}..., "
            f"target_lang={target_lang}, source_lang={source_lang}, "
            f"has_session={self._session is not None}"
        )

        if not text or not text.strip():
            logger.debug("GoogleTranslator: 空文本，直接返回")
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

            # Use external session if available, otherwise create temporary one
            if self._session is None:
                logger.error(
                    "GoogleTranslator: 没有可用的 session！创建临时 session（无代理）"
                )
                async with aiohttp.ClientSession() as temp_session:
                    return await self._do_translate(temp_session, params)
            else:
                logger.info(
                    f"GoogleTranslator: 使用提供的 session 进行翻译，"
                    f"session 类型={type(self._session).__name__}"
                )
                return await self._do_translate(self._session, params)

        except Exception as e:
            logger.warning(f"Google translation failed: {e}")
            return None

    async def _do_translate(
        self,
        session: aiohttp.ClientSession,
        params: dict,
    ) -> str | None:
        """Perform the actual translation request.

        Args:
            session: aiohttp ClientSession to use
            params: API parameters

        Returns:
            Translated text or None if failed
        """
        # Log session proxy info for debugging
        logger.debug(
            f"GoogleTranslator._do_translate: session type={type(session)}, "
            f"has_proxy={hasattr(session, '_proxy') and session._proxy is not None}"
        )

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

            # Use external session if available, otherwise create temporary one
            if self._session is None:
                async with aiohttp.ClientSession() as temp_session:
                    return await self._do_detect_language(temp_session, params)
            else:
                return await self._do_detect_language(self._session, params)

        except Exception as e:
            logger.warning(f"Google language detection failed: {e}")
            return None

    async def _do_detect_language(
        self,
        session: aiohttp.ClientSession,
        params: dict,
    ) -> str | None:
        """Perform the actual language detection request.

        Args:
            session: aiohttp ClientSession to use
            params: API parameters

        Returns:
            Detected language code or None if failed
        """
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
