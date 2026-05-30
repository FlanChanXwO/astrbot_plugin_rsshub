"""RSSHub Routes knowledge-base command handlers."""

from __future__ import annotations

from ...application.services.route_knowledge_service import (
    RouteKnowledgeSyncAlreadyRunning,
    RouteKnowledgeTaskStatus,
)


async def handle_rsshub_kb_init(deps: dict) -> dict:
    """Ensure the configured RSSHub Routes KB exists."""
    service = deps.get("route_knowledge_service")
    if service is None:
        return {"plain": "Routes KB 服务未初始化"}
    try:
        kb_id = await service.ensure_kb()
    except Exception as exc:
        return {"plain": f"Routes KB 初始化失败: {exc}"}
    return {"plain": f"Routes KB 已就绪: {kb_id}"}


async def handle_rsshub_kb_sync(deps: dict) -> dict:
    """Start a background routes KB sync task."""
    service = deps.get("route_knowledge_service")
    if service is None:
        return {"plain": "Routes KB 服务未初始化"}
    try:
        task = await service.start_sync()
    except RouteKnowledgeSyncAlreadyRunning as exc:
        return {"plain": f"无法启动 Routes KB 同步: {exc}"}
    except Exception as exc:
        return {"plain": f"Routes KB 同步启动失败: {exc}"}
    return {
        "plain": (
            f"Routes KB 同步任务已启动: {task.task_id}\n可用 /rsshub_kb_task 查看进度。"
        )
    }


async def handle_rsshub_kb_status(deps: dict) -> dict:
    """Return routes KB status."""
    service = deps.get("route_knowledge_service")
    if service is None:
        return {"plain": "Routes KB 服务未初始化"}
    status = await service.get_status()
    lines = [
        f"知识库: {status.kb_name}",
        f"KB ID: {status.kb_id or '未就绪'}",
        f"已管理文件: {status.managed_files}",
        f"KB 文档: {status.kb_docs}",
        f"来源版本: {status.source_version or '未知'}",
        f"最后同步: {status.last_sync_at or '从未同步'}",
    ]
    if status.last_error:
        lines.append(f"最近错误: {status.last_error}")
    if status.task.status != "idle":
        lines.append(f"任务: {_format_task_line(status.task)}")
    return {"plain": "\n".join(lines)}


def handle_rsshub_kb_task(deps: dict) -> dict:
    """Return latest routes KB sync task status."""
    service = deps.get("route_knowledge_service")
    if service is None:
        return {"plain": "Routes KB 服务未初始化"}
    task = service.get_task_status()
    if task.status == "idle":
        return {"plain": "当前没有 Routes KB 同步任务"}
    lines = [
        f"任务 ID: {task.task_id}",
        f"状态: {task.status}",
        f"进度: {task.processed}/{task.total}",
        f"计划: 新增 {task.added}, 更新 {task.updated}, 删除 {task.deleted}, 跳过 {task.skipped}{f', 对账修复 {task.reconciled}' if task.reconciled else ''}, 未变更 {task.unchanged}",
    ]
    if task.current_path:
        lines.append(f"当前文件: {task.current_path}")
    if task.message:
        lines.append(f"消息: {task.message}")
    if task.error:
        lines.append(f"错误: {task.error}")
    return {"plain": "\n".join(lines)}


def _format_task_line(task: RouteKnowledgeTaskStatus) -> str:
    return f"{task.status} {task.processed}/{task.total}{f' 对账={task.reconciled}' if task.reconciled else ''} ({task.task_id})"
