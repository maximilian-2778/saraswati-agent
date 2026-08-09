"""Alembic 数据库版本检测与应用启动升级。"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from backend.config import PROJECT_ROOT
from backend.database import Database


def upgrade_database(database: Database) -> str:
    """将数据库升级到 head，并接管没有版本号的旧版数据库。"""
    config = alembic_config(database.database_url)
    tables = set(inspect(database.engine).get_table_names())
    business_tables = tables - {"alembic_version", "sqlite_sequence"}
    current = current_revision(database)

    if business_tables and current is None:
        database.prepare_legacy_schema()
        command.stamp(config, "head")
        return "legacy_stamped"

    command.upgrade(config, "head")
    return "upgraded"


def current_revision(database: Database) -> str | None:
    """读取数据库当前 Alembic revision；未接管时返回 None。"""
    with database.engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def alembic_config(database_url: str) -> Config:
    """创建供应用和测试复用的 Alembic 配置。"""
    path = Path(PROJECT_ROOT) / "alembic.ini"
    config = Config(path.as_posix())
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config
