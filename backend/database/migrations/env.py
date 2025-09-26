from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

CURRENT_DIR = Path(__file__).resolve()
BACKEND_ROOT = CURRENT_DIR.parents[2]
REPO_ROOT = CURRENT_DIR.parents[3]

for candidate in {BACKEND_ROOT, REPO_ROOT}:
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.append(path_str)

from database.connection import DATABASE_URL
from database.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Ensure DATABASE_URL from environment takes precedence
sqlalchemy_url = os.getenv("DATABASE_URL", DATABASE_URL)
if sqlalchemy_url:
    config.set_main_option("sqlalchemy.url", sqlalchemy_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
