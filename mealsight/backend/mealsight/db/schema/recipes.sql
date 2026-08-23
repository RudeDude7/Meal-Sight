-- recipes.db schema.
--
-- Owned entirely by the recipes MCP server. No foreign keys to pantry.db
-- or user_intelligence.db — those are separate physical database files,
-- and SQLite cannot join across them anyway. Cross-database data flow is
-- the agent's job, not SQL's.

CREATE TABLE IF NOT EXISTS recipes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cuisine TEXT,
    meal_type TEXT,
    cook_time_minutes INTEGER,
    prep_time_minutes INTEGER,
    difficulty TEXT,
    servings_base INTEGER DEFAULT 4,
    -- JSON array of strings, e.g. ["vegetarian", "gluten-free"].
    dietary_tags TEXT,
    -- JSON array of objects: {"name": string, "quantity": number,
    -- "unit": string, "importance": "critical" | "important" | "optional"}.
    -- Phase 2 reads "importance" to decide whether a missing ingredient
    -- blocks a recommendation entirely or is just a nice-to-have.
    ingredients TEXT NOT NULL,
    -- JSON array of strings, one per ordered instruction step.
    steps TEXT NOT NULL,
    image_url TEXT,
    source TEXT,
    times_recommended INTEGER DEFAULT 0,
    average_rating REAL
);

CREATE TABLE IF NOT EXISTS nutrition_reference (
    ingredient TEXT PRIMARY KEY,
    calories_per_100g REAL,
    protein_per_100g REAL,
    carbs_per_100g REAL,
    fat_per_100g REAL,
    fiber_per_100g REAL,
    sodium_per_100g REAL,
    source TEXT DEFAULT 'usda'
);

CREATE TABLE IF NOT EXISTS substitutions (
    original_ingredient TEXT NOT NULL,
    substitute TEXT NOT NULL,
    ratio TEXT DEFAULT '1:1',
    flavor_impact TEXT,
    dietary_notes TEXT,
    notes TEXT,
    PRIMARY KEY (original_ingredient, substitute)
);

CREATE TABLE IF NOT EXISTS ingredient_synonyms (
    canonical_name TEXT NOT NULL,
    synonym TEXT NOT NULL,
    PRIMARY KEY (canonical_name, synonym)
);

CREATE INDEX IF NOT EXISTS idx_recipes_cuisine ON recipes(cuisine);
CREATE INDEX IF NOT EXISTS idx_recipes_cook_time_minutes ON recipes(cook_time_minutes);
CREATE INDEX IF NOT EXISTS idx_recipes_meal_type ON recipes(meal_type);
CREATE INDEX IF NOT EXISTS idx_ingredient_synonyms_synonym ON ingredient_synonyms(synonym);
