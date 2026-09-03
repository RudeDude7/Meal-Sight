-- pantry.db schema.
--
-- Tracks what MealSight currently believes is in the user's fridge and
-- pantry, mostly derived from photo analysis. Owned entirely by the
-- pantry MCP server — no foreign keys to recipes.db or
-- user_intelligence.db, since those are separate physical database files
-- and SQLite cannot join across them anyway. Cross-database data flow is
-- the agent's job, not SQL's.

CREATE TABLE IF NOT EXISTS pantry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    quantity REAL,
    unit TEXT,
    category TEXT NOT NULL,
    freshness_status TEXT DEFAULT 'fresh',
    estimated_shelf_days INTEGER,
    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source TEXT DEFAULT 'photo'
);

CREATE TABLE IF NOT EXISTS shelf_life_reference (
    item_name TEXT PRIMARY KEY,
    category TEXT,
    shelf_days_refrigerated INTEGER,
    shelf_days_frozen INTEGER,
    shelf_days_pantry INTEGER
);

CREATE TABLE IF NOT EXISTS grocery_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active',
    estimated_total_cost REAL,
    items TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consumption_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name TEXT NOT NULL,
    quantity_used REAL,
    used_for_recipe TEXT,
    consumed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- waste_log: every logged instance of food thrown out, with a reason —
-- separate from consumption_log (which records ANY quantity decrease,
-- waste included, with no reason attached) because this table exists
-- specifically to support reason-aware insights (mealsight.pantry.waste).
-- estimated_cost has no price data anywhere in this project — the
-- column exists per spec, but nothing ever writes a non-null value into
-- it; see mealsight.pantry.waste's own module docstring.
CREATE TABLE IF NOT EXISTS waste_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name TEXT NOT NULL,
    quantity_wasted REAL,
    unit TEXT,
    reason TEXT NOT NULL,
    estimated_cost REAL,
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pantry_category ON pantry(category);
CREATE INDEX IF NOT EXISTS idx_pantry_name ON pantry(name);
CREATE INDEX IF NOT EXISTS idx_pantry_last_seen_date ON pantry(last_seen_date);
CREATE INDEX IF NOT EXISTS idx_waste_log_item_name ON waste_log(item_name);
CREATE INDEX IF NOT EXISTS idx_waste_log_logged_at ON waste_log(logged_at);
