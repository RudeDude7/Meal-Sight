"""MCP server transport shells over MealSight's plain-Python engines.
Every server here is a thin wrapper: it validates input, calls into an
existing, independently-testable module (mealsight.recipe_engine,
mealsight.matching, ...), and serializes the result. No business logic
lives in this package — if a rule about what a recipe or a match means
needs to change, it changes in the underlying module, not here.
"""
