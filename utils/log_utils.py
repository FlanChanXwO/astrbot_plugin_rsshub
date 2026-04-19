"""Logger wrapper that adds plugin prefix to all log messages."""

from astrbot.api import logger as _logger


class PrefixedLogger:
    """Wrapper around AstrBot logger that adds [astrbot_plugin_rsshub] prefix."""

    PREFIX = "[astrbot_plugin_rsshub] "

    def _add_prefix(self, msg):
        """Add prefix to message if it's a string."""
        return self.PREFIX + str(msg)

    def debug(self, msg, *args, **kwargs):
        _logger.debug(self._add_prefix(msg), *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        _logger.info(self._add_prefix(msg), *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        _logger.warning(self._add_prefix(msg), *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        _logger.error(self._add_prefix(msg), *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        _logger.exception(self._add_prefix(msg), *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        _logger.critical(self._add_prefix(msg), *args, **kwargs)


# Singleton instance for import
logger = PrefixedLogger()
