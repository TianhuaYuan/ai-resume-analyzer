import asyncio
import os
import sys
import logging

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

backend_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, backend_dir)

from core.database import Base
from core.config import settings

import models.user  # noqa: F401
import models.resume  # noqa: F401
import models.qa_history  # noqa: F401
import models.resume_module  # noqa: F401
import models.job_application  # noqa: F401
import models.audit_log  # noqa: F401
import models.qa_feedback  # noqa: F401
import models.user_feedback  # noqa: F401
import models.analytics_event  # noqa: F401
import models.qa_conversation  # noqa: F401

config = context.config

# 设置脚本位置
config.set_main_option("script_location", "alembic")

# 设置 prepend_sys_path
config.set_main_option("prepend_sys_path", ".")

# 从 settings 中获取数据库 URL，覆盖配置文件中的值
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(levelname)-5.5s [%(name)s] %(message)s")
logger = logging.getLogger("alembic")
logger.setLevel(logging.INFO)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """Run migrations with a connection."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
