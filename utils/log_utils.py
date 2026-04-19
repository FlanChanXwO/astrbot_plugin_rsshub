"""Logger wrapper that adds plugin prefix to all log messages."""

from __future__ import annotations

from astrbot.api import logger as _logger


class PrefixedLogger:
    """Wrapper around AstrBot logger that adds [astrbot_plugin_rsshub] prefix."""

    PREFIX = "[astrbot_plugin_rsshub] "

    # Skip wrapper frame so astrbot log shows the real caller file:line.
    CALLER_STACKLEVEL = 2

    def _add_prefix(self, msg):
        """Add prefix to message if it's a string."""
        return self.PREFIX + str(msg)

    def _with_stacklevel(self, kwargs: dict) -> dict:
        if "stacklevel" not in kwargs:
            kwargs["stacklevel"] = self.CALLER_STACKLEVEL
        return kwargs

    def debug(self, msg, *args, **kwargs):
        _logger.debug(self._add_prefix(msg), *args, **self._with_stacklevel(kwargs))

    def info(self, msg, *args, **kwargs):
        _logger.info(self._add_prefix(msg), *args, **self._with_stacklevel(kwargs))

    def warning(self, msg, *args, **kwargs):
        _logger.warning(self._add_prefix(msg), *args, **self._with_stacklevel(kwargs))

    def error(self, msg, *args, **kwargs):
        _logger.error(self._add_prefix(msg), *args, **self._with_stacklevel(kwargs))

    def exception(self, msg, *args, **kwargs):
        _logger.exception(self._add_prefix(msg), *args, **self._with_stacklevel(kwargs))

    def critical(self, msg, *args, **kwargs):
        _logger.critical(self._add_prefix(msg), *args, **self._with_stacklevel(kwargs))


# Singleton instance for import
logger = PrefixedLogger()
