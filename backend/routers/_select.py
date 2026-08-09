"""从控制器集合中挑选领域路由，迁移期间保持所有公开 URL 不变。"""

from collections.abc import Iterable

from fastapi import APIRouter
from fastapi.routing import APIRoute

from backend.controllers import router as controller_router


def routes_with_tags(tags: Iterable[str]) -> APIRouter:
    selected_tags = set(tags)
    router = APIRouter()
    router.routes.extend(
        route
        for route in controller_router.routes
        if isinstance(route, APIRoute) and selected_tags.intersection(route.tags)
    )
    return router
