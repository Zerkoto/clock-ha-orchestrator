from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.settings import Settings, get_settings


def build_engine(settings: Settings) -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True)


engine = build_engine(get_settings())
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
