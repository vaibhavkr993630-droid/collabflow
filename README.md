# CollabFlow

A real-time collaboration and project management platform — a focused hybrid of Jira
(task/project management) and Slack (real-time updates). See [PROJECT_BRIEF2.md](PROJECT_BRIEF2.md)
for full scope, and [PROGRESS.md](PROGRESS.md) for build status and decisions.

## Stack

Backend: FastAPI, async SQLAlchemy 2.0, PostgreSQL, Alembic, JWT auth, hand-rolled RBAC.
Frontend: React + TypeScript (Phase 7+). Real-time: WebSockets + Redis pub/sub (Phase 4+).

## Local development

Requires Docker Desktop with WSL integration enabled (or a native Postgres instance).

```bash
docker compose up -d postgres redis minio

cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

alembic upgrade head
uvicorn app.main:app --reload
```

API docs at `http://localhost:8000/docs`. Health check at `/health`.

### Running tests

Tests run against a separate `collabflow_test` database (see `TEST_DATABASE_URL` in
`app/core/config.py`). Create it once, then:

```bash
createdb collabflow_test   # or: docker exec -it <postgres-container> createdb -U collabflow collabflow_test
pytest
```
