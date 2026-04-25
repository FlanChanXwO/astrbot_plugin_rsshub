"""Base translator interface for all translation providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiohttp


class BaseTranslator(ABC):
    """Abstract base class for all translation providers.

    All translation providers must inherit from this class and implement
    the required abstract methods.
    """

    # Provider name identifier (must be unique)
    NAME: str = ""

    # Language code mapping: our format -> provider format
    LANG_MAP: dict[str, str] = {}

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
    ):
        """Initialize the translator.

        Args:
            session: Shared aiohttp ClientSession with proxy/timeout configured
        """
        self._session = session

    @abstractmethod
    async def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: str | None = None,
    ) -> str | None:
        """Translate text from source language to target language.

        Args:
            text: Text to translate
            target_lang: Target language code (in our format)
            source_lang: Source language code (in our format), None for auto-detect

        Returns:
            Translated text or None if translation failed
        """
        raise NotImplementedError

    @abstractmethod
    async def detect_language(self, text: str) -> str | None:
        """Detect the language of the given text.

        Args:
            text: Text to detect language for

        Returns:
            Detected language code (in our format) or None if detection failed
        """
        raise NotImplementedError

    def _normalize_lang(self, lang_code: str) -> str:
        """Convert our language code to provider-specific format.

        Args:
            lang_code: Language code in our format (e.g., 'zh-CN')

        Returns:
            Provider-specific language code
        """
        return self.LANG_MAP.get(lang_code, lang_code)

    def _denormalize_lang(self, provider_lang_code: str) -> str:
        """Convert provider language code back to our format.

        Args:
            provider_lang_code: Language code from provider

        Returns:
            Language code in our format
        """
        for our_code, provider_code in self.LANG_MAP.items():
            if provider_code.lower() == provider_lang_code.lower():
                return our_code
        return provider_lang_code

    def _load_credentials(self) -> bool:
        """Load provider-specific credentials from config.

        Override this method if the provider requires authentication.

        Returns:
            True if credentials are valid/loaded, False otherwise
        """
        return True

    def is_configured(self) -> bool:
        """Check if the translator is properly configured and ready to use.

        Returns:
            True if the translator can be used, False otherwise
        """
        return True
