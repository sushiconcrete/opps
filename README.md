# OPP Agent Web

LLM-powered competitive intelligence stack with a streaming Vite + React frontend and a FastAPI backend that orchestrates LangGraph agents, OAuth login, and a Postgres persistence layer.

## Project Highlights
- **Streaming intelligence run**: `frontend/src/utils/api.ts` drives a three-stage workflow (tenant intel, competitors, change radar) by streaming updates from `/api/analyze`.
- **Agentic backend**: `backend/app.py` wires FastAPI, Google/GitHub OAuth, and the LangGraph pipeline defined under `src/` into task-based endpoints (`/api/analyze`, `/api/status/{task_id}`, `/api/results/{task_id}`).
- **Persistent data model**: SQLAlchemy models in `backend/database/models.py` capture tenants, competitors, change tracking caches, and OAuth users with enhanced CRUD helpers.
- **Rate-limited tool usage**: `src/core/rate_limiter.py` wraps Tavily search, Firecrawl scraping, and OpenAI calls to stay within vendor limits.
- **Animated frontend shell**: Components like `AnimatedBackground`, `TypingText`, and the staged cards in `frontend/src/components/image-combiner.tsx` deliver a polished operator experience once the user logs in.

## Repository Layout
```
backend/             FastAPI service, OAuth flows, SQLAlchemy models
backend/database/    Connection helpers, CRUD modules, cache managers
frontend/            Vite + React single-page app with Tailwind UI
src/                 LangGraph agents, prompts, shared configs for analysis
main.py              Scripted runner tying the agents and persistence together
test*.py, *.ipynb    Ad-hoc experiments and notebooks
```

## Prerequisites
- Python 3.10+
- Node.js 20+ (npm 10+)
- A running Postgres instance (default URL `postgresql://opp_user:opp_password@localhost:5432/opp_db`)
- API access keys: OpenAI (gpt-4.1), Tavily search, Firecrawl MCP
- OAuth credentials if you intend to exercise Google/GitHub login flows

> **Note on dependencies:** `backend/requirements.txt` is saved in UTF-16. Convert it to UTF-8 (`iconv -f utf-16 -t utf-8 backend/requirements.txt > backend/requirements-utf8.txt`) or re-save the file before running `pip install`.

## Environment Variables
Place a `.env` file at the repo root (or under `backend/`). The backend loader checks multiple locations.

```
# Core services
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
FIRECRAWL_API_KEY=fc-...

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/opp_db
REDIS_URL=redis://localhost:6379/0   # optional, for future caching

# OAuth + JWT
JWT_SECRET_KEY=super-secret
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
GITHUB_REDIRECT_URI=http://localhost:8000/api/auth/github/callback

# App metadata (optional overrides)
APP_ENV=development
DEBUG=true
```

Frontend variables live in `frontend/.env.local`:
```
VITE_API_BASE_URL=http://localhost:8000
```

## Backend Setup & Commands
1. Create and activate a virtual environment.
2. Install dependencies (after converting `requirements.txt` if needed):
   ```bash
   pip install -r backend/requirements.txt
   ```
3. Apply schema (caution: `init_db()` drops and recreates tables every startup):
   ```bash
   uvicorn backend.app:app --reload --port 8000
   ```
   Running the app calls `init_db()` via FastAPI's lifespan hook. For an explicit migration workflow—and background cache tasks—run:
   ```bash
   python backend/database/deploy_database_enhancements.py
   ```
4. Helpful API routes once the server is up:
   - `POST /api/analyze` – enqueue an analysis run
   - `GET /api/status/{task_id}` – poll progress (0–100)
   - `GET /api/results/{task_id}` – retrieve final structured output
   - `GET /api/tasks` – list recent runs
   - `GET /api/stats` – aggregate counts
   - `GET /api/tenants/{tenant_id}/history` – historical competitor intel
   - OAuth endpoints under `/api/auth/*` manage login/logout and tokens

### Running the LangGraph pipeline standalone
`main.py` wires the tenant analyzer, competitor finder, and change detector with the persistence layer. A sample invocation:
```bash
python main.py
```
Adjust the `run_opp_agent_with_enhanced_persistence` parameters inside the script to target a specific domain or tune the competitor cap.

## Frontend Setup & Commands
From `frontend/`:
1. Install packages: `npm install`
2. Start the dev server: `npm run dev` (defaults to `http://localhost:5173`)
3. Lint: `npm run lint`
4. Production build: `npm run build`

The SPA stores the backend-issued JWT in `localStorage`. A successful OAuth callback should redirect to `/?token=...`, which `App.tsx` consumes to flip the UI into the analysis surface.

## Data & Caching Notes
- SQLAlchemy models (`backend/database/models.py`) define tenants, competitors, linkage tables, cached change detections, content storage, and OAuth users.
- `backend/database/cache_manager.py` maps human-readable competitor IDs to UUID primary keys before writing cache rows.
- `init_db()` currently performs a destructive `drop_all` → `create_all`. Avoid running it against production data.
- `backend/opp_analysis.db` ships as a local SQLite artefact for experimentation; the live code prefers Postgres via `DATABASE_URL`.

## Development Tips
- When debugging agent runs, enable FastAPI logging or instrument the print statements inside `streamMockRun` to observe stage transitions.
- Rate limiting buckets in `src/core/rate_limiter.py` can be tuned if you hit 429s during heavy research sessions.
- The old `mock_api.py` referenced in the frontend README has been replaced by the real FastAPI service; ensure `VITE_API_BASE_URL` points to your backend.
- Additional utilities under `src/tools/` and `src/wip/` are exploratory; review before relying on them.

## Troubleshooting
- **OAuth redirect loops**: confirm the `redirect_uri` you registered with Google/GitHub matches the values in `.env` and the frontend origin.
- **Frontend stuck on login**: check `localStorage.auth_token` and verify the backend responded with `/api/auth/me`.
- **Database integrity errors**: use `backend/database/test_database_integrity()` or `deploy_database_enhancements.py` to rebuild indexes and clean cache entries.
- **Unicode decode errors on install**: re-encode `backend/requirements.txt` as described above.

## Next Steps
- Harden database migrations (replace `init_db()` drop-create with Alembic migrations).
- Add automated tests for API endpoints and agent flows.
- Document deployment strategies (Docker, CI/CD) if you plan to run opp-agent-web beyond local development.
