"""Web API routes."""

from .chat import create_chat_routes
from .health import create_health_route
from .logs import create_log_routes
from .settings import create_settings_routes
from .storage import create_storage_routes
from .tasks import create_task_routes
from .temporal import create_temporal_routes
from .tokens import create_token_routes
from .wechat_dialog import create_wechat_dialog_routes

__all__ = [
    "create_chat_routes",
    "create_health_route",
    "create_log_routes",
    "create_settings_routes",
    "create_storage_routes",
    "create_task_routes",
    "create_temporal_routes",
    "create_token_routes",
    "create_wechat_dialog_routes",
]
