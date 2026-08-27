"""Async SQLite database layer: connection handling, schemas, and
initialization for MealSight's three physically separate databases
(pantry, recipes, user_intelligence)."""

from mealsight.db.connection import (
    Database,
    close_all,
    get_pantry_db,
    get_recipe_db,
    get_user_db,
)
from mealsight.db.init import SchemaInitResult, init_all_databases, init_database, reset_database

__all__ = [
    "Database",
    "SchemaInitResult",
    "close_all",
    "get_pantry_db",
    "get_recipe_db",
    "get_user_db",
    "init_all_databases",
    "init_database",
    "reset_database",
]
