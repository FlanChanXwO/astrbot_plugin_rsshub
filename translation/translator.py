"""Translation manager with caching support."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from ..utils.log_utils import logger
from .language_detect import should_translate
from .providers.baidu import BaiduTranslator
from .providers.base import BaseTranslator
from .providers.google import GoogleTranslator

if TYPE_CHECKING:
    from ..config import TranslationConfig


# Registry of available translation providers
_PROVIDER_REGISTRY: dict[str, type[BaseTranslator]] = {
    "google": GoogleTranslator,
    "baidu": BaiduTranslator,
}


def register_provider(name: str, provider_class: type[BaseTranslator]) -> None:
    """Register a new translation provider.

    This function allows external plugins or extensions to add new
    translation providers at runtime.

    Args:
        name: Unique provider identifier
        provider_class: Provider class inheriting from BaseTranslator

    Raises:
        ValueError: If provider name is already registered
        TypeError: If provider_class is not a subclass of BaseTranslator
    """
    if name in _PROVIDER_REGISTRY:
        raise ValueError(f"Provider '{name}' is already registered")

    if not issubclass(provider_class, BaseTranslator):
        raise TypeError(
            f"Provider class must inherit from BaseTranslator, "
            f"got {provider_class.__name__}"
        )

    _PROVIDER_REGISTRY[name] = provider_class
    logger.debug(f"Registered translation provider: {name}")


def get_available_providers() -> list[str]:
    """Get list of available provider names."""
    return list(_PROVIDER_REGISTRY.keys())


class TranslationManager:
    """Manages text translation with caching support."""

    # Separator for translated content display
    TRANSLATION_SEPARATOR = "\n--【译文】--\n"
    TRANSLATION_FAILED_MARKER = "\n--【译文】--\n（翻译失败）"

    def __init__(self, config: TranslationConfig | None = None):
        self.config = config
        self._provider: BaseTranslator | None = None
        self._cache_enabled = True
        self._target_lang = "zh-CN"
        self._force_translate = False
        self._translate_title = True
        self._translate_content = True
        self._display_original = False
        self._load_config()

    def _load_config(self) -> None:
        """Load translation configuration."""
        logger.debug("TranslationManager: Loading configuration...")
        if self.config is None:
            logger.debug("TranslationManager: Config is None, skipping")
            return

        try:
            # Load from TranslationConfig object
            logger.debug(f"TranslationManager: Config type={type(self.config)}")

            self._target_lang = self.config.target_lang
            self._force_translate = self.config.force_translate
            self._translate_title = self.config.translate_title
            self._translate_content = self.config.translate_content
            self._display_original = self.config.display_orignal_content
            self._cache_enabled = self.config.cache_translations

            logger.debug(
                f"TranslationManager: Settings loaded - "
                f"target_lang={self._target_lang}, "
                f"translate_title={self._translate_title}, "
                f"translate_content={self._translate_content}, "
                f"force_translate={self._force_translate}"
            )

            # Initialize provider
            self._init_provider(self.config.provider)

        except Exception as e:
            logger.warning(f"Failed to load translation config: {e}", exc_info=True)
            self._init_provider("google")

    def _init_provider(self, provider_name: str) -> None:
        """Initialize translation provider by name.

        Args:
            provider_name: Name of the provider to initialize
        """
        if provider_name not in _PROVIDER_REGISTRY:
            logger.warning(
                f"Unknown translation provider: {provider_name}, "
                f"falling back to google. Available: {get_available_providers()}"
            )
            provider_name = "google"

        provider_class = _PROVIDER_REGISTRY[provider_name]
        self._provider = provider_class(self.config)

        # Check if provider is properly configured
        if not self._provider.is_configured():
            logger.warning(
                f"Translation provider '{provider_name}' is not properly configured, "
                f"translation may fail"
            )

    def _get_cache_key(self, text: str, target_lang: str) -> str:
        """Generate cache key for translation."""
        provider_name = self._provider.NAME if self._provider else "unknown"
        key_data = f"{text}:{provider_name}:{target_lang}"
        return hashlib.md5(key_data.encode("utf-8")).hexdigest()

    async def _get_cached_translation(self, cache_key: str) -> str | None:
        """Get cached translation from database.

        Returns:
            Cached translation or None if not found
        """
        if not self._cache_enabled:
            return None

        try:
            from ..db import TranslationCache

            cache = await TranslationCache.get_by_hash(cache_key)
            if cache:
                return cache.translated_text
            return None

        except Exception as e:
            logger.debug(f"Cache lookup failed: {e}")
            return None

    async def _cache_translation(
        self,
        cache_key: str,
        translated_text: str,
    ) -> None:
        """Save translation to cache."""
        if not self._cache_enabled:
            return

        try:
            from ..db import TranslationCache

            provider_name = self._provider.NAME if self._provider else "unknown"
            await TranslationCache.save(
                hash=cache_key,
                provider=provider_name,
                target_lang=self._target_lang,
                translated_text=translated_text,
            )

        except Exception as e:
            logger.debug(f"Cache save failed: {e}")

    async def translate_text(
        self,
        text: str | None,
        target_lang: str | None = None,
    ) -> str | None:
        """Translate text with caching.

        Args:
            text: Text to translate
            target_lang: Target language (uses config default if None)

        Returns:
            Translated text or original if translation failed/not needed
        """
        logger.debug(
            "translate_text called: text=%s..., provider=%s",
            text[:50] if text else None,
            self._provider
        )

        if not text or not text.strip():
            logger.debug("translate_text: Empty text, returning as-is")
            return text

        if self._provider is None:
            logger.debug("translate_text: No provider available, returning as-is")
            return text

        # Check if should translate
        tgt_lang = target_lang or self._target_lang
        logger.debug(f"translate_text: Checking if should translate to {tgt_lang}")

        if not should_translate(text, tgt_lang, self._force_translate):
            logger.debug(
                "translate_text: Language detection says no translation needed"
            )
            return text

        # Check cache
        cache_key = self._get_cache_key(text, tgt_lang)
        logger.debug(f"translate_text: Checking cache for key={cache_key[:16]}...")
        cached = await self._get_cached_translation(cache_key)
        if cached is not None:
            logger.debug("translate_text: Cache hit! Returning cached translation")
            return cached

        logger.debug(
            "translate_text: Cache miss, calling provider %s",
            self._provider.NAME
        )

        # Perform translation
        try:
            result = await self._provider.translate(text, tgt_lang)
            logger.debug(
                "translate_text: Provider returned: %s...",
                result[:100] if result else None
            )

            if result and result != text:
                await self._cache_translation(cache_key, result)
                logger.debug("translate_text: Translation successful, cached")
                return result
            logger.debug("translate_text: Provider returned empty or same text")
            return text

        except Exception as e:
            logger.warning(f"Translation failed: {e}", exc_info=True)
            return text

    async def translate_entry(
        self,
        title: str | None,
        content: str | None,
        target_lang: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Translate RSS entry title and content.

        Args:
            title: Entry title
            content: Entry content
            target_lang: Target language (uses config default if None)

        Returns:
            Tuple of (translated_title, translated_content)
            Returns None for each if translation was skipped/failed
        """
        tgt_lang = target_lang or self._target_lang

        translated_title = None
        translated_content = None

        # Translate title
        if self._translate_title and title:
            translated_title = await self.translate_text(title, tgt_lang)

        # Translate content
        if self._translate_content and content:
            translated_content = await self.translate_text(content, tgt_lang)

        return translated_title, translated_content

    def format_translated_text(
        self,
        original: str | None,
        translated: str | None,
        translation_failed: bool = False,
    ) -> str | None:
        """Format translated text with original if needed.

        Args:
            original: Original text
            translated: Translated text
            translation_failed: Whether translation failed

        Returns:
            Formatted text for display
        """
        if translation_failed:
            if original:
                return f"{original}{self.TRANSLATION_FAILED_MARKER}"
            return None

        if not translated:
            return original

        # If translation returned same text (no translation needed)
        if translated == original:
            return original

        # If display original is enabled, show both
        if self._display_original and original:
            return f"{original}{self.TRANSLATION_SEPARATOR}{translated}"

        return translated

    @property
    def is_enabled(self) -> bool:
        """Check if translation is enabled."""
        return self._provider is not None

    @property
    def target_lang(self) -> str:
        """Get target language."""
        return self._target_lang

    @property
    def translate_title(self) -> bool:
        """Check if title translation is enabled."""
        return self._translate_title

    @property
    def translate_content(self) -> bool:
        """Check if content translation is enabled."""
        return self._translate_content

    @property
    def provider_name(self) -> str:
        """Get current provider name."""
        return self._provider.NAME if self._provider else ""
