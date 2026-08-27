# CollabFlow — Progress Log

Persistent memory for this project across sessions. Read this first before touching code.

## Current Phase
**Phase 5 — Notifications & Background Jobs: complete and verified.**

## Status — Phase 5 (Notifications, Celery, Email, Reminders)
- [x] `Notification` model (user_id, type, title, body, optional project_id/task_id both
      `ON DELETE SET NULL` — same "history outlives the referenced entity" reasoning as
      ActivityLog, see Phase 3/4), `read_at` nullable timestamp for read/unread state.
- [x] `app/services/notification_service.create_and_dispatch` — the single choke point every
      trigger calls through: persists + commits (its own unit of work, not bundled into the
      caller's transaction — see Bugs/Decisions below for why), broadcasts live over
      `/ws/notifications` via Redis pub/sub, and queues a Celery email task, always, regardless
      of whether the recipient is currently connected.
- [x] Real-time delivery generalized from Phase 4's project-room pattern rather than duplicated:
      `app/ws/redis_listener.py`'s `run_pattern_listener` is now generic (pattern + id-extractor +
      deliver-fn), so `main.py`'s lifespan runs two instances of the same listener — one for
      `project:*:events` (existing), one for `user:*:notifications` (new) — instead of two
      different pieces of listener code. `app/ws/notification_manager.py` mirrors
      `connection_manager.py`'s shape but keyed only by user_id (notifications aren't
      project-scoped — a user should be notified even for a project they don't have open).
- [x] `GET /ws/notifications` (WebSocket, any authenticated user, no project check) and REST:
      `GET /api/notifications` (paginated), `GET /api/notifications/unread-count`,
      `POST /api/notifications/{id}/read`, `POST /api/notifications/read-all`.
- [x] Notification triggers wired into existing services rather than added as new endpoints:
      task assignment (create + reassignment, not self-assignment) in `task_service`, workspace
      invite in `workspace_service`, project invite in `project_service`, @mention parsing in
      `comment_service` (email-based mentions, `app/core/mentions.py`; only notifies if the
      mentioned email belongs to an actual project member — see README).
- [x] Celery app (`app/workers/celery_app.py`, Redis as broker+backend) + `send_notification_email`
      task (blocking `smtplib`, fine since it only ever runs on a Celery worker thread, not the
      API's event loop) + Celery Beat `send_due_soon_reminders`, scheduled daily, matching tasks
      due **exactly tomorrow** (not "due within N days" — see Decisions below for why that
      distinction matters).
- [x] MailDev container added to `docker-compose.yml` (pinned to `2.1.0`, not `latest` — see Bugs
      below) for real SMTP delivery in local dev without needing real credentials; viewable at
      `http://localhost:1080`.
- [x] pytest suite: +12 tests (53 total) covering every notification trigger, unread count,
      mark-read/mark-all-read, cross-user access denial (404, not 403 — don't reveal another
      user's notification exists), and live WS delivery.
- [x] ruff clean. Alembic migration applied to real Postgres. Extensive live verification: full
      HTTP smoke test of every trigger, a real Celery worker actually processing the queued-task
      backlog from earlier test runs and delivering real mail to MailDev (confirmed via MailDev's
      own API, not just "the task didn't raise"), and the Beat reminder job run synchronously
      against a real task due tomorrow — notification created, email queued, delivered, confirmed
      in MailDev.

## Decisions worth knowing for Phase 5
- **Why the due-soon reminder matches `due_date == tomorrow` exactly, not "due within N days":**
  the job runs once daily. An exact-date match fires once per task, the day before it's due.
  A range match (e.g. "due within 2 days") would re-notify the same still-open, still-overdue task
  every single day the job runs until it's marked done — a design that looks more thorough but is
  actually just a spam generator. The tradeoff: a task whose due date passes without the job
  running that specific day (downtime) never gets reminded. Accepted for scope; noted honestly.
- **Why `create_and_dispatch` commits on its own, not inside the caller's transaction:** a single
  comment can mention multiple project members, meaning one `create_comment` call may invoke
  `create_and_dispatch` several times — each needs to succeed or fail independently, not roll back
  the others (or the comment itself) if one recipient lookup has an issue. Same reasoning as the
  WS broadcast-after-commit pattern from Phase 4, applied one layer further.
- **Test-writing lesson, not a code bug, but worth recording:** several new notification tests
  initially asserted the wrong count (e.g. expecting 1 notification after an assignment, got 2)
  because inviting a user to a project *also* creates a `project_invite` notification for that
  same user — both fire for the same recipient in tests that invite-then-assign in one flow. The
  app behavior was correct throughout; the tests had to be corrected to account for it. A reminder
  that "the test failed" and "the code is wrong" are different claims — this session's assertions
  were checked against actual behavior before being changed, not just adjusted to whatever passed.

## Bugs found and fixed in Phase 5
1. **MailDev `:latest` tag pulled a release candidate (3.0.0-rc.3) with a different, API-only
   routing scheme** — the web UI and `/email` endpoint both 404'd even though the SMTP server and
   process were genuinely up and healthy (confirmed via `docker logs` and `netstat` inside the
   container before concluding this wasn't a startup timing issue). Pinning to `2.1.0` (a known
   stable release) fixed it immediately. Lesson: `:latest` on a fast-moving dev-tool image is a
   real risk, not just a hygiene nitpick — caught here because I verified the container's actual
   listening state before assuming misconfiguration on my end.

## Status — Phase 4 (WebSockets, Redis Pub/Sub, Presence)
- [x] `app/ws/connection_manager.py` — process-local registry of live WebSocket connections,
      keyed by (project_id, user_id) -> set of sockets (a set, not one socket, since a user can
      hold multiple tabs open to the same project). Only responsible for fanning a message out to
      local sockets; never decides what to broadcast.
- [x] `app/core/redis.py` — module-level singleton async Redis client (mirrors the `engine`
      singleton pattern in `app/db/session.py`).
- [x] `app/ws/events.py` — every event (task created/updated/deleted, comment created, presence
      joined/left/snapshot) is published to a per-project Redis channel (`project:{id}:events`),
      never pushed to local sockets directly — even by the instance that triggered it.
- [x] `app/ws/redis_listener.py` — one long-lived background task (started in `main.py`'s
      lifespan), pattern-subscribed once to `project:*:events` rather than opening a subscription
      per active project, relaying every message to `connection_manager.send_to_project`.
- [x] `app/ws/presence.py` — presence tracked in Redis as a per-project hash of
      `user_id -> open-connection-count`, not a local set or a plain Redis set: a ref count
      because a user can hold multiple tabs/connections open, and Redis-backed (not in-process)
      so it stays correct even if those connections land on different backend instances.
- [x] `GET /ws/projects/{project_id}` (WebSocket) — auth via `require_ws_project_role`, a
      `Depends()`-based dependency that raises `WebSocketException` on failure (FastAPI closes the
      socket automatically, before accept). Token arrives as a query param, not a header — see
      Known Simplifications. On connect: snapshot of who's online sent directly to the new
      socket, *then* a PRESENCE_JOINED broadcast to everyone else (ordering matters — see bugs
      below). On disconnect: presence.leave + PRESENCE_LEFT broadcast if the count hits zero.
- [x] `GET /api/projects/{project_id}/presence` — REST snapshot of the same presence data, for
      clients that want "who's online" without opening a socket first, and for testing.
- [x] Task create/update/delete and comment create now publish a WS event after their DB
      transaction commits (not inside it, unlike activity log entries — a broadcast is a side
      effect that should only fire once the change is actually durable).
- [x] pytest suite: +6 WebSocket tests (41 total) using Starlette's `TestClient` (httpx.AsyncClient
      has no WS support). ruff clean. No new migration — Phase 4 state (presence, pub/sub) is
      entirely Redis-resident and intentionally never touches Postgres.
- [x] Extensive live verification against a real running `uvicorn` process + real Redis with a
      standalone `websockets` client (not mocked): single-connection task/comment broadcast flow,
      and a full two-user presence scenario (join, snapshot-includes-existing-user, live join
      broadcast to existing connections, live leave broadcast, REST presence staying in sync
      throughout) — repeated after every bug fix below to confirm each one actually held.

## Bugs found and fixed in Phase 4 (four, three of them concurrency-shaped)
1. **Presence-snapshot/self-join ordering race.** Original code published PRESENCE_JOINED to
   Redis *before* sending the direct presence snapshot to the newly-connected client. Since
   publishing wakes the (already-running) Redis listener task, that task could relay the
   client's own join event back to it before the direct snapshot send even happened — the new
   client would see itself "join" before knowing who else was online, or possibly before knowing
   it was online at all. Fixed by reordering: snapshot send fully completes before anything is
   published to Redis. Caught by an assertion in a manual smoke-test script that expected
   snapshot as the first message received; the fix was verified by rerunning that same script.
2. **WS auth wasn't overridable in tests.** Original auth used a hand-rolled `AsyncSessionLocal()`
   inside the route (auth failure needs `websocket.close()`, not an exception — or so it seemed),
   bypassing the same `Depends(get_db)` pattern every HTTP route uses. This meant `tests/conftest.py`'s
   DB override had no effect on the WS route, which would have silently hit the *dev* database
   during tests. Fixed by discovering FastAPI/Starlette support raising `WebSocketException` from
   a `Depends()` — it closes the socket with that code automatically, before accept — so auth
   became a normal overridable dependency (`require_ws_project_role`) instead of a special case.
3. **Redis client singleton broke across pytest's per-test event loops.** Exact same root cause as
   the `NullPool` fix from Phase 1 (documented there), but for `redis.asyncio.Redis` instead of
   the DB engine: a module-level singleton client gets bound to whichever event loop first creates
   it, and pytest-asyncio hands each test function a fresh loop — so any test after the first one
   to touch Redis raised `RuntimeError: Event loop is closed`. Fixed with an autouse fixture that
   closes and resets the singleton after every test, so the next test creates its own bound to its
   own loop — mirrors the DB engine fix in spirit exactly.
4. **`ConnectionManager.send_to_project` iterated a live, mutable set while awaiting inside the
   loop.** `await websocket.send_json(...)` yields control back to the event loop; if a real
   client disconnects at that exact moment, its `finally` block's `connection_manager.disconnect()`
   mutates the very set/dict this method is mid-iteration over, raising `RuntimeError: Set changed
   size during iteration`. Surfaced during a full pytest run (not the WS tests alone — it showed
   up during app shutdown while relaying a queued message), not caught by the individual
   WebSocket tests in isolation. Fixed by snapshotting both the outer dict and each inner set into
   plain lists before iterating, decoupling the broadcast loop from live mutable state. Re-ran the
   full suite 3x and the live two-user presence smoke test again after the fix to confirm no
   regression — a bug like this needs repetition to trust the fix, not just one clean run.

## Known Simplifications (Phase 4)
- WS auth token travels as a `?token=...` query parameter, not a header (browsers' native
  WebSocket API can't set custom headers on the handshake). Tradeoff: the access token can appear
  in server access logs. See README's Real-time architecture section for the production
  alternative (short-lived, single-use WS ticket).
- Redis pub/sub fan-out is real code, exercised on every event, but only one backend instance
  runs in this project's setup — so the "reaches clients on a different instance" benefit is
  architecturally present but not something this deployment currently needs. Documented per the
  brief's instruction to be honest about this exact tradeoff.
- `PresenceTracker.leave`'s `hincrby` + conditional `hdel` isn't a single atomic operation — a
  rare race between two concurrent disconnects at the exact moment a count would hit zero could
  theoretically leave a stale zero-count entry. Not fixed with Lua scripting/transactions given
  the scope; noted here rather than silently ignored.
- No reconnect/backoff logic exists yet on the client side — that's explicitly a Phase 7
  (frontend) concern per the brief ("native WebSocket client with a small reconnect/backoff
  wrapper").

## Status — Phase 3 (Activity Log, Filtering/Sorting/Pagination, Basic Search)
- [x] `ActivityLog` model (append-only — never updated/deleted, only inserted from
      `app/services/activity_service.py`). `activity_metadata` (not `metadata` — that name is
      reserved by SQLAlchemy's declarative `Base.metadata`) is a JSONB column holding structured
      details (e.g. `{"changes": {"status": {"old": "todo", "new": "in_progress"}}}`).
- [x] `task_id` FK is `ON DELETE SET NULL`, not `CASCADE` or a plain restrictive FK — a task's
      history must outlive the task itself. Verified via live smoke test: deleting a task nulls
      `task_id` on *every* historical log entry that referenced it (create, updates, etc.), not
      just the deletion entry — correct Postgres FK semantics, not a bug.
- [x] Every state-changing service call now logs an activity entry in the *same* transaction as
      the change it describes (flush, not commit — the log entry only persists if the action it
      describes actually commits): project created, member invited, task created/updated/deleted,
      comment added, label created.
- [x] `GET /api/projects/{project_id}/activity` and `GET /api/tasks/{task_id}/activity` — both
      paginated, newest first, RBAC via existing `require_project_role`/`require_task_project_role`.
- [x] Task listing (`GET /api/projects/{project_id}/tasks`) now supports filtering (status,
      priority, assignee_id, label_id), search (`search` — ILIKE on title; Postgres `tsvector` not
      used, per brief's "only if needed"), sorting (any field, asc/desc — status/priority sort
      correctly by severity because Postgres native enums order by their *definition* order, which
      was deliberately chosen to match: todo<in_progress<in_review<done, low<medium<high<urgent),
      and pagination (page/page_size, capped at 100). Response is now a `{items, total, page,
      page_size}` envelope instead of a bare list — a breaking change to the Phase 2 contract,
      done deliberately rather than bolting pagination on as a second endpoint.
- [x] Added `TaskUpdate.label_ids` (full-replace semantics) — Phase 2 built labels but never
      wired up attaching them to a task, which would have made the new `label_id` filter
      untestable. Closed that gap now rather than leaving it as dead functionality.
- [x] pytest suite: +9 tests (35 total). ruff clean. Alembic migration applied to real Postgres.
      Full live-HTTP smoke test against the migrated DB (filter/search/sort/paginate/update/
      delete/activity-log), including the FK SET NULL behavior above.

## Status — Phase 2 (Projects, Project Membership, Tasks, Labels, Subtasks, Comments)
- [x] `Role` enum + `ROLE_RANK` moved to a shared `app/models/roles.py` (was `WorkspaceRole`,
      workspace-only) since project membership reuses the same three roles. Postgres enum type
      `workspace_role` renamed to `member_role` via migration to match.
- [x] Project, ProjectMembership models — same Owner/Admin/Member pattern as Workspace.
      Creating a project auto-seeds the creator as project Owner (mirrors org→workspace pattern).
- [x] Task model: title, description, status (todo/in_progress/in_review/done), priority
      (low/medium/high/urgent), assignee, due_date, self-referential `parent_task_id` for
      subtasks, `position` (int, fractional-style ordering within a status column for future
      Kanban drag-and-drop), indexed on `project_id`, `assignee_id`, `status`, `parent_task_id`.
- [x] Label + `task_labels` many-to-many association table (unique per project by name).
- [x] Comment model (task_id, author_id, body). **Mention parsing deferred to Phase 5** — no
      notification system exists yet to feed (see Deviations).
- [x] `require_project_role(min_role)` and `require_task_project_role(min_role)` RBAC
      dependencies — the latter loads the task by `task_id`, checks role via *its* project, and
      returns the loaded Task so route handlers don't re-fetch it.
- [x] Endpoints: create/list projects (workspace-scoped), project members (list/invite),
      create/list/get/update/delete tasks, list subtasks, create/list labels, create/list comments.
- [x] pytest suite: +15 tests (26 total), covering RBAC on every write endpoint (member vs.
      admin/owner), assignee-must-be-project-member validation, subtask-same-project validation,
      duplicate label rejection.
- [x] ruff clean; Alembic migration applied to real Postgres (enum rename + 6 new
      tables/associations); full manual smoke test through live HTTP API against the migrated DB.

### Bug found and fixed in Phase 2
`Task.labels` (a lazy-loaded relationship) was accessed by Pydantic's response serialization
*after* the request's async DB session context had already yielded control back — FastAPI/Pydantic
don't await SQLAlchemy's lazy-load machinery, so this raised `MissingGreenlet`. **Only surfaced
when actually calling the endpoint (pytest response-model validation caught it too, to its
credit — this one wasn't hidden).** Fixed by setting `lazy="selectin"` on `Task.labels`, which
also happens to solve the N+1 that would otherwise occur when listing all tasks in a project with
their labels — a deliberate `selectinload`-equivalent choice, not an accident.

## Status — Phase 1 (Foundation)
- [x] Repo initialized (git init, backend/frontend directory skeleton)
- [x] Backend layered structure (`app/api/routers`, `core`, `models`, `schemas`, `services`, `crud`, `ws`, `workers`, `db`)
- [x] FastAPI app skeleton + config (pydantic-settings) + `/health`
- [x] DB session setup (async SQLAlchemy 2.0) + Alembic (async template)
- [x] User, Organization, Workspace, WorkspaceMembership models
- [x] JWT auth (register/login/refresh + `/me`), passlib/bcrypt hashing
- [x] RBAC dependency `require_workspace_role(min_role)` — rank-based Owner > Admin > Member check
- [x] Organizations (create, auto-seeds a "General" workspace with creator as Owner) + Workspaces
      (create, list members, invite member by email) endpoints
- [x] pytest suite: 11 tests, all passing against a real `collabflow_test` Postgres DB
- [x] ruff clean
- [x] Alembic migration applied to a real Postgres DB (`docker compose up -d postgres`, then
      `alembic upgrade head`) — schema verified with `\dt`/`\dT` in psql
- [x] Full manual smoke test through live HTTP API (register → login → me → create org →
      create workspace → list members) against the running app + real Postgres

## Bugs found and fixed this session (verification caught 3 real issues)
1. **Alembic migration double-created the Postgres enum type.** `workspace_role.create(bind,
   checkfirst=True)` ran explicitly, then `create_table` tried to create the same type again
   implicitly (default `create_type=True` on the inline `postgresql.ENUM`). Fixed by setting
   `create_type=False` on the enum instance used inside `create_table`, since creation is handled
   explicitly. `migrations/versions/34d09d87098c_phase1_foundation.py`.
2. **passlib 1.7.4 + bcrypt ≥4.1 incompatibility.** passlib's backend self-test hits bcrypt's new
   strict 72-byte enforcement and raises instead of the old truncate-silently behavior. Pinned
   `bcrypt<4.1` in `pyproject.toml`. Unrelated to any password we actually hash — it broke on
   import/first-use regardless of input.
3. **Enum values vs. names mismatch (the interesting one).** `WorkspaceRole` is a `StrEnum`;
   `SAEnum(WorkspaceRole, name="workspace_role")` without `values_callable` binds using member
   `.name` ("OWNER") by default. The hand-written Alembic migration hardcoded lowercase Postgres
   labels ("owner"/"admin"/"member"), so real inserts failed with `invalid input value for enum`.
   **pytest alone did not catch this** — the test fixture recreates the enum type via
   `Base.metadata.create_all` from the same (buggy) SAEnum definition, so table creation and
   inserts were self-consistently wrong together. Only running against the Alembic-migrated DB
   exposed the mismatch. Fixed with `values_callable=lambda cls: [m.value for m in cls]` in
   `app/models/workspace.py`. **Lesson: a from-scratch pytest DB via `create_all` can hide
   enum/type mismatches that only Alembic-vs-model drift would reveal — periodically smoke-test
   against the actual migrated DB, not just the test suite.**
4. Also found and fixed independently: pytest-asyncio opens a fresh event loop per test function,
   but the default SQLAlchemy connection pool holds asyncpg connections bound to whichever loop
   created them — reusing one across tests raised `another operation is in progress`. Fixed by
   using `NullPool` for the test engine in `tests/conftest.py`.

## Key Decisions
- Backend: Python 3.12, FastAPI, async SQLAlchemy 2.0, Pydantic v2, Alembic, PostgreSQL.
- RBAC built by hand via FastAPI dependencies (not a library), per the brief's learning objective.
  `require_workspace_role(min_role)` in `app/core/deps.py` uses a role-rank dict for "at least X" checks.
- Layered architecture per brief: routers thin, business logic in `services/`, data access in `crud/`.
- Creating an Organization auto-creates a "General" Workspace and makes the creator its Owner —
  avoids a dead-end org with no workspace and nowhere to invite people yet.
- Organization slugs are globally unique (suffixed on collision); Workspace slugs are unique per
  organization only.
- Added `docker-compose.yml` at repo root now (Postgres/Redis/MinIO only) instead of waiting for
  Phase 8, since Phase 1 needs a real Postgres to migrate/test against. Full compose (backend/
  worker/frontend services, per the brief's Phase 8) still deferred.
- Backend venv lives at `backend/.venv` — use it (not system/apt-installed packages) so installed
  versions match `pyproject.toml`.

## Known Simplifications
- Single-instance assumptions not yet relevant (no WebSockets/Redis pub/sub wired up yet — Phase 4).
- No rate limiting on auth endpoints yet (register/login) — worth adding before any public deploy.
- Task search is a plain `ILIKE` on title (no index beyond the default btree on title via no
  explicit index — full scans fine at this data scale). Postgres `tsvector` + GIN index deferred
  per the brief's "only if needed" — would matter once task counts got large or description
  search/ranking were required.

## Deviations from Brief
- `docker-compose.yml` introduced early (Phase 1, infra-only) rather than Phase 8 — see Key Decisions.
- Mention parsing (brief lists "comments, mentions" together under Task fields in Phase 2) was
  deferred to Phase 5, when the notification system that would consume mentions actually exists.
  Comments themselves were built in Phase 2. Confirmed with user before proceeding. **Resolved in
  Phase 5** — see that phase's status section for the implementation.

## Local dev environment notes
- Docker Desktop WSL integration must be enabled for the Ubuntu-24.04 distro (it was off at the
  start of this session; user enabled it mid-session). `docker compose up -d postgres` from repo
  root brings up Postgres; `collabflow_test` DB must be created once manually (or via a setup
  script — not yet automated): `docker exec <postgres-container> psql -U collabflow -d collabflow
  -c "CREATE DATABASE collabflow_test;"`.

## Next Steps
Phase 5 is done and verified — including closing out Phase 2's deferred mention-parsing item (see
that phase's Deviations entry; it now has a real consumer). Next: Phase 6 (Files — MinIO
integration, attachment upload/validation on tasks, file metadata in DB). MinIO is already in
`docker-compose.yml` from Phase 1 but has never actually been used yet — Phase 6 is where that
gets exercised for the first time.

## Model Effort Reminder
Per the brief: stay at Medium effort for routine CRUD/auth work; bump to High only for genuinely
harder design problems. Phase 4 (Real-Time) was done at High and caught real concurrency bugs that
Medium-effort review likely would have missed. Phase 5 (Notifications/Celery) was done at Medium,
appropriately — it was CRUD-shaped work (a new model, triggers wired into existing services,
standard Celery setup) with no comparable architectural complexity; the one interesting design
decision (exact-date reminder matching, not a range) was a judgment call, not a hard problem.
**Stay at Medium for Phase 6** (Files/MinIO) unless something in that phase's design turns out to
be less routine than it looks — flag it if so.
