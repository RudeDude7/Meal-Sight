# Deployment: Hugging Face Space (backend) + Vercel (frontend)

What exists in the repo for this: `Dockerfile`, `.dockerignore`, `deploy/huggingface/` (Space README with the required
frontmatter, and a bundle script), `frontend/vercel.json`, `frontend/.env.example`. Nothing had been set up for
deployment before this.

**Verification status.** The image was built and run with Docker Desktop (arm64) on the machine it was prepared on:
build 28 to 66 s depending on cache, final image 615.5 MB; run with the three keys as environment variables only (no
`.env`, no mounts); `/health` healthy with 7, 8 and 11 MCP tools and 250 recipes; pantry hash `c975c014058a` with 64
rows inside the container; a full photo-plus-text recommendation completed in 62 to 66 s over a WebSocket, and a
voice-memo run worked without ffmpeg. **Not yet exercised:** the Hugging Face build and run (x86 hardware, their proxy
and their registry) and a real Space wake.

## How it is put together

- **Backend** (Space, Docker SDK, port 7860): FastAPI + WebSocket, three MCP servers as stdio subprocesses, one
  uvicorn worker. The databases are built **at image build time** from committed fixtures (`seed_all --from-snapshot`,
  then `scripts/reset_demo_pantry.py`), so a container starts with no pre-existing data and has the same 250 recipes
  and the same 64-row demo pantry (content hash `c975c014058a`, the value the eval baseline was recorded against).
- **Frontend** (Vercel): static Vite build, `VITE_API_BASE_URL` pointing at the Space, SPA rewrite so deep links work.
- **Secrets** exist only as environment variables (Space secrets). The image has no `.env` and no key; placeholder
  keys exist for the seeding `RUN` step only and are not `ENV`.

## Decisions

- **Ephemeral storage: the demo resets.** Free Spaces lose runtime writes on restart or sleep/wake. Seeding at build
  time means every start is the same fresh copy of the image, which is honest and simple: pantry edits, meal history
  and profile changes are temporary. The frontend's demo notice says so. No persistent storage is used.
- **One worker.** The provider rate limiter and the MCP client manager are per process; a second worker would double the
  request rate the provider allows and cause 429s.
- **`--proxy-headers`.** Spaces sits behind a proxy; without it every visitor shares one client IP and the per-client
  submission limit (10/minute) would be global. With it the limit sees real addresses.
- **ffmpeg is not installed.** It was in the first version and removed: no backend code calls it (voice memos are
  validated with mutagen and transcribed by Groq's API). The image went from 1,199.8 MB to 615.5 MB, and `/health`, the
  pantry hash, a photo-plus-text run and a voice-memo run all behave the same without it.

## The rate limit is a deployment constraint

At 2 provider requests a minute (measured, see the README), the whole deployment shares one limiter. A text-only
recommendation makes 2 requests and a photo one makes 3; the first starts at once and each further request waits for
the next 30 s slot. Measured against a local run of the container's file set with two simultaneous text-only visitors:
visitor A finished at 61.6 s and visitor B at 91.8 s, and `/health` reported `active_runs: 2` then `1` then `0`.
So each additional concurrent visitor adds roughly 30 to 60 seconds. Concurrent runs do not fail; they queue.

How it is disclosed, before the visitor waits: the Home page shows a "Free demo, so it is slow" notice above the submit
button, built from `GET /health` (`demo.seconds_between_requests`, `demo.active_runs`), so it is derived from the live
limiter and the running sessions and stays true if the provider's limits change. A plain notice rather than a queue
widget, because everyone shares one limiter and "N already running" is the whole story.

## Cold start

Free Spaces sleep after inactivity. The first request after a sleep waits for the container to start. **The wake time
on Hugging Face was not measured** (no Space exists yet). Measured locally in Docker with the image already on disk:
6.5 to 6.7 s from `docker run` to the first successful `/health` (three runs; 8.1 s once on a first run), and 6.4 s
for a stop followed by `docker start`, the closest analogue to a wake. Hugging Face adds scheduling and image loading
on top, so expect it to be longer than that, and measure it after the first deploy.

The frontend handles it without an error: while `/health` does not answer with a health report (an HTML wake page, a
timeout or a network error), a "waking up" notice with a ticking counter replaces the error, the submit button is
disabled with a plain reason, and the page retries every 4 s and unlocks by itself. Verified in a real browser
against a backend that was off and then started: the notice cleared 4.1 s after the backend came up, with no reload.

## CORS and the WebSocket

`CORS_ALLOWED_ORIGINS` (a JSON array) controls REST. Set it to the Vercel origin. Verified against the container's
file set: a preflight from the allowed origin gets `access-control-allow-origin`; another origin gets
`400 Disallowed CORS origin`. A full text-only recommendation ran from a real browser on a different origin
(`localhost:5173` to `127.0.0.1:7860`), including the cross-origin WebSocket upgrade, to "Recommendation ready".

Two facts worth knowing: CORS does not apply to WebSocket handshakes, and this backend does not check the `Origin` of a
WebSocket, so any origin that knows a session id (an unguessable UUID) can subscribe to it. Preview deployments on Vercel
have different origins and will be blocked by CORS unless you add them to the list.

## Manual steps

You have to do these; they need your accounts.

**0. (Optional) Build and run the image locally first** (already done once, see above), from `mealsight/`:
```
docker build -t mealsight-api .
docker run --rm -p 7860:7860 -e MISTRAL_API_KEY=... -e GROQ_API_KEY=... -e OPENWEATHER_API_KEY=... mealsight-api
curl localhost:7860/health      # all three MCP servers should report "up"
docker run --rm mealsight-api sh -c 'PYTHONPATH=. .venv/bin/python -c "import asyncio; from eval.runner import pantry_snapshot; print(asyncio.run(pantry_snapshot())[\"pantry_content_sha256\"])"'   # c975c014058a
```

**Hugging Face Space (backend)**
1. Create a token with write access at huggingface.co/settings/tokens.
2. New Space (huggingface.co/new-space): name `mealsight-api`, SDK **Docker** (blank template), hardware CPU basic
   (free), visibility **Public** (the Vercel frontend calls it from the browser).
3. Space Settings, "Variables and secrets", add secrets `MISTRAL_API_KEY`, `GROQ_API_KEY`, `OPENWEATHER_API_KEY`.
   (You will add the variable `CORS_ALLOWED_ORIGINS` in step 8, once Vercel gives you a domain.)
4. From `mealsight/`, assemble the bundle: `./deploy/huggingface/make_space_bundle.sh` (writes `dist/hf-space`).
5. Push it:
   ```
   cd dist/hf-space && git init -b main && git add . && git commit -m "Deploy MealSight API"
   git remote add space https://huggingface.co/spaces/<your-username>/mealsight-api
   git push --force space main      # username = your HF username, password = the token from step 1
   ```
6. Watch the build on the Space's "Logs" tab. When it says Running, check
   `https://<your-username>-mealsight-api.hf.space/health`: status healthy, three MCP servers up.

**Vercel (frontend)**
7. vercel.com, "Add New Project", import the GitHub repo. Set **Root Directory** to `mealsight/frontend`
   (framework Vite is detected; `vercel.json` sets the build and the SPA rewrite). Add the environment variable
   `VITE_API_BASE_URL` = `https://<your-username>-mealsight-api.hf.space` (https, no trailing slash) for Production and
   Preview, then deploy. It is read at build time, so changing it later needs a redeploy.
8. Copy the production domain Vercel assigns, then in the Space settings add the variable
   `CORS_ALLOWED_ORIGINS` = `["https://<your-project>.vercel.app"]` and restart the Space (or push any change).
9. Open the Vercel URL. Check a deep link directly (for example `/pantry`), and run one recommendation; the browser
   network tab should show the WebSocket on `wss://<your-username>-mealsight-api.hf.space/ws/...`.

## Known limits of this deployment

- The Hugging Face build and the Space wake time have not been exercised (see the top of this file).
- Everyone shares one pantry, one profile and one rate limit; there is no authentication.
- Because storage is ephemeral, nothing a visitor saves survives a restart.
