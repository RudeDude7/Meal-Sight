---
title: MealSight API
emoji: 🍽️
colorFrom: yellow
colorTo: red
sdk: docker
app_port: 7860
pinned: false
short_description: Backend for MealSight, a multimodal meal recommender (FastAPI, WebSocket, MCP).
---

# MealSight API

This Space runs the MealSight backend (FastAPI + WebSocket, three MCP servers as subprocesses, three SQLite
databases built from committed fixtures at image build time). The frontend is deployed separately on Vercel.

**It is a demo, and it resets.** The Space filesystem is ephemeral: pantry edits, meal history and profile
changes are lost whenever the Space restarts or wakes from sleep. The AI provider's free tier allows one
request every 30 seconds, so a photo recommendation takes about a minute and concurrent visitors queue.

Source and documentation: the main MealSight repository (README, docs/DEPLOYMENT.md).

Secrets (set in Space settings, never in the repo): `MISTRAL_API_KEY`, `GROQ_API_KEY`, `OPENWEATHER_API_KEY`.
Variable: `CORS_ALLOWED_ORIGINS`, a JSON array containing the Vercel frontend origin.
