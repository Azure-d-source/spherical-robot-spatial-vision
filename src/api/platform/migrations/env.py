from alembic import context
from sqlalchemy import create_engine, pool

from src.api.platform import frames, jobs
from src.api.platform.config import PlatformSettings
from src.api.platform.database import Base


database_url = PlatformSettings.from_env().database_url
metadata = Base.metadata

if context.is_offline_mode():
    context.configure(url=database_url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(database_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
