"""Baidu Translate provider."""

from __future__ import annotations

import hashlib
import random

import aiohttp

from ...config import cfg
from ...utils.log_utils import logger
from .base import BaseTranslator


class BaiduTranslator(BaseTranslator):
    """Baidu Translate API provider."""

    NAME = "baidu"
    API_URL = "https://fanyi-api.baidu.com/api/trans/vip/translate"

    # Baidu language codes
    LANG_MAP = {
        "zh-CN": "zh",
        "zh-TW": "cht",
        "en": "en",
        "ja": "jp",
        "ko": "kor",
        "fr": "fra",
        "de": "de",
        "es": "spa",
        "ru": "ru",
        "pt": "pt",
        "it": "it",
    }

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
    ):
        super().__init__(session)
        self._appid = ""
        self._key = ""

    def _load_credentials(self) -> bool:
        """Load Baidu API credentials from cfg.

        Returns:
            True if credentials are valid
        """
        if not cfg:
            return False

        try:
            # Get baidu credentials from translation_template
            templates = cfg.translation.translation_template or []
            for template in templates:
                if template.get("provider") == "baidu":
                    self._appid = template.get("baidu_appid", "")
                    self._key = template.get("baidu_key", "")
                    break

            return bool(self._appid and self._key)

        except Exception as e:
            logger.warning(f"Failed to load Baidu credentials: {e}")
            return False

    def _generate_sign(self, query: str, salt: str) -> str:
        """Generate Baidu API sign.

        Sign = MD5(appid + query + salt + key)
        """
        sign_str = f"{self._appid}{query}{salt}{self._key}"
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest()

    def is_configured(self) -> bool:
        """Check if Baidu translator has valid credentials."""
        return self._load_credentials()

    async def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str | None = None,
    ) -> str | None:
        """Translate text using Baidu Translate API.

        Args:
            text: Text to translate
            target_lang: Target language code
            source_lang: Source language code (auto-detect if None)

        Returns:
            Translated text or None if failed
        """
        if not text or not text.strip():
            return text

        if not self._load_credentials():
            logger.warning("Baidu translator: missing credentials")
            return None

        try:
            salt = str(random.randint(32768, 65536))
            sign = self._generate_sign(text, salt)

            params = {
                "q": text,
                "from": self._normalize_lang(source_lang) if source_lang else "auto",
                "to": self._normalize_lang(target_lang),
                "appid": self._appid,
                "salt": salt,
                "sign": sign,
            }

            # Use external session if available, otherwise create temporary one
            if self._session is None:
                logger.warning(
                    "BaiduTranslator: No session available, creating temporary session WITHOUT proxy"
                )
                async with aiohttp.ClientSession() as temp_session:
                    return await self._do_translate(temp_session, params)
            else:
                logger.debug("BaiduTranslator: Using provided session for translation")
                return await self._do_translate(self._session, params)

        except Exception as e:
            logger.warning(f"Baidu translation failed: {e}")
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
        async with session.get(
            self.API_URL,
            params=params,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                logger.warning(f"Baidu API error: HTTP {resp.status}")
                return None

            data = await resp.json()

            if "error_code" in data:
                logger.warning(f"Baidu API error: {data.get('error_msg')}")
                return None

            # Extract translation result
            trans_result = data.get("trans_result", [])
            if not trans_result:
                return None

            # Concatenate all translation parts
            translated_parts = [item.get("dst", "") for item in trans_result]
            return "".join(translated_parts)

    async def detect_language(self, text: str) -> str | None:
        """Detect language using Baidu API (via translation with from=auto).

        Returns:
            Detected language code or None
        """
        if not text or not text.strip():
            return None

        if not self._load_credentials():
            return None

        try:
            salt = str(random.randint(32768, 65536))
            sign = self._generate_sign(text, salt)

            params = {
                "q": text[:100],  # Use first 100 chars for detection
                "from": "auto",
                "to": "en",  # Target doesn't matter for detection
                "appid": self._appid,
                "salt": salt,
                "sign": sign,
            }

            # Use external session if available, otherwise create temporary one
            if self._session is None:
                async with aiohttp.ClientSession() as temp_session:
                    return await self._do_detect_language(temp_session, params)
            else:
                return await self._do_detect_language(self._session, params)

        except Exception as e:
            logger.warning(f"Baidu language detection failed: {e}")
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
            Detected language code or None
        """
        async with session.get(
            self.API_URL,
            params=params,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                return None

            data = await resp.json()

            if "error_code" in data:
                return None

            # Get detected source language
            from_lang = data.get("from", "")
            return self._denormalize_lang(from_lang) if from_lang else None
