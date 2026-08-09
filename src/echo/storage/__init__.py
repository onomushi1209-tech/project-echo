"""SQLite storage layer. All SQL lives here -- see db.py (schema/connection)
and repository.py (queries, model<->row mapping)."""

from echo.storage.db import get_connection, init_db
from echo.storage.repository import EchoRepository

__all__ = ["EchoRepository", "get_connection", "init_db"]
