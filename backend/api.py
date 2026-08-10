"""公开 API 入口；具体路由按业务领域放在 backend.routers。"""

from fastapi import APIRouter

from backend.routers import extensions, memory, presets, state, stories, system, templates, world_engine


router = APIRouter()
router.include_router(system.router)
router.include_router(extensions.router)
router.include_router(presets.router)
router.include_router(templates.router)
router.include_router(stories.router)
router.include_router(memory.router)
router.include_router(state.router)
router.include_router(world_engine.router)
