# CollabFlow — Progress Log

Persistent memory for this project across sessions. Read this first before touching code.

## Current Phase
**Phase 3 — Activity & Search: complete and verified.**

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
- Mention parsing (brief lists "comments, mentions" together under Task fields in Phase 2) is
  deferred to Phase 5, when the notification system that would consume mentions actually exists.
  Comments themselves are built now. Confirmed with user before proceeding.

## Local dev environment notes
- Docker Desktop WSL integration must be enabled for the Ubuntu-24.04 distro (it was off at the
  start of this session; user enabled it mid-session). `docker compose up -d postgres` from repo
  root brings up Postgres; `collabflow_test` DB must be created once manually (or via a setup
  script — not yet automated): `docker exec <postgres-container> psql -U collabflow -d collabflow
  -c "CREATE DATABASE collabflow_test;"`.

## Next Steps
Phase 3 is done and verified. Next: Phase 4 (Real-Time — WebSocket connection manager, broadcast
task/comment updates to project "rooms", presence, Redis pub/sub). **Remember to remind the user
to switch from Medium to High effort before starting Phase 4's design work** (see Model Effort
Reminder below) — this is exactly the kind of harder architectural reasoning the brief flags.

## Model Effort Reminder
Per the brief: stay at Medium effort through Phase 1-3 (routine CRUD/auth work). When Phase 4
(Real-Time: WebSocket manager, Redis pub/sub, presence) begins, remind the user to switch to
**High** effort for that phase's design work, then back to Medium once the design settles.
