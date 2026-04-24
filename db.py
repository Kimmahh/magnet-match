from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


BASE_DIR = Path(__file__).resolve().parent


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def database_path() -> Path:
    return Path(os.environ.get("DATABASE_PATH", BASE_DIR / "magnet_match.db"))


def is_postgres() -> bool:
    return database_url().startswith("postgres://") or database_url().startswith("postgresql://")


def connect() -> Any:
    if is_postgres():
        return psycopg.connect(database_url(), row_factory=dict_row)

    connection = sqlite3.connect(database_path())
    connection.row_factory = sqlite3.Row
    return connection


def placeholder_sql(sql: str) -> str:
    if is_postgres():
        return sql.replace("?", "%s")
    return sql


def row_value(row: Any, key: str) -> Any:
    if row is None:
        return None
    return row[key]
