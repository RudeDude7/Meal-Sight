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

-- The waste_log table from the original spec is deliberately deferred —
-- do not add it here without a corresponding phase task.

CREATE INDEX IF NOT EXISTS idx_pantry_category ON pantry(category);
CREATE INDEX IF NOT EXISTS idx_pantry_name ON pantry(name);
CREATE INDEX IF NOT EXISTS idx_pantry_last_seen_date ON pantry(last_seen_date);
