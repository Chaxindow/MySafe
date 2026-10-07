"""Database layer. The UI must only talk to the database through `Repository`."""

from mysafe.db.connection import open_database, open_from_bytes, to_bytes
from mysafe.db.repository import (
    CategoryNotEmptyError,
    DuplicateCategoryError,
    NotFoundError,
    Repository,
    RepositoryError,
)

__all__ = [
    "CategoryNotEmptyError",
    "DuplicateCategoryError",
    "NotFoundError",
    "Repository",
    "RepositoryError",
    "open_database",
    "open_from_bytes",
    "to_bytes",
]
