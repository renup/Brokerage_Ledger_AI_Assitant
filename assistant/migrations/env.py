from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from assistant.config import settings

# Importing the models registers their tables on SQLModel.metadata, which is what
# "alembic revision --autogenerate" compares the real database against.
# Import ONLY this service's models, so a migration never touches another service's tables.
import assistant.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers=False so running migrations inside tests doesn't silence other logging
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# The URL comes from the service's settings (.env / environment). "%" must be doubled for the ini parser.
config.set_main_option("sqlalchemy.url", settings.assistant_database_url.replace("%", "%%"))
target_metadata = SQLModel.metadata


# "offline" mode writes the SQL to the screen instead of running it (useful for review)
def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


# "online" mode connects to the database and applies the migrations in one transaction
def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        # NullPool: a migration is a one-off command, so no connection pool is needed
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
