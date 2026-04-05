# RSS-to-AstrBot Monitor Module
# 基于 RSS-to-Telegram-Bot 移植的 RSS 监控模块

from .monitor import MonitorStat, RSSMonitor, TaskState

# 导出类而非实例
Monitor = RSSMonitor

__all__ = ["Monitor", "RSSMonitor", "MonitorStat", "TaskState"]
