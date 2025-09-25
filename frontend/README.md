# opp Frontend

Single-page React app built with Vite + TypeScript for the opp competitive intelligence workflow.

## What’s in the UI
- **Hero & typing headline** driven by `TypingText`, highlighting target audiences for the agent.
- **URL intake form** with a monospace input that normalises schemes before submitting.
- **Three-stage progress column** (“Tenant intel”, “Competitor sweep”, “Change radar”) that streams updates and swaps between idle, loading, done, or error states.
- **Animated background + pulse states** to keep the mock run visually lively while data arrives.

## Local Development
1. Install dependencies:
   ```bash
   npm install
   ```
2. Start the frontend dev server:
   ```bash
   npm run dev
   ```
   Vite exposes the app on the port it prints (usually `http://localhost:5173`).

Environment variables live in `.env.local`. The important one for local work is `VITE_API_BASE_URL`, which defaults to the mock server at `http://localhost:8000`.

## Working with the Mock API
We ship a streaming FastAPI mock in `mock_api.py` that reproduces the three-stage run:
- Emits tenant intel immediately, competitor data after 8 s, and change radar after 16 s total.
- Uses JSONL chunking so the frontend can update each stage as soon as it arrives.

To run it locally from the repo root:
```bash
uvicorn mock_api:app --reload --port 8000
```

The server listens on `http://localhost:8000` with reload enabled. Keep it running while you develop so the frontend can stream from `/mock/run`.

> Tip: if you prefer your own virtualenv, install FastAPI & Uvicorn (`pip install fastapi uvicorn`) first.

## Linting & Build
- `npm run lint` – ESLint (configured via `eslint.config.js`).
- `npm run build` – Type-check + production build.

Feel free to extend Tailwind utilities or replace the pulse loader with a richer effect—the stage lifecycles are already wired through `streamMockRun` in `src/utils/api.ts`.
