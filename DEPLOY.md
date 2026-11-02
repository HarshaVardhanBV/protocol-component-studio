# Deploy

The web app is **read-only and credential-free to run** — it serves `web/index.html`
and computes `/api/model` from the committed `store/*.json`. No database, no API key
needed in production. That makes it a one-service deploy on any container/PaaS host.

Start command (what `Procfile` already declares):
```
uvicorn server:app --host 0.0.0.0 --port $PORT
```

## Render (free tier, simplest)
1. Push the repo to GitHub.
2. Render → **New → Web Service** → connect the repo.
3. Settings:
   - **Runtime:** Python 3
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `uvicorn server:app --host 0.0.0.0 --port $PORT`
   - **Environment variables:** none required to run. (Only add `ANTHROPIC_API_KEY`
     or `NEO4J_*` if you intend to re-extract / load the graph from the deployed box,
     which you normally wouldn't — do that locally and commit the refreshed `store/`.)
4. Deploy → you get a public URL. Put it in the README badge and the vault `live_url`.

Pin the Python version if the default differs from local (3.12): add a `runtime.txt`
with `python-3.12.6` (Render) or a `.python-version` file.

## Railway / Fly.io (equivalent)
- **Railway:** New Project → Deploy from repo; it reads the `Procfile` automatically.
- **Fly.io:** `fly launch` (Python buildpack) → set the start command above → `fly deploy`.

## Notes
- `data/` (raw PDFs) and `.streamlit/secrets.toml` are gitignored, so nothing sensitive
  or heavy ships. The deploy only needs `server.py`, `app_data.py`, `src/`, `web/`,
  `store/*.json`, and `requirements.txt`.
- To refresh the live demo after a new extraction: re-run `extract`/`classify` locally,
  commit the updated `store/*.json`, and push — the host redeploys and the app picks up
  the new data on next request (the model cache keys off store mtime).
- The Streamlit build (`app.py`) can be deployed instead on Streamlit Community Cloud
  (entry point `app.py`) if you prefer that host — same credential-free behavior.
