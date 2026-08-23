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
