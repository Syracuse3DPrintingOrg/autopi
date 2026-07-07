"""Engine, session factory, and safe init for the local SQLite database.

The database file lives at ``settings.data_dir / "autopi.db"``, next to the
JSON state files. The engine is looked up (and lazily created) by that path
rather than built once at import time, so tests that point ``data_dir`` at a
temp directory get an isolated database automatically.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from .models import Base


def db_path() -> Path:
    return settings.data_dir / "autopi.db"


@lru_cache(maxsize=8)
def _engine_for(path: str) -> Engine:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    return engine


def get_engine() -> Engine:
    return _engine_for(str(db_path()))


def get_sessionmaker() -> sessionmaker:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Session:
    """Return a new session. Caller is responsible for closing it."""
    return get_sessionmaker()()


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session that commits on success, rolls back on error, and closes."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create any missing tables. Never drops or resets existing data.

    Safe to call on every startup: ``create_all`` only adds tables that do
    not already exist and leaves existing ones (and their rows) untouched.
    """
    Base.metadata.create_all(get_engine())
