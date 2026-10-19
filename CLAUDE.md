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
Django apps live in `backend/apps/<name>/` (accounts, organizations, production, downtime, audit, quality, maintenance, analytics, notifications). Create an app only when a step needs it.

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
- Rebuild derived downtime/incidents (idempotent; run after changing a factory's `minimum_stop_seconds` or `stale_after_seconds`): `docker compose exec backend python manage.py rebuild_downtime --line <id> [--start ISO] [--end ISO]`
- OEE for a line: `GET /api/v1/lines/<id>/oee/?start=ISO&end=ISO[&group_by=hour|day|shift]` (JWT)
- Backfill today's morning shift (Algiers, 06:00 local = 05:00Z) after seed_demo: `docker compose run --rm simulator python main.py --scenario scenarios/normal_shift.yaml --mode backfill --start <today>T05:00:00Z` (must end in the past, i.e. after 14:00 Algiers)
- Regenerate the downtime test fixtures (only if the simulator or scenarios change): `docker compose run --rm simulator python main.py --scenario scenarios/<name>.yaml --mode backfill --output file --file data/<name>.jsonl`, then copy to `backend/tests/fixtures/`
- Frontend lint/typecheck: `docker compose exec frontend npm run lint` / `docker compose exec frontend npm run typecheck`
- Frontend tests (Vitest): `docker compose exec frontend npm test` (one file: `docker compose exec frontend npx vitest run src/pages/DowntimePage.test.tsx`)
- Downtime screens: http://localhost:5173/lines/<id>/downtime (Pareto, table, CSV), `/lines/<id>/unclassified` (queue), `/lines/<id>/reasons` (factory managers)
- CSV export from the shell: `GET /api/v1/downtime-events/export.csv?line=<id>&start=ISO&end=ISO[&view=line]` (JWT)
- Quality screens: http://localhost:5173/lines/<id>/quality (summary, Pareto, trend, results, reviews), `/lines/<id>/quality-setup` (defect types and stations, factory managers)
- Rebuild inspection results from the raw defect events (idempotent; reviews stay attached; run after the first `migrate` of step 9, or if processing failed): `docker compose exec backend python manage.py rebuild_quality --line <id> [--start ISO] [--end ISO]`
- Alerts (step 10a): `docker compose up` also starts `worker` (Celery), `beat` (alert evaluation every 30 s) and `mailpit`. Read alert emails at http://localhost:8025. Logs: `docker compose logs -f worker beat`
- Is the alert engine running? `GET /api/v1/health/` reports `"alerts": "ok"` or `"stale"` (no evaluation for 2 min); supervisors and above also see a red warning in the top bar
- Evaluate all alert rules once by hand: `docker compose exec backend python manage.py shell -c "from apps.notifications.tasks import evaluate_periodic; print(evaluate_periodic())"`
- After changing backend requirements (e.g. Celery): `docker compose up -d --build backend worker beat`
- After changing backend code: `docker compose restart worker beat` (unlike the dev server, Celery does not reload by itself; a stale worker runs old code against the new database)
- Maintenance (step 10b): http://localhost:5173/maintenance (list; technicians see "My actions") and `/maintenance/<id>` (steps, evidence, work log, diagnosis, before/after). "Create action" buttons are on line stops, alerts, recurring stops, defects and machine pages
- Effectiveness demo data (7 days each, ~10 min to send; nothing else must cover these dates): `docker compose run --rm simulator python main.py --scenario scenarios/labeler_recurring_jams.yaml --mode backfill` (2026-09-28 → 10-05), complete the action with fix date 2026-10-05 05:00 UTC, then the same with `scenarios/labeler_after_fix.yaml` (10-05 → 10-12)
- AI assistant (step 10c): set `ASSISTANT_BASE_URL`, `ASSISTANT_MODEL`, `ASSISTANT_API_KEY` in `.env` (README "AI production assistant"), then turn it on per organization in the Django admin (Assistant settings). Check: `GET /api/v1/assistant/status/`. Without a model: `ASSISTANT_PROVIDER=fake`
- Evaluate the assistant (paced for free tiers; report in `backend/reports/assistant_eval/`): `docker compose exec backend python manage.py assistant_eval [--models openai/gpt-oss-120b,openai/gpt-oss-20b] [--only q1,fr,no_data]`
- Quality endpoints (JWT; range required): `GET /api/v1/quality/summary|pareto|trend/?line=<id>&start=ISO&end=ISO`, `GET /api/v1/inspection-results/[export.csv]`, `POST /api/v1/inspection-results/<id>/reviews/`
- After changing `frontend/package.json`: `docker compose up -d --build -V frontend` (`-V` renews the container's node_modules volume)
- UI screenshots of every page at 1440x900, 1280x800 and 1920x1080 (needs live data, e.g. a realtime simulator run): `docker compose run --rm -e SHOT_LABEL=after e2e npm run screenshots` (writes `e2e/screenshots/<label>/`, not in git; `SHOT_PAGES=01,15` for some pages; compare with `e2e/screenshots/compare.html`)
- Accessibility check (axe, WCAG AA, light and dark): `docker compose run --rm e2e npm run a11y` (`A11Y_PAGES=overview,tv` for some pages)
- Design system gallery (development only): http://localhost:5173/dev/ui
- Dashboard: http://localhost:5173 (log in e.g. as `production_supervisor@demo-beverages.test`); live data: `docker compose run --rm simulator python main.py --scenario scenarios/labeler_jam.yaml --mode realtime`
- Simulator tests/lint (no backend needed): `docker compose run --rm simulator pytest` / `docker compose run --rm simulator ruff check .`
- Run the simulator (needs `SIMULATOR_API_KEY` in `.env`): `docker compose run --rm simulator python main.py --scenario scenarios/<name>.yaml --mode backfill --start 2026-10-05T06:00:00Z` (or `--mode accelerated --speed 60`, `--mode realtime`; `--output file` writes JSON Lines to `simulator/data/`)
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

## Downtime derivation
Code lives in `backend/apps/downtime/`. `DowntimeEvent` and `LineStopIncident` are *derived* conclusions: they can always be recomputed from the raw observations and are never typed in by hand.
- **Intervals.** `services/intervals.py` holds pure functions. Each state transition lasts until the next *different* state; repeated states merge. Sorting is always by `(timestamp, event_id)`, never by arrival.
- **Telemetry gaps.** Silences longer than `Factory.stale_after_seconds` become `no_data` intervals. The state that was in force resumes after the gap as a `resume` interval. Silence after a machine's last event is not a gap.
- **Downtime events.** Non-running intervals become `DowntimeEvent`:

  | State | Category |
  |---|---|
  | stopped | breakdown |
  | blocked | blocked |
  | starved | starved |
  | planned_stop | planned |
  | unknown | no_data |

  Closed intervals shorter than `oee_settings.minimum_stop_seconds` are dropped. Open ones (`ended_at=None`) are always kept.
- **Stable identity.** `(start_kind, start_event_id)` is the raw event that starts the interval. Rebuilds update rows in place, so ids and classifications survive. Rows that disappear but have classifications are marked `is_obsolete` instead of deleted.
- **After ingestion.** `services/derivation.py: rebuild_after_ingestion()` runs once per ingestion request, called from the ingestion service; it's ready to move to Celery. It rebuilds each affected machine over `[earliest new timestamp, next transition after the latest]`, then regroups incidents. `rebuild_line()` and the `rebuild_downtime` command recompute everything.
- **Incidents.** `services/incidents.py` groups breakdown/blocked/starved events that start while the current incident is open. First observed stop = earliest breakdown; equal times are all first stops. With no breakdown, `origin="unknown"`. In the API, say "first observed stop", never "root cause".
- **One formula each.** Durations: `services/durations.py`. Estimated losses: `services/losses.py`, always `{"units", "is_estimate": true, "basis"}`. Escalation: `Factory.escalation_after_seconds`.
- **Classifications.**
  - `DowntimeClassification` is append-only: the newest row is `current_classification`.
  - Write them only through `services/classification.py: classify_downtime()`, which also writes the AuditLog.
  - Allowed roles: operator, supervisor, factory manager, platform admin.
- **Audit.** Use `apps/audit/services.py: record_audit()` inside the same transaction for every change to classifications or configuration.
- **Tests.**
  - Simulator fixtures live in `backend/tests/fixtures/*.jsonl` and are loaded through the real ingestion service with the `load` fixture.
  - Any change to the derivation must keep the "any arrival order == full rebuild" tests passing.

## OEE calculation
Definitions, settings and their defaults are in `docs/PRODUCT.md` §4. Code:
- **Calculation.** `backend/apps/analytics/services/oee.py` is the only place OEE is calculated. Its functions are pure and take a `LineData` (`compute_inputs` → `OEEInputs`, then `calculate` → `OEEResult`). `oee_data.py` loads `LineData` in a few queries; `buckets.py` builds hour/day/shift buckets.
- **Time sets.** Times are combined with `apps/production/services/timeset.py` (`TimeSet` union, intersection, difference, exact `Fraction` seconds). Never add durations of overlapping things by hand.
- **Shifts.** Shift occurrences come from `apps/production/services/shifts.py: shift_periods()` and are never stored:
  - shift times are local factory time;
  - `end <= start` crosses midnight;
  - an occurrence belongs to the weekday it starts on.
- **Counts.** Only the counting machine counts (`ProductionLine.output_machine()`):
  - production is the difference between consecutive cumulative readings, credited to the later reading;
  - a reading counts only if its time is inside planned time (`TimeSet.contains_end_inclusive`);
  - a reading at second 0 of a run is a baseline (the simulator sends one).
- **Ideal cycle time.** It comes from the `ProductionOrder` covering the reading, with `ProductLineCycleTime` overriding the product's value. With no order, the line's slowest nominal speed is used, plus a warning.
- **Totals and percentages.**
  - Grouped totals are `calculate(sum_inputs(buckets))`, never an average of percentages.
  - Percentages are rounded only at the end, half up.
  - Performance is never capped.
- **Configuration endpoints.**
  - Shifts, breaks, products, cycle times and orders: `apps/production/planning_views.py`.
  - Products are organization-wide (`scope_to_organization`, writes need `all_factories`).
  - Every configuration viewset uses `AuditedModelViewSetMixin` (`apps/audit/mixins.py`), including factories, lines and machines. Put the mixin *before* any mixin that defines `perform_destroy`.

## Frontend and live updates
- **Backend runs under ASGI.** `daphne` is first in `INSTALLED_APPS`, so `runserver` serves HTTP and WebSockets. `config/asgi.py` routes `/ws/...` to `apps/live/routing.py`.
- **Redis** (the `redis` service, `REDIS_URL`) carries the channel layer and the cache. Without `REDIS_URL`, and in tests (`config/settings_test.py`), both are in-memory.
- **WebSocket per line:** `/ws/lines/<id>/?ticket=…`.
  - The ticket comes from `POST /api/v1/ws-ticket/` (JWT). It's single-use and lasts 30 s (`apps/live/tickets.py`).
  - `LineConsumer` checks the line with `scope_to_user`: 4401 for a bad ticket, 4403 for no access.
  - Messages only go server → browser.
- **Broadcasting** (`apps/live/broadcast.py`) always happens after commit (`transaction.on_commit`). Every message has the envelope `{type, line_id, sent_at, data}`.
  - `machine_state_changed`: only when the *current* state changed.
  - `count_updated`: the newest count per request, at most one per machine every 5 s.
  - `incident_opened`, `incident_updated`, `incident_closed`: only for ongoing incidents.

  The ingestion service queues machine messages *before* calling the downtime rebuild, so they go out first. The REST `/lines/{id}/status/` (`production/services/line_status.py: machine_status`) and the messages use the same functions.
- **Frontend layout** (`frontend/src/`):
  - `api/`: typed client and endpoints. The access token is in memory; the refresh token is in localStorage for development only and moves to an httpOnly cookie before production. A 401 → one refresh → one retry.
  - `i18n/en.ts`: all UI text. Never hard-code strings in components.
  - `lib/`: time formatting in the factory's timezone, state styles, server clock.
  - `live/useLineLive.ts`: ticket → socket → merges messages into the TanStack Query cache; backoff and reconnect.
  - `components/`, `pages/`.
- **Server time, not device time.** `lib/serverClock.ts` keeps an offset from WebSocket `sent_at` and HTTP `Date` headers. Stale detection and "time in state" use `serverNow()` / `useServerNow()`, never `Date.now()`.
- **Live screen rules.**
  - A machine with `last_seen` older than `stale_after_seconds` (server time) shows "unknown".
  - Every state has a colour, an icon *and* written text.
  - Alarms: shown prominently only while the machine is stopped; otherwise "Last alarm X · N min ago" if it happened during the current shift.
  - While disconnected, the status is polled every 15 s; after reconnecting, everything is re-fetched.
- **Demo modes.** Accelerated simulator mode ends at "now", so during the run the data lags real time and machines look stale. Use `--mode realtime` to watch the live screen.

## Downtime analysis
- **One place for the numbers.** `backend/apps/downtime/services/analysis.py` builds the analysed stops (`build_entries`) and is the only code that computes Pareto, summary, recurring stops and the "needs a reason" list. Durations are clipped to the requested range, ongoing stops count up to now, and sums use integer microseconds so the Pareto total always equals the summary total.
- **Two views.**
  - **Line view** (default): one entry per line stop incident, attributed to its first observed stop's machine, reason and alarm. Origin-unknown incidents are attributed to their earliest member. Use it to answer "why did the line lose time?".
  - **Machine view**: every downtime event, including blocked and starved time on other machines, so the totals are larger. Use it to answer "what happened on each machine?". The API returns `view` and `view_note`, and the UI always shows which view is on.
- **Planned and no_data** are excluded unless `include=planned,no_data` is passed. In the line view, overlapping stops of the same category are merged per line.
- **Roles in an incident** (`role_in_incident`): `first_observed_stop`, `secondary_breakdown` (a breakdown that is not a first stop) or `consequence` (blocked/starved). The first two need a reason; consequences never do. Secondary breakdowns don't add a line-view entry, but recurring stops count them, and the summary reports `secondary_breakdowns`.
- **Recurring stops**: breakdowns only, grouped by machine and reason (or alarm when unclassified), shown when the count reaches `Factory.recurring_stop_threshold` (default 3).
- **Endpoints** (all need `start` and `end`, at most 92 days, tenant-scoped): `GET /api/v1/downtime/pareto/`, `/downtime/summary/`, `/downtime/recurring/`, `/downtime-events/` (filters: line, machine, category, reason or `unclassified`, alarm or `none`, classified, min/max_duration, `view=line`, `needs_reason=true`, ordering), `/downtime-events/export.csv`, `/downtime-events/{id}/suggested-reasons/`, `POST /downtime-events/bulk-classify/`, `/incidents/{id}/`, `/downtime-reasons/` (plus `archive`/`restore`), `/factories/{id}/shift-occurrences/`.
- **Classification rules.** Bulk classification: supervisors, factory managers and platform admins; at most 200 stops; all-or-nothing; one audit entry per stop. Suggested reasons are frequency-based (no AI). Archived reasons can't be chosen. A reason that has been used can't be deleted (409): archive it instead.
- **CSV export.** Factory-time timestamps with offsets, a UTF-8 BOM for Excel, cells starting with `= + - @` (or tab/CR) are prefixed with `'`, and more than `DOWNTIME_EXPORT_MAX_ROWS` (50,000) rows → 400.
- **Frontend.** The filters live in the URL (`lib/downtimeFilters.ts`). Pages: `pages/DowntimePage.tsx`, `UnclassifiedPage.tsx`, `ReasonsPage.tsx`. Classification goes through `lib/useClassify.ts`. The prompt after a line stop comes from `live/useClassificationPrompts.ts`. Role checks for buttons are in `lib/permissions.ts`; the server enforces them anyway.

## Quality
Code lives in `backend/apps/quality/` (step 9). Rules are in `docs/PRODUCT.md` §4 (counting) and §6 (recording).
- **Results are derived.** `services/processing.py` turns each `quality_defect_detected` event into one `InspectionResult` (keyed by `event_id`), called by the ingestion service after the downtime rebuild, by `rebuild_quality`, and after station or defect-type changes. It updates rows in place, so reviews stay attached. It only reads raw events.
- **Never store good bottles.** Inspected volume comes from machine counters (`production/services/counters.py`).
- **Nothing is dropped.** Unknown codes and machines without an active station are kept, with warnings. An archived station stays on its past results; new defects use the machine's active station (at most one per machine).
- **Line-wide counts have one rule.** `LineCounts` in `production/services/counters.py`: total = counting machine output + upstream rejects; good = output − rejects at the counting machine. The OEE (`analytics/services/oee.py`) and the quality metrics both use it; never re-derive it elsewhere. A rejected bottle leaves the line at its machine in the simulator (`factory.py`), which is what makes this rule count each bottle once.
- **Metrics are in one place.** `services/metrics.py` covers summary, Pareto, trend and the effective defect type. A `false_reject` review removes a result from defect counts; `reclassified` counts it under the corrected type. Rates are computed from summed counts.
- **Reviews.**
  - `QualityReview` is append-only; the newest is `current_review`.
  - Write reviews only through `services/reviews.py: review_result()`, which also audits.
  - Allowed roles: quality inspector, supervisor, factory manager, platform admin.
  - **Reviews never change OEE**, which counts what the machines removed.
- **Context is computed when read.** `services/context.py` batches it for a page or CSV chunk: product and order, machine state and last alarm, and the last incident that ended within `Factory.quality_incident_window_minutes`. Wording: "Occurred 2 min after incident #14 ended", never a cause.
- **Live updates.** `quality_updated` (`services/live.py`) is sent after commit, at most once per line every 5 s, after new defects or a review. The overview card also refreshes every minute because throttled messages can be dropped.
- **Configuration.** Defect types are organization-wide (like products: writes need all factories). Stations are per line. Both archive instead of delete when used (409). A used defect type's code can't change.
- **Tests.** The fixtures `reference_quality_1h` (OEE 98.00%) and `normal_shift_150m` carry defect confidences. Use the `catalogue` and `defect` fixtures in `apps/quality/tests/conftest.py`.

## Alerts
Code lives in `backend/apps/notifications/` (step 10a).
- **Rule types are evaluators** (`evaluators/rules.py`, interface in `evaluators/base.py`).
  - Each has a parameters serializer (validation and defaults), `triggers` (events after which it is re-checked), `time_driven`, and `findings(rule, ctx)`: the subjects the condition is true for *now*.
  - Numbers come from the existing services (downtime, OEE, quality metrics), never recomputed here.
  - To add a type, write a class and register it in `EVALUATORS`.
- **The engine** (`services/engine.py`) is the only code that opens or auto-resolves alerts:
  - a finding without an unresolved alert opens one, unless it's suppressed or in cooldown;
  - an unresolved alert whose finding is gone resolves (`resolution=auto`);
  - running it twice changes nothing.
- **Deduplication is in the database.** A partial unique constraint allows one unresolved alert per rule + `subject_key`; `_open()` catches the IntegrityError, so two workers can't create duplicates. Never remove it or create alerts elsewhere.
- **Suppression** (`RuleEvaluator.suppressed`): no new alerts outside shifts, during breaks or planned stops, unless `active_outside_shifts`. Open alerts still resolve.
- **When rules are evaluated.**
  - Event-driven: `tasks.queue_evaluation(line_ids, triggers)` runs after commit from ingestion (`ingestion`, `downtime`, `quality`), classification and quality reviews.
  - Time-driven: beat runs `evaluate_periodic` every 30 s (every enabled rule, then escalation). It writes the `periodic` heartbeat; every finished task writes `worker` (`signals.py`).
- **Notifications** (`services/notify.py`):
  - Recipients come from `services/recipients.py`: active users of the alert's organization and factory with a rule role.
  - Each user's `NotificationPreference` decides in-app (never off) and email.
  - Emails are sent by `send_alert_email` with retries (30 s, 2 min, 8 min), then marked `failed`. Without a broker it retries immediately.
  - Live messages go after commit: `alert_opened/updated/resolved` to the line group, `notifications_changed {unread_count}` to the user group (`/ws/me/`).
- **Escalation** (`services/escalation.py`): warning and critical alerts still `open` after `escalate_after_minutes` go once to `escalation_roles`. A conditional update on `escalated_at` makes it happen once.
- **People's actions** (`services/actions.py`, audited):
  - Acknowledge: the rule's roles, escalation roles, and supervisors and above. The API returns `can_acknowledge` per alert.
  - Resolve: supervisors and above, with a note.
- **Text.** Alerts store `message_key` + `message_values`. The UI translates them (`en.ts`, keys `alert.*`); emails use `services/messages.py`. Keep both in sync.
- **Tests.** `apps/notifications/tests/` uses explicit `now` values (`support.T`) and the `day_shift`, `make_rule` and `evaluate` fixtures. Celery runs eagerly in tests (`settings_test.py`).

## Maintenance
Code lives in `backend/apps/maintenance/` (step 10b). Lightweight, not a CMMS: no inventory, purchasing or preventive schedules.
- **Workflow** (`services/workflow.py`, the `STEPS` table):
  - the path is requested → assigned → in_progress ⇄ waiting → done → verified;
  - cancel is possible before done; reopen goes from done or verified back to in_progress;
  - cancel, reopen and wait need a note.
  - Anything else is 400; a wrong role is 403.
  - Every step writes a `MaintenanceStatusChange` and an AuditLog entry, sends `maintenance_updated` to the line after commit, and re-checks the `maintenance_overdue` rule.
  - Verify only through `verify()`, with a result.
  - `allowed_steps()` tells the UI which buttons to show.
- **Roles** (`services/permissions.py`):
  - Request: everyone except analysts.
  - Assign, priority, due date, cancel, verify: supervisors and above.
  - Work (start, log, diagnose, complete): the assignee or any technician of the factory.
- **Links** (`services/links.py`) only point at observations (stops, incidents, alerts, defects) plus at most one **signature** (machine + reason or alarm). Each must be in the action's factory. `prefill()` builds the "create from" form for each source.
- **Confirmed diagnosis** (`services/diagnosis.py`):
  - A `MaintenanceDiagnosis` row; the newest is current.
  - "Apply to linked stops" adds a new `technician` classification per stop through `downtime.services.classification.record_confirmed_diagnosis`. The operator's classification stays in the history, and raw events are never touched.
  - `preview()` counts the stops first: unclassified, already this reason, same category, other reasons. By default only unclassified and same-category stops change; other categories need `replace_other_reasons`.
- **Effectiveness** (`services/effectiveness.py`, the only place it's computed):
  - Compares windows of `effectiveness_window_days` before and after `fixed_at` (the fix date; default the completion time, can be earlier).
  - Occurrences and downtime come from step 8 `select_entries` (machine view, breakdowns, signature); run time comes from the step 6 OEE `run_seconds`. Both are counted per 10 run hours.
  - `MARGIN` (±20%) and `MIN_BEFORE_OCCURRENCES` (5) are constants. Under `min_after_run_hours`, or with too few occurrences before, the result is `not_enough_data` with a reason.
  - The wording is an observation, never proof.
- **Notifications** reuse step 10a: `Notification.alert` is optional and `notify_users()` sends messages that aren't about an alert. The assignee is told on assignment (severity from priority: urgent → critical, high → warning, else info); the reporter is told on completion. The `maintenance_overdue` rule type lives in `notifications/evaluators/rules.py` and is never suppressed by shifts.
- **Tests.** Fixtures `labeler_recurring_jams_24h` and `labeler_after_fix_24h` (1 day each, consecutive at 2026-09-30 05:00; counters every 45 s, so they pass with the normal 60 s stale threshold — never relax it to make simulator data fit). Use the `new_action(status, ...)` and `all_day_shift` fixtures.

## AI assistant
Code lives in `backend/apps/assistant/` (step 10c). Read-only: it never writes anything.
- **Providers** (`providers/`): one interface (`stream()` yields text pieces then one result; `probe()`). `OpenAICompatibleProvider` talks plain HTTP to any OpenAI-compatible server (Groq, Ollama…), with 429 retries (`retry-after`, then 2/4/8 s) → "busy"; bad key/URL/no network → "unreachable". `FakeProvider` scripts replies: **no test may call a real model** (`fake(...)` fixture). Switching vendor = environment variables only.
- **Tools** (`tools/`, 13): thin wrappers around existing services. Arguments are declared once as `Param`s (JSON schema for the model *and* validation). Identity comes from `ToolContext` (the request's user), never from arguments; ids go through `ctx.line()`/`scope_to_user` → "not found". Every result has sources (with frontend links), the service's warnings and key metrics. User-written text goes through `untrusted()` (⟦…⟧).
  - Never compute metrics in a tool: call the service. Shared pieces were moved out of views for this (`analytics/services/report.py: oee_report`, `quality/services/metrics.py: trend_buckets`).
  - Dates: `resolve_time_range` and the prompt's ready-made ranges; differences: `compare_periods`. The model never calculates.
- **The loop** (`services/orchestrator.py: ask()`, a generator of events): max `ASSISTANT_MAX_TOOL_CALLS`, one correction after invalid arguments (or a malformed generation), a total timeout, concurrency slots (`services/limits.py`). Every ending stores a `Message` with a status and a server-written message in the question's language (`services/language.py`).
- **Number check** (`services/numbers.py`): every number in the answer must round from a tool result (or LineMind's own prompt context) → verified; only in the question → "from your question"; else "not verified" (logged). Numbers inside ⟦…⟧ never verify anything.
- **API**: `POST /assistant/conversations/{id}/ask/` streams server-sent events (`progress`, `delta`, `text_reset`, `final`, `error`); conversations are filtered by `user` (others get 404). Off per organization (`AssistantSettings`, admin, audited); daily limit counts answered questions only.
- **Wording**: "first observed stop", explanations as possibilities; answers are AI assessments (shown as such in the UI).
- **Evaluation** (`eval/`, `assistant_eval`): its own "Assistant Eval" organization built from the fixtures; expected numbers are computed from the services, never typed in. The report highlights the production candidate (gpt-oss-20b) against the development model.
- **Frontend**: `api/assistant.ts` (fetch stream parser), `components/assistant/` (chat, answer card, side panel), `pages/AssistantPage.tsx`. The Downtime page opens an incident from `?incident=<id>`.

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

## Simulator
Plain Python in `simulator/` (no Django, no MQTT). It runs as the `simulator` Compose service with the `simulator` profile, so `docker compose up` doesn't start it.
- **Layers.** Each layer knows nothing about the ones after it:
  - `scenarios.py`: YAML loading and validation.
  - `machines.py` / `factory.py`: line physics.
  - `simulation.py`: one tick produces a list of `Event`s.
  - `runner.py`: pacing by mode.
  - `senders.py`: `EventSink` with `FileSink` / `HttpSink`.
  - `event_queue.py`: SQLite queue.

  Simulation code must never import httpx or do I/O. A future real-machine connector should produce `events.Event` and reuse the sinks.
- **Tick rules (`factory.py`):**
  - Machines are processed downstream first (M06 → M01).
  - Speed uses exact `Fraction` credit.
  - Processed units = `min(credit, input level, output space)`.
  - State is decided in this order: fault → `stopped`; planned → `planned_stop`; processed ≥ 1 → `running`; input empty → `starved`; output full → `blocked`.
  - Defective units are counted and removed from the line.
- **Events (`simulation.py`, `events.py`):**
  - State events are sent only on transitions.
  - Counts (cumulative) are sent every `count_interval_seconds` plus once at the end.
  - Timestamps are UTC and strictly increasing per machine (1 ms tie-break).
  - `event_id = uuid5(scenario|seed|start, sequence)`, so the same run gives the same IDs (tests, idempotent re-sends).
- **Modes (`runner.py`):** accelerated mode places simulated time so it *ends* at the real end of the run. Timestamps must never be ahead of the wall clock, because the backend rejects events more than 5 minutes in the future.
- **Sending.** Events are queued in `simulator/data/queue.sqlite` before sending. Retries keep the same event JSON. Answered events are removed. Unsent events survive restarts.
- **Known answers** (keep these tests passing):
  - `reference_1h.yaml`: M06 makes 5,500 / 165 rejected / 5,335 good.
  - `labeler_jam.yaml`: the timeline matches PRODUCT.md §5.
  - `reference_quality_1h.yaml`: labeler 6,000 / 120 rejected, packer 5,880, every conveyor back at 25 (PRODUCT.md §4).
- **Rejects leave the line** at the machine that rejected them (never counted downstream). Defect events carry `payload.confidence` (0.80–0.99), derived from the event id so runs stay reproducible.
- **New scenarios** go in `simulator/scenarios/`. A scenario may override machine speeds (`machines: {M06: {speed_per_hour: 5880}}`) and buffers. Unknown keys are rejected. Machine IDs must exist in the line config, and all times must be multiples of `tick_seconds`.
