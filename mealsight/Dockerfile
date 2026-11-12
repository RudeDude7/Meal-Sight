# MealSight backend for Hugging Face Spaces (Docker SDK). Build context is this folder (mealsight/).
#
#   docker build -t mealsight-api .
#   docker run --rm -p 7860:7860 -e MISTRAL_API_KEY=... -e GROQ_API_KEY=... -e OPENWEATHER_API_KEY=... \
#       -e CORS_ALLOWED_ORIGINS='["https://your-app.vercel.app"]' mealsight-api
#
# Secrets are supplied ONLY as environment variables (Spaces injects them at runtime). The image holds no
# .env file and no key. The databases are built at IMAGE BUILD time from committed fixtures, so a container
# starts with no pre-existing data and still has the same recipes and demo pantry every time.
#
# Spaces' filesystem is ephemeral: anything the app writes while running (pantry edits, meal history,
# profile changes) is lost when the Space restarts or sleeps and wakes, because each start is a fresh copy
# of this image. That is the intended behaviour for a public demo: it resets to a known state.

FROM python:3.11-slim

# procps (pgrep) is used by the pantry reset guard. ffmpeg is deliberately NOT installed: no backend code calls
# it (voice memos are validated with mutagen and transcribed by Groq's API), and removing it saved ~420 MB.
RUN apt-get update \
    && apt-get install -y --no-install-recommends procps ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /usr/local/bin/uv

# Spaces runs the container as UID 1000.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy

# Same layout as the repo: settings resolves data/ and .env relative to the folder above backend/.
WORKDIR /home/user/app
COPY --chown=user backend/pyproject.toml backend/uv.lock backend/
RUN cd backend && uv sync --frozen --no-dev --no-install-project

COPY --chown=user backend/ backend/
COPY --chown=user scripts/reset_demo_pantry.py scripts/
COPY --chown=user test_data/demo_pantry.json test_data/
RUN cd backend && uv sync --frozen --no-dev

# Build the databases. Placeholder keys exist only for this RUN (Settings refuses to import without them);
# they are not ENV, so they are not in the running container. No network, no API call.
RUN cd backend \
    && MISTRAL_API_KEY=build-placeholder GROQ_API_KEY=build-placeholder OPENWEATHER_API_KEY=build-placeholder \
       sh -c '.venv/bin/python -m mealsight.seed.seed_all --from-snapshot \
              && PYTHONPATH=. .venv/bin/python ../scripts/reset_demo_pantry.py'

WORKDIR /home/user/app/backend
EXPOSE 7860

# ONE worker on purpose: the provider rate limiter and the MCP client manager are per-process, so a
# second worker would double the request rate the provider allows and trip its 429s.
# --proxy-headers: Spaces sits behind a proxy; this makes the per-client submission limit see real IPs.
CMD [".venv/bin/uvicorn", "mealsight.api.app:app", "--host", "0.0.0.0", "--port", "7860", \
     "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
