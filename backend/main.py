"""FastAPI 应用工厂和开发服务器入口。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import router
from backend.config import Settings
from backend.database import Database
from backend.llm import ModelClient, build_model_client
from backend.migrations import upgrade_database
from backend.services.agent import AgentRuntime


def create_app(
    settings: Settings | None = None,
    model_client: ModelClient | None = None,
) -> FastAPI:
    """创建相互隔离、便于测试的 FastAPI 应用实例。"""
    active_settings = settings or Settings.from_env()
    database = Database(active_settings.database_url)
    model = model_client or build_model_client(active_settings)
    runtime = AgentRuntime(active_settings, model)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        upgrade_database(database)
        await runtime.startup()
        try:
            yield
        finally:
            active_runtime: AgentRuntime = _app.state.runtime
            await active_runtime.shutdown()
            database.close()

    app = FastAPI(
        title="Saraswati Agent API",
        version="1.0.0",
        description="带分层记忆、状态账本和一致性审计的角色扮演 Agent 后端。",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = active_settings
    app.state.database = database
    app.state.model = model
    app.state.runtime = runtime
    app.include_router(router, prefix="/api")
    return app


app = create_app()
