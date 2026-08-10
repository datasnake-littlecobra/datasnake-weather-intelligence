"""SQLAlchemy engine for the FastAPI service.

Uses the pgbouncer transaction-pooling connection (DATABASE_POOLER_URL).
Transaction pooling doesn't support session-level features the same way a
direct connection does — pool_pre_ping catches stale connections, and
statement caching is disabled since pgbouncer in transaction mode can hand
a different backend connection to each transaction.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import get_database_url

engine = create_engine(
    get_database_url(),
    pool_pre_ping=True,
    connect_args={"prepare_threshold": None},  # disable psycopg statement caching under pgbouncer
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
