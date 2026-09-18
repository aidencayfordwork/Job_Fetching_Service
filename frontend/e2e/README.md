# E2E tests

Prerequisites (this suite does not manage these itself):

1. Postgres running: `docker compose up -d db` (from the project root).
2. The backend API running with a matching API key:
   `SCHEDULER_ENABLED=false uvicorn app.main:app --port 8000` (from the
   project root). `SCHEDULER_ENABLED=false` avoids starting real fetch
   cycles against live job sites during a test run.
3. At least one job already persisted (e.g. from a prior scheduler run,
   or via the backend's own test fixtures) so the Jobs page has
   something to assert against.

Then, from this `frontend/` directory:

```
npx playwright test
```

Override the backend location/key if not using the defaults
(`http://localhost:8000` / `dev-local-key`) via `E2E_API_BASE_URL` and
`E2E_API_KEY` env vars.
