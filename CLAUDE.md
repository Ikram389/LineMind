# CLAUDE.md — LineMind

LineMind is a manufacturing intelligence platform (production monitoring, downtime analysis, quality, maintenance, AI insights) for bottling lines. The full specification is in `docs/PRODUCT.md`. Read the relevant section before working on a feature.

## How we work
- We build **one step at a time** (see "Build plan" in `docs/PRODUCT.md`). Only build the step you are asked to build. Do not start future steps or add features that were not requested.
- **Plan before coding.** For every step, first present a plan (files to create/change, models, endpoints, tests) and wait for approval.
- After finishing, summarize what you built, how to run it, and what each new file does. The developer is learning; explain choices in plain language.
- If the spec is ambiguous or conflicts with these rules, ask instead of guessing.
- Keep changes small and focused. Do not refactor unrelated code.

## Stack
- Backend: Python 3.12, Django 5, Django REST Framework, PostgreSQL 16
- Frontend: React + TypeScript, built with Vite
- Simulator: plain Python, sends events to the backend over HTTP (**no MQTT**)
- Background jobs (when needed): Celery + Redis
- Everything runs with Docker Compose (`compose.yaml` at the repo root)
- Developer machine: Windows with Docker Desktop. Commands must work in Docker; avoid OS-specific shell scripts.

## Repository layout
```
backend/      Django project (config/ + apps/)
simulator/    Python factory simulator
frontend/     React + TypeScript app
vision/       Computer vision (later)
docs/         PRODUCT.md and other docs
compose.yaml
```
Django apps live in `backend/apps/<name>/` (accounts, organizations, production, downtime, quality, maintenance, analytics, notifications). Create an app only when a step needs it.

## Commands
(Update this section as the project grows.)
- First time only: `Copy-Item .env.example .env` (PowerShell) — compose reads settings from `.env`
- Start everything: `docker compose up --build` (frontend http://localhost:5173, backend http://localhost:8000; set `BACKEND_PORT` in `.env` if 8000 is taken)
- Backend tests: `docker compose exec backend pytest`
- Backend lint/format: `docker compose exec backend ruff check .` / `ruff format .`
- Backend lint/format: run `ruff format .` before `ruff check .` (`ruff check --fix` exits non-zero while unfixable issues remain)
- Migrations: `docker compose exec backend python manage.py makemigrations` / `migrate`
- Demo data (idempotent; needs `DEMO_USER_PASSWORD` in `.env`): `docker compose exec backend python manage.py seed_demo`
- Admin user (Django admin at http://localhost:8000/admin/): `docker compose exec backend python manage.py createsuperuser`
- Reset the development database (deletes all data): `docker compose down -v`, then `docker compose up --build`
- Get a JWT: `POST /api/v1/auth/token/` with `{"email", "password"}`; send `Authorization: Bearer <access>`
- Line API key for event senders (printed once): `docker compose exec backend python manage.py create_line_api_key <line_id> "<name>"`; send `Authorization: Api-Key <key>` to `POST /api/v1/events/` or `/api/v1/events/batch/`. Revoke in the Django admin.
- Frontend lint/typecheck: `docker compose exec frontend npm run lint` / `docker compose exec frontend npm run typecheck`
- The database is not exposed to the host; only the backend reaches it inside Docker.

## How to apply tenant isolation
All helpers are in `backend/apps/organizations/` (`tenancy.py`, `permissions.py`, `serializers.py`). Every app must use them:
1. **Viewsets** inherit `TenantScopedViewSetMixin` and set `factory_path`, the ORM path from the model to its `Factory` (`"pk"` for Factory, `"factory"` for ProductionLine, `"line__factory"` for Machine, e.g. `"machine__line__factory"` for a machine event). The queryset is then limited to the user's permitted factories, so other tenants' objects return 404.
2. **Permissions:** always include `IsAuthenticated` and `HasMembership`, plus a role check (`IsConfigurationManagerOrReadOnly`, or a new class in `permissions.py` built on `get_membership()` and `Role`). Roles decide *what you may do*; tenancy decides *which rows you see*. Use both.
3. **Foreign keys in serializers** that point to tenant data use `ScopedPrimaryKeyRelatedField(queryset=..., factory_path=...)`, so a user can't attach data to another tenant's object.
4. **Anything that isn't a viewset** (services, AI assistant tools, reports, Celery jobs) filters with `scope_to_user(queryset, user, factory_path)` or `permitted_factories(user)`. Never filter only by an ID from the request.
5. **Organization on create** comes from `get_membership(user).organization`, never from the request body.
6. **Tests:** every new endpoint gets tests using the `world` and `api` fixtures (`backend/conftest.py`, `tests/helpers.py`), proving that `other_manager` gets 404 on retrieve/update/delete and doesn't see the data in lists, and that `limited_operator` can't see factory B. See `apps/organizations/tests/test_isolation.py`.

The Django admin is not tenant-scoped: it's a superuser-only tool for platform operators.

## Event ingestion
Code lives in `backend/apps/production/`.
- **Entry point.** `services/ingestion.py` (`ingest_event`, `ingest_batch`) is the only code that turns incoming events into stored rows. Views just call it.
- **Event meaning.** `event_types.py` holds `EventType`, `MachineState` and `EVENT_TYPE_TO_STATE`, the single mapping from event type to state.
- **Order of checks:**
  1. The event is a JSON object with a UUID `event_id`.
  2. If that `event_id` already exists, the answer is `"duplicate"`. Nothing is re-validated or overwritten; the first version wins. The unique constraint is the safety net for simultaneous requests.
  3. Full validation runs (`IncomingEventSerializer`):
     - known type;
     - timestamp with a timezone, converted to UTC, at most `EVENT_MAX_FUTURE_SECONDS` ahead;
     - machine on the key's line;
     - counts are integers ≥ 0.
  4. The event is stored in its own savepoint.
- **Batches.** One result per event. A bad event never fails the batch. At most `EVENT_BATCH_MAX_SIZE` events.
- **What gets stored.** Every accepted event becomes an `IngestedEvent`. State types also create a `MachineStateEvent`, a point in time and not an interval; durations come in step 5. `production_count_updated` also creates a `ProductionEvent`, with counts stored exactly as reported. `sensor_reconnected` and `quality_defect_detected` are stored raw only.
- **Observations are immutable.** They inherit `ImmutableModel`: `save()` on an existing row and `delete()` raise an error. The admin is read-only and machine foreign keys are `PROTECT`. Never use `queryset.update()`/`.delete()` on them.
- **Order is by event timestamp.** Anything "latest" orders by event `timestamp` (then `received_at`, `id`), never by arrival. Out-of-order delivery is normal.
- **Stale telemetry.** A machine is `unknown` when it hasn't sent any event for longer than `Factory.stale_after_seconds`, or when it has never reported a state. See `services/line_status.py`.
- **Authentication.** `LineApiKeyAuthentication` and `HasLineApiKey` are used only on ingestion views. Keys are stored as SHA-256 hashes (`services/api_keys.py`). User endpoints never accept API keys, and ingestion never accepts user tokens.
- **Tests.** Use `apps/production/tests/events.py` (`make_event`) and the `sender`/`key_client` fixtures in `apps/production/tests/conftest.py`.

## Non-negotiable rules
1. **Tenant isolation.** Every query that returns organization data is filtered by the requesting user's organization and permitted factories, enforced on the server (querysets/permissions), never only in the UI. Every new endpoint gets a test proving a user from another organization gets 404/403.
2. **Observations are immutable.** Raw machine events (`MachineStateEvent`, `ProductionEvent`) are never edited or deleted by application logic. Classifications, AI suggestions and confirmed diagnoses are stored separately, with who/what created them.
3. **Metrics are computed in Python code, in one place.** OEE, durations and loss estimates live in dedicated service functions with unit tests. Never duplicate formulas in views, serializers or the frontend. The AI assistant never computes authoritative numbers.
4. **Time.** Store all timestamps as timezone-aware UTC. Convert to the factory's timezone only for display.
5. **Idempotent events.** Every incoming event has a unique `event_id`; duplicates are ignored, never double-counted. Out-of-order events are accepted.
6. **Estimates are labelled.** Any loss figure not directly measured is marked as an estimate in the API and UI.
7. **No secrets in code.** Use environment variables (`.env`, with a committed `.env.example`).
8. **Changes to classifications and configuration are written to the audit log** (once the AuditLog model exists).

## Code conventions
- Python: type hints, small functions, business logic in `services.py` (not in views or serializers), `ruff` for linting and formatting.
- Django: one app per domain; explicit `related_name`; database indexes on foreign keys and timestamps used in filters; API under `/api/v1/`.
- TypeScript: strict mode, no `any`, components small and typed; API calls in a dedicated `api/` folder.
- Names in English. Machine states use the exact values: `running`, `stopped`, `blocked`, `starved`, `planned_stop`, `unknown`.

## Testing
- Use `pytest` + `pytest-django` for the backend.
- Every feature includes tests; a step is not done until all tests pass.
- Use the reference test cases in `docs/PRODUCT.md` (OEE = 78.40%; simulator scenario = 5,335 good bottles) as fixed expected values.
- Test permissions, duplicates, out-of-order events and missing data, not only the happy path.

## Out of scope for now
MQTT, real PLC/OPC UA integration, automatic physical rejection, predictive maintenance, ERP integration, spare-parts inventory, Kubernetes/microservices.
