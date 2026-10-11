"""Moteur SQLAlchemy / sessions SQLModel. SQLite par défaut, SQL Server via DATABASE_URL."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from .config import settings

logger = logging.getLogger("hackcure.db")

_connect_args = {"check_same_thread": False} if settings.is_sqlite else {}
engine = create_engine(settings.database_url, connect_args=_connect_args, echo=False)

if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - dépend du driver
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def init_db() -> None:
    from . import models  # noqa: F401 — enregistre les tables

    SQLModel.metadata.create_all(engine)
    _migrate_columns()
    from . import crypto

    crypto.migrate(engine)  # V3 : chiffre les champs sensibles encore en clair quand une clé vient d'être configurée
    logger.info("Base initialisée (%s)", "sqlite" if settings.is_sqlite else "sql server")


def _migrate_columns() -> None:
    """Ajoute les colonnes apparues après la création d'une base existante (SQLite : ALTER TABLE ADD COLUMN)."""
    if not settings.is_sqlite:
        return
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    wanted = {"risk": [("handled_by", "VARCHAR DEFAULT 'local' NOT NULL"), ("n8n_resume_url", "VARCHAR")], "ambulancemission": [("time_scale", "FLOAT DEFAULT 0 NOT NULL")],
              "auditlog": [("ip", "VARCHAR DEFAULT '' NOT NULL")]}
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if table not in insp.get_table_names():
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    logger.info("Migration : colonne %s.%s ajoutée", table, name)


def get_session() -> Iterator[Session]:
    """Dépendance FastAPI."""
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Utilisation hors FastAPI (agents, seed, simulateur)."""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
