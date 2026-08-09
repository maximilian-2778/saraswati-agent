"""公开 API 入口；具体路由按业务领域放在 backend.routers。"""

from fastapi import APIRouter

from backend.routers import memory, presets, state, stories, system, templates


router = APIRouter()
router.include_router(system.router)
router.include_router(presets.router)
router.include_router(templates.router)
router.include_router(stories.router)
router.include_router(memory.router)
router.include_router(state.router)
