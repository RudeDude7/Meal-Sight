"""A throwaway world for Dimensions 4 and 5: its own pantry and profile databases.

Those dimensions have to put the system into one exact state per case (a pantry with a
particular item two days from expiry, a profile with ten five-star Italian ratings) and
then ask it for a recommendation. Doing that to the real data/ databases would wreck the
seeded demo pantry and the user's real history, so each case runs against fresh SQLite files
in a temp directory instead. The three MCP servers are pointed at them through environment
variables (MCPClientManager(env=...)); the agent code reaches the databases only through
those servers, so nothing else has to change. The recipe corpus is shared and read-only.

RESET AND VERIFICATION
  * reset() closes the handles, deletes both database files (and their -wal/-shm), recreates
    them from the real schema files, and then COUNTS the rows of every table: all must be
    zero or reset() raises. That count is returned and recorded per case.
  * After seeding, verify_pantry() / verify_profile() read the state back through the same
    public read functions the servers use and compare it with what the case asked for.
  * Dimension runners hash the CONTENT of the real pantry/user/recipe databases (every table's rows) before
    and after a run (file_fingerprints) and fail if any changed: proof the real data was never touched.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from mealsight.config.settings import settings
from mealsight.db.connection import SCHEMA_DIR, Database
from mealsight.db.init import init_database
from mealsight.pantry.query import get_pantry
from mealsight.user_intelligence.meal_history import log_meal
from mealsight.user_intelligence.preferences import update_preferences
from mealsight.user_intelligence.profile import get_user_profile


@dataclass(frozen=True)
class PantrySeed:
    """One pantry row. `days_remaining` is what the pantry will report: shelf life minus
    age, with the row aged so the arithmetic comes out exact."""

    name: str  # stored in the canonical form the real write path produces
    days_remaining: int | None = None  # None: not near expiry (a year of shelf life, added today)
    category: str = "other"
    quantity: float = 1.0
    unit: str | None = "count"


@dataclass(frozen=True)
class MealSeed:
    """One logged meal. `days_ago` is relative to the moment of seeding."""

    recipe_name: str
    cuisine: str | None
    days_ago: int
    rating: int | None = None
    recipe_id: str | None = None
    ingredients_used: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfileSeed:
    household_size: int | None = None
    preferred_cook_time_minutes: int | None = None
    disliked_ingredients: tuple[str, ...] = ()
    protein_preference: str | None = None
    dietary_restrictions: tuple[str, ...] = ()
    meals: tuple[MealSeed, ...] = ()


def file_fingerprints() -> dict[str, str]:
    """Content hashes of the REAL databases, to prove a run never modified them.

    The hash is of every table's rows (read-only), not of the file's bytes: opening and closing a SQLite
    database in WAL mode checkpoints the file and changes its bytes without changing a single row, so a
    byte hash raised a false alarm whenever anything else (a test run, say) merely opened the real database.
    """
    import sqlite3

    out: dict[str, str] = {}
    for label, path in (
        ("pantry", settings.pantry_db_path),
        ("user_intelligence", settings.user_intelligence_db_path),
        ("recipes", settings.recipes_db_path),
    ):
        if not Path(path).exists():
            out[label] = "absent"
            continue
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            digest = hashlib.sha256()
            tables = [
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            ]
            for table in tables:
                if table.startswith("sqlite_"):
                    continue
                digest.update(table.encode())
                for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2"):  # noqa: S608 - names from sqlite_master
                    digest.update(repr(row).encode())
            out[label] = digest.hexdigest()[:16]
        finally:
            conn.close()
    return out


class IsolatedWorld:
    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="mealsight_eval_"))
        self.pantry_path = self.dir / "pantry.db"
        self.user_path = self.dir / "user_intelligence.db"
        self.pantry_db: Database | None = None
        self.user_db: Database | None = None

    @property
    def env(self) -> dict[str, str]:
        return {
            "PANTRY_DB_PATH": str(self.pantry_path),
            "USER_INTELLIGENCE_DB_PATH": str(self.user_path),
        }

    async def reset(self) -> dict[str, int]:
        """Fresh empty databases. Returns row counts per table (all zero) as the verification."""
        await self.close()
        for path in (self.pantry_path, self.user_path):
            for suffix in ("", "-wal", "-shm"):
                Path(str(path) + suffix).unlink(missing_ok=True)
        self.pantry_db = Database(self.pantry_path, name="pantry", schema_path=SCHEMA_DIR / "pantry.sql")
        self.user_db = Database(
            self.user_path, name="user_intelligence", schema_path=SCHEMA_DIR / "user_intelligence.sql"
        )
        for db in (self.pantry_db, self.user_db):
            await init_database(db, db.schema_path)
        counts: dict[str, int] = {}
        for db in (self.pantry_db, self.user_db):
            tables = await db.fetch_all(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            for table in tables:
                row = await db.fetch_one(f"SELECT COUNT(*) AS n FROM {table['name']}")  # noqa: S608 - names from sqlite_master
                counts[f"{db.name}.{table['name']}"] = int(row["n"]) if row else -1
        non_empty = {k: v for k, v in counts.items() if v != 0}
        if non_empty:
            raise AssertionError(f"reset left rows behind: {non_empty}")
        return counts

    async def close(self) -> None:
        for db in (self.pantry_db, self.user_db):
            if db is not None:
                await db.close()
        self.pantry_db = None
        self.user_db = None

    async def cleanup(self) -> None:
        await self.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    # ------------------------------------------------------------------ seeding

    async def seed_pantry(self, items: list[PantrySeed], today: date | None = None) -> None:
        assert self.pantry_db is not None
        today = today or datetime.now(UTC).date()
        for item in items:
            shelf = 365 if item.days_remaining is None else max(item.days_remaining, 0) + 30
            age = 0 if item.days_remaining is None else shelf - item.days_remaining
            added = datetime.combine(today - timedelta(days=age), datetime.min.time()).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            await self.pantry_db.execute(
                "INSERT INTO pantry (name, quantity, unit, category, freshness_status, estimated_shelf_days, "
                "added_date, last_seen_date, source) VALUES (?, ?, ?, ?, 'fresh', ?, ?, ?, 'eval')",
                (item.name, item.quantity, item.unit, item.category, shelf, added, added),
            )

    async def seed_profile(self, profile: ProfileSeed, today: date | None = None) -> None:
        assert self.user_db is not None
        today = today or datetime.now(UTC).date()
        if profile.household_size is not None:
            await update_preferences("household_size", profile.household_size, user_db=self.user_db)
        if profile.preferred_cook_time_minutes is not None:
            await update_preferences(
                "preferred_cook_time_minutes", profile.preferred_cook_time_minutes, user_db=self.user_db
            )
        if profile.disliked_ingredients:
            await update_preferences(
                "disliked_ingredients",
                list(profile.disliked_ingredients),
                user_db=self.user_db,
                synonym_map={},
            )
        if profile.protein_preference is not None:
            await update_preferences("protein_preference", profile.protein_preference, user_db=self.user_db)
        if profile.dietary_restrictions:
            await update_preferences(
                "dietary_restrictions", list(profile.dietary_restrictions), user_db=self.user_db
            )
        from mealsight.db import get_recipe_db

        recipe_db = get_recipe_db()
        for meal in profile.meals:
            await log_meal(
                recipe_id=meal.recipe_id,
                recipe_name=meal.recipe_name,
                cuisine=meal.cuisine,
                meal_type="main",
                date=today - timedelta(days=meal.days_ago),
                rating=meal.rating,
                ingredients_used=list(meal.ingredients_used) or None,
                user_db=self.user_db,
                recipe_db=recipe_db,
            )

    # ---------------------------------------------------------------- read-back

    async def verify_pantry(self, expected: list[PantrySeed]) -> dict[str, Any]:
        """The pantry, read back through the same function the pantry server uses."""
        items = await get_pantry(freshness_filter="all", pantry_db=self.pantry_db)
        got = {i.name: i.days_remaining for i in items}
        want = {e.name: e.days_remaining if e.days_remaining is not None else 365 for e in expected}
        mismatches = {
            n: (want[n], got.get(n))
            for n in want
            if got.get(n) != want[n] and not (want[n] == 365 and got.get(n) == 365)
        }
        if len(items) != len(expected) or mismatches:
            raise AssertionError(f"pantry seed mismatch: rows {len(items)} vs {len(expected)}, {mismatches}")
        return {"rows": len(items), "days_remaining": {n: got[n] for n in sorted(got) if got[n] != 365}}

    async def verify_profile(self, expected: ProfileSeed) -> dict[str, Any]:
        profile = await get_user_profile(self.user_db)
        problems: list[str] = []
        if expected.household_size is not None and profile.household_size != expected.household_size:
            problems.append(f"household_size {profile.household_size}")
        if (
            expected.preferred_cook_time_minutes is not None
            and profile.preferred_cook_time_minutes != expected.preferred_cook_time_minutes
        ):
            problems.append(f"preferred_cook_time {profile.preferred_cook_time_minutes}")
        if (
            expected.protein_preference is not None
            and profile.protein_preference != expected.protein_preference
        ):
            problems.append(f"protein_preference {profile.protein_preference}")
        for d in expected.disliked_ingredients:
            if d not in profile.disliked_ingredients:
                problems.append(f"dislike {d} missing")
        rated = [m for m in expected.meals if m.rating is not None and m.cuisine]
        by_cuisine: dict[str, int] = {}
        for m in rated:
            assert m.cuisine is not None
            by_cuisine[m.cuisine.lower()] = by_cuisine.get(m.cuisine.lower(), 0) + 1
        for cuisine, n in by_cuisine.items():
            got_n = {k.lower(): v for k, v in profile.cuisine_preference_data_points.items()}.get(cuisine)
            if got_n != n:
                problems.append(f"cuisine {cuisine}: data_points {got_n} != {n}")
        if problems:
            raise AssertionError(f"profile seed mismatch: {problems}")
        return {
            "household_size": profile.household_size,
            "preferred_cook_time_minutes": profile.preferred_cook_time_minutes,
            "disliked_ingredients": profile.disliked_ingredients,
            "protein_preference": profile.protein_preference,
            "cuisine_scores": profile.cuisine_preferences,
            "cuisine_data_points": profile.cuisine_preference_data_points,
        }
