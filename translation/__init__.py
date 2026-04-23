"""Translation module for RSS-to-AstrBot."""

from .language_detect import should_translate
from .providers.baidu import BaiduTranslator
from .providers.base import BaseTranslator
from .providers.google import GoogleTranslator
from .translator import (
    TranslationManager,
    get_available_providers,
    register_provider,
)

__all__ = [
    "BaseTranslator",
    "TranslationManager",
    "get_available_providers",
    "register_provider",
    "should_translate",
    "GoogleTranslator",
    "BaiduTranslator",
]
