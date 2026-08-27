# CollabFlow

A real-time collaboration and project management platform — a focused hybrid of Jira
(task/project management) and Slack (real-time updates). See [PROJECT_BRIEF2.md](PROJECT_BRIEF2.md)
for full scope, and [PROGRESS.md](PROGRESS.md) for build status and decisions.

## Stack

Backend: FastAPI, async SQLAlchemy 2.0, PostgreSQL, Alembic, JWT auth, hand-rolled RBAC.
Frontend: React + TypeScript (Phase 7+). Real-time: FastAPI WebSockets + Redis pub/sub.

## Real-time architecture

Every backend instance subscribes to Redis pub/sub (`project:{id}:events`, pattern-subscribed
once as `project:*:events`) and relays messages to whichever WebSocket clients happen to be
connected to *that* instance. A REST call that changes a task publishes to Redis rather than
pushing to local sockets directly — so a task updated via an API call served by instance A still
reaches a WebSocket client connected to instance B. Only one instance runs in this project's demo
deployment, so that fan-out is presently a no-op round trip through Redis rather than something
observably necessary — but the code path is identical either way, which is the point: horizontal
scaling readiness without needing a rewrite to add it later.

Presence (who's viewing a project) is tracked in Redis as a per-project hash of
`user_id -> open-connection-count` (`app/ws/presence.py`), not a local in-process set — a ref
count because one user can hold multiple tabs/connections open, and a Redis-backed count (not an
in-memory one) because it needs to stay correct even if those connections land on different
instances. `GET /api/projects/{project_id}/presence` exposes the same data over REST for clients
that want a snapshot without opening a socket.

**Known simplification:** the WebSocket handshake passes the JWT access token as a query
parameter (`?token=...`), not an `Authorization` header — browsers' native WebSocket API can't
set custom headers on the handshake request. This means a short-lived access token can end up in
server access logs via the query string. A production system would issue a short-lived, single-use
WS ticket via an authenticated REST call instead of reusing the access token here.

## Notifications & background jobs

In-app notifications (mentions, task assignments, workspace/project invites, due-soon reminders)
are delivered live over `/ws/notifications` and persisted to the `notifications` table. Each one
also queues a Celery task that sends an email — in local dev this goes to a MailDev container, not
a real inbox, so nothing needs real SMTP credentials to test the full flow. View sent mail at
`http://localhost:1080`. Celery Beat runs `send_due_soon_reminders` once daily (see
`app/workers/celery_app.py`) for tasks due the next day.

@mentions in comments use the mentioned user's **email** (e.g. `@alice@example.com`) — there's no
separate username field on `User`, and email is the only identifier a mention can unambiguously
resolve to one account. A mention only notifies if that email belongs to an actual member of the
task's project; mentioning a non-member's email is a silent no-op (not an error) — see
`app/services/comment_service.py`.

## File attachments

Tasks can have file attachments, stored in MinIO (S3-compatible) rather than the app server's own
disk — the API server never proxies file bytes on download. Upload goes through the API
(`POST /api/tasks/{task_id}/attachments`, multipart), but download returns a **presigned URL**
(`GET .../attachments/{id}/download`) that the client fetches directly from MinIO, valid for 5
minutes. Files are capped at `MAX_ATTACHMENT_SIZE_MB` (10MB by default); there's no content-type
restriction beyond that — MinIO never executes stored objects, so this isn't a code-execution
surface the way serving uploads back through the app server would be.

MinIO's own console is at `http://localhost:9001` (login: the `S3_ACCESS_KEY`/`S3_SECRET_KEY`
values in `.env`) if you want to browse the bucket directly.

## Local development

Requires Docker Desktop with WSL integration enabled (or native Postgres/Redis instances).

```bash
docker compose up -d postgres redis minio maildev

cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

alembic upgrade head
uvicorn app.main:app --reload
```

API docs at `http://localhost:8000/docs`. Health check at `/health`.

### Running the background worker

Needed for email sending and the due-soon reminder job — the API queues Celery tasks regardless
of whether a worker is running, so nothing breaks without one, but nothing gets delivered either.

```bash
celery -A app.workers.celery_app worker --loglevel=info   # processes queued tasks
celery -A app.workers.celery_app beat --loglevel=info      # schedules the daily reminder job
```

### Running tests

Tests run against a separate `collabflow_test` database (see `TEST_DATABASE_URL` in
`app/core/config.py`). Create it once, then:

```bash
createdb collabflow_test   # or: docker exec -it <postgres-container> createdb -U collabflow collabflow_test
pytest
```
