-- user_intelligence.db schema.
--
-- Owned entirely by the user-intelligence MCP server: meal history,
-- learned preferences, and cooking-pattern signals. No foreign keys to
-- pantry.db or recipes.db — those are separate physical database files,
-- and SQLite cannot join across them anyway. Cross-database data flow is
-- the agent's job, not SQL's.

CREATE TABLE IF NOT EXISTS user_profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meal_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id TEXT,
    recipe_name TEXT NOT NULL,
    cuisine TEXT,
    meal_type TEXT,
    date DATE NOT NULL,
    rating INTEGER CHECK (rating IS NULL OR (rating BETWEEN 1 AND 5)),
    servings_made INTEGER,
    ingredients_used TEXT,
    notes TEXT,
    cooked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS preference_scores (
    dimension TEXT NOT NULL,
    value TEXT NOT NULL,
    score REAL NOT NULL,
    data_points INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (dimension, value)
);

CREATE TABLE IF NOT EXISTS cooking_patterns (
    day_of_week INTEGER,
    hour_of_day INTEGER,
    cook_count INTEGER DEFAULT 0,
    average_cook_time_minutes REAL,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (day_of_week, hour_of_day)
);

CREATE INDEX IF NOT EXISTS idx_meal_history_date ON meal_history(date);
CREATE INDEX IF NOT EXISTS idx_meal_history_cuisine ON meal_history(cuisine);
CREATE INDEX IF NOT EXISTS idx_meal_history_rating ON meal_history(rating);

-- Every recommendation request and its outcome, regardless of whether
-- anything was actually cooked (meal_history only ever records a
-- CONFIRMED cook) — text only, on purpose: modalities/text_input/
-- voice_transcript/ingredients_summary are all plain text describing
-- what was sent or found, never the actual image or audio bytes
-- themselves, which keeps this table small and lets an ephemeral
-- deployment's filesystem survive a restart without a media blob store
-- to worry about.
CREATE TABLE IF NOT EXISTS interaction_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    trace_id TEXT,
    -- JSON array of strings, e.g. ["vision", "text"].
    modalities TEXT NOT NULL,
    text_input TEXT,
    voice_transcript TEXT,
    ingredients_summary TEXT,
    -- JSON object of the merged request's own constraint fields
    -- (dietary_restrictions, cuisine_preference, etc.) — null when
    -- perception never ran far enough to merge anything at all.
    merged_constraints TEXT,
    recommended_recipe_id TEXT,
    recommended_recipe_name TEXT,
    any_cookable INTEGER NOT NULL DEFAULT 0,
    top_match_score REAL,
    final_response TEXT
);

CREATE INDEX IF NOT EXISTS idx_interaction_history_created_at ON interaction_history(created_at);
