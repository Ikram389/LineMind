# LineMind

Manufacturing intelligence platform for bottling lines: production monitoring, downtime analysis, quality, maintenance and AI insights. The full specification is in [docs/PRODUCT.md](docs/PRODUCT.md).

On a bottling line, one jammed machine quickly blocks or starves its neighbours. The cause gets lost in the noise, and the lost time is only noticed at the end of the shift. LineMind collects machine events and turns them into answers people can act on:

- **Live line overview:** every machine's state, the line stop in progress and its **first observed stop**, and the shift's OEE.
- **Downtime analysis:** stop Pareto, recurring stops, and the reasons operators give for each stop.
- **Quality:** defects by type, station and time, with reviews by quality inspectors.
- **Alerts:** in-app and email, sent to the right roles, with escalation.
- **Maintenance actions:** linked to the stops they fix, with a before/after check of whether the fix helped.
- **AI production assistant:** read-only, in English, French or Arabic, built only on LineMind's own numbers.

Each organization sees only its own data. Raw machine events are never edited. Every metric is computed in one place on the server. A built-in **factory simulator** plays realistic scenarios, so you can try everything without a real line.

## Team: who did what

**Ikram ZIANE**: product owner and lead. Co-developed the idea from first-hand experience integrating a factory monitoring system and talking with production workers. Wrote the product specification and engineering rules, planned the step-by-step build, directed the AI coding assistant, and reviewed every technical plan, catching design flaws before implementation. Tested each feature live, ran the AI model evaluations, and produced the demo.

**Fouad BOUNAB**: my husband and former colleague, network and security manager. We brainstormed the idea together from our shared experience at work. He reviewed multi-tenant data isolation and authentication, security-tested the application by attempting to access other companies' data, advised on factory network architecture and how industrial devices connect to LineMind, and gave feedback on features, screens and the demo video.

## What runs where

| Service    | What it is                          | URL on your machine                        |
| ---------- | ----------------------------------- | ------------------------------------------ |
| `frontend` | React + TypeScript dashboard (Vite dev server) | http://localhost:5173           |
| `backend`  | Django + DRF, served through ASGI (Daphne): REST API and WebSockets | http://localhost:8000/api/v1/health/ |
| `db`       | PostgreSQL 16                       | internal only (not exposed to Windows)     |
| `redis`    | Redis 7: live-update channel layer, cache and job queue | internal only          |
| `worker`   | Celery worker: checks alert rules and sends alert emails | no URL                |
| `beat`     | Celery beat: starts the alert check every 30 seconds | no URL                    |
| `mailpit`  | Catches alert emails in development (no real mail is sent) | http://localhost:8025 |
| `simulator`| Python factory simulator (run on demand, see below) | sends events to the backend |

## Prerequisites (Windows)

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it. Wait until it says "Engine running".
2. Open PowerShell (or the VS Code terminal) in the project folder.

You do **not** need Python or Node.js installed on Windows. Everything runs inside Docker.

## First start

```powershell
# 1. Create your local settings file from the template (only once)
Copy-Item .env.example .env

# 2. Build and start all services
docker compose up --build
```

Then open http://localhost:5173. You should see the LineMind login page with **Backend: ok · Database: ok** under the form.

Stop everything with `Ctrl+C`, or from another terminal with `docker compose down`.
Your database data is kept in a Docker volume. `docker compose down -v` deletes it.

## Quick start: from zero to a live dashboard

About 5 minutes. Run these in PowerShell, in the project folder, with Docker Desktop running.

```powershell
# 1. Settings file (only once). DEMO_USER_PASSWORD in .env is the demo users' password.
Copy-Item .env.example .env

# 2. Start everything in the background
docker compose up --build -d

# 3. Demo organizations, factory, line, machines and one user per role
docker compose exec backend python manage.py seed_demo

# 4. An API key so the simulator may send events for Bottling Line 1 (shown once)
docker compose exec backend python manage.py create_line_api_key 1 "Simulator"
#    Paste it into .env as SIMULATOR_API_KEY=lm_..., save .env.
```

5. Open http://localhost:5173 and log in as `production_supervisor@demo-beverages.test`. The password is `DEMO_USER_PASSWORD` from `.env`: with the template unchanged it is **`change-me-demo-password`**. The same password works for every demo user. Swap the role at the start of the email to see another role's view: `machine_operator`, `maintenance_technician`, `quality_inspector`, `factory_manager`, `analyst` or `platform_admin` (all `@demo-beverages.test`).
6. Watch a labeler jam live (15 minutes; the jam starts at minute 5):
   ```powershell
   docker compose run --rm simulator python main.py --scenario scenarios/labeler_jam.yaml --mode realtime
   ```
   The labeler turns red with alarm E-204. Its neighbours become blocked or starved, and the banner names the labeler as the first observed stop. After 90 s the line runs again. Then open **Downtime** to classify the stop.

The AI assistant needs a model provider: see [AI production assistant](#ai-production-assistant). It is optional; everything else works without it.

## Everyday commands

| Task                         | Command                                                          |
| ---------------------------- | ---------------------------------------------------------------- |
| Start everything             | `docker compose up --build`                                      |
| Start in the background      | `docker compose up --build -d`                                   |
| See logs                     | `docker compose logs -f backend` (or `frontend`, `db`)           |
| Backend tests                | `docker compose exec backend pytest`                             |
| Backend lint                 | `docker compose exec backend ruff check .`                       |
| Backend format               | `docker compose exec backend ruff format .`                      |
| Create migrations            | `docker compose exec backend python manage.py makemigrations`    |
| Apply migrations             | `docker compose exec backend python manage.py migrate`           |
| Load demo data               | `docker compose exec backend python manage.py seed_demo`         |
| Create a line API key        | `docker compose exec backend python manage.py create_line_api_key <line_id> "<name>"` |
| Rebuild downtime for a line  | `docker compose exec backend python manage.py rebuild_downtime --line <id>` |
| Rebuild quality results      | `docker compose exec backend python manage.py rebuild_quality --line <id>` |
| Create an admin user         | `docker compose exec backend python manage.py createsuperuser`   |
| Frontend lint                | `docker compose exec frontend npm run lint`                      |
| Frontend type check          | `docker compose exec frontend npm run typecheck`                 |
| Frontend tests               | `docker compose exec frontend npm test`                          |
| Simulator tests              | `docker compose run --rm simulator pytest`                       |
| Simulator lint               | `docker compose run --rm simulator ruff check .`                 |

The `exec` commands need the services to be running (`docker compose up` in another terminal, or with `-d`).
The simulator commands use `run --rm`: they start a temporary container and remove it when done.

Code changes are picked up automatically: Django restarts itself and Vite hot-reloads the page.
If you change `requirements.txt` or `package.json`, rebuild with `docker compose up --build`.
For a new frontend package, also run `docker compose down` first, so the container's `node_modules` volume is recreated.

## Demo data and logging in

`seed_demo` creates two organizations:
- **Demo Beverages**: factory Algiers Plant, line Bottling Line 1, and machines M01–M06.
- **Other Company**: used to prove that tenants can't see each other's data.

It also creates one demo user per role, for example `factory_manager@demo-beverages.test` and `machine_operator@demo-beverages.test`, plus `factory_manager@other-company.test`. Every demo user's password is `DEMO_USER_PASSWORD` from your `.env`. The command is safe to run again.

Log in through the API (PowerShell):

```powershell
$login = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth/token/ `
  -ContentType "application/json" `
  -Body '{"email": "machine_operator@demo-beverages.test", "password": "<DEMO_USER_PASSWORD>"}'
$headers = @{ Authorization = "Bearer $($login.access)" }
Invoke-RestMethod -Uri http://localhost:8000/api/v1/me/ -Headers $headers
Invoke-RestMethod -Uri http://localhost:8000/api/v1/machines/ -Headers $headers
```

Access tokens last 15 minutes. Get a new one with `POST /api/v1/auth/token/refresh/` and `{"refresh": "<refresh token>"}`.

Django admin: create a superuser (see the table above), then open http://localhost:8000/admin/.

## API (v1)

| Endpoint | Description |
| --- | --- |
| `POST /api/v1/auth/token/`, `POST /api/v1/auth/token/refresh/` | Log in, refresh the access token |
| `GET /api/v1/me/` | Current user, organization, role, permitted factories |
| `/api/v1/factories/` | Factories (read: all roles; write: factory managers and platform admins) |
| `/api/v1/lines/?factory=<id>` | Production lines |
| `/api/v1/machines/?line=<id>` | Machines, ordered by position |
| `GET /api/v1/machines/{id}/state-events/?start=&end=` | State changes of a machine, ordered by timestamp (paginated: `limit`, `offset`) |
| `GET /api/v1/machines/{id}/production-events/?start=&end=` | Counter readings of a machine, ordered by timestamp (paginated) |
| `GET /api/v1/lines/{id}/status/` | Every machine's current state, when it began (`state_since`), shift count, alarms and last-seen time, plus the open incident with its first observed stop |
| `GET /api/v1/factories/{id}/current-shift/` | The shift running now (UTC start, end, breaks) or `null` |
| `POST /api/v1/ws-ticket/` | A single-use, 30-second ticket for the live WebSocket `/ws/lines/{id}/?ticket=…` |
| `GET /api/v1/downtime-events/` | Stops derived from machine states. Filters: `line`, `machine`, `factory`, `incident`, `category` (breakdown, blocked, starved, planned, no_data), `reason` (code), `classified=true/false`, `is_first_stop=true/false`, `start`/`end` |
| `GET/POST /api/v1/downtime-events/{id}/classifications/` | Classification history (GET) or a new classification `{"reason": <id>, "comment": "..."}` (POST: operators, supervisors, factory managers, platform admins) |
| `GET /api/v1/incidents/`, `GET /api/v1/incidents/{id}/` | Line stop incidents (cascades) with their **first observed stop** and, in the detail, all affected machines in time order. Filters: `line`, `origin`, `start`/`end` |
| `GET /api/v1/downtime-reasons/?factory=<id>` | The factory's downtime reason catalogue |
| `GET /api/v1/lines/{id}/oee/?start=&end=[&group_by=hour\|day\|shift]` | OEE with every input, the four results (ratio and %), data coverage and warnings; with `group_by`, one result per bucket plus the total |
| `/api/v1/shifts/`, `/api/v1/shift-breaks/?shift=<id>` | Shifts (local factory time; may cross midnight) and their breaks |
| `/api/v1/products/`, `/api/v1/product-cycle-times/` | Products (organization-wide) and line-specific ideal cycle times |
| `/api/v1/production-orders/?line=&status=&start=&end=` | Which product a line makes when (orders on one line cannot overlap) |
| `GET /api/v1/quality/summary/`, `/quality/pareto/?group_by=defect_type\|station\|machine\|product`, `/quality/trend/?group_by=hour\|shift\|day` | Defect counts and rates for `line`, `start`/`end` (false rejects excluded and counted separately) |
| `GET /api/v1/inspection-results/`, `.../export.csv` | One row per detected defect with its production context. Filters: `line`, `station`, `machine`, `defect_type` (code or `unknown`), `severity`, `product`, `reviewed`, `verdict`, `start`/`end` or `shift`+`date` |
| `GET/POST /api/v1/inspection-results/{id}/reviews/` | Review history, or a new review `{"verdict": "confirmed" \| "false_reject" \| "reclassified", "corrected_defect_type": <id>, "comment": ""}` (quality inspectors, supervisors, factory managers, platform admins) |
| `/api/v1/defect-types/`, `/api/v1/inspection-stations/?line=` | Defect catalogue (organization-wide) and inspection stations; `archive`/`restore` instead of deleting when used |

Shifts, products and orders: everyone can read; factory managers and platform admins can change (products: only with access to all factories). Every configuration change, including factories, lines and machines, is recorded in the audit log.

Downtime events can also be filtered by shift: `?shift=<id>&date=YYYY-MM-DD` (the day the shift starts, factory time).

OEE rules, settings and the reference cases are documented in [docs/PRODUCT.md §4](docs/PRODUCT.md).
| `POST /api/v1/events/`, `POST /api/v1/events/batch/` | Send machine events (line API key, not a user login) |
| `GET /api/v1/health/` | Backend and database status (no login needed) |

Users only ever see the factories their membership allows; anything else returns 404.
`start` and `end` are ISO 8601 date-times with a timezone, e.g. `2026-10-12T10:00:00Z` (`end` is excluded).

## Sending machine events

Machines (for now, the simulator) send events with a **line API key**, not a user login.

**1. Create a key** for a line (find the line id with `GET /api/v1/lines/` or in the admin; after `seed_demo`, Bottling Line 1 is usually `1`):

```powershell
docker compose exec backend python manage.py create_line_api_key 1 "Simulator"
```

The key (`lm_...`) is printed **once**. Only a hash is stored, so copy it now. Revoke keys in the Django admin (Line API keys → select → "Revoke selected keys").

**2. Send one event (PowerShell):**

```powershell
$headers = @{ Authorization = "Api-Key lm_xxxxxxxx_yyyyyyyy" }   # your key
$body = @{
  event_id            = [guid]::NewGuid().ToString()
  machine_external_id = "M04"
  event_type          = "machine_stopped"
  timestamp           = (Get-Date).ToUniversalTime().ToString("o")
  alarm_code          = "E-204"
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/events/ `
  -Headers $headers -ContentType "application/json" -Body $body
```

**3. Send a batch (up to 500 events):**

```powershell
$now = (Get-Date).ToUniversalTime().ToString("o")
$batch = ConvertTo-Json -InputObject @(
  @{ event_id = [guid]::NewGuid().ToString(); machine_external_id = "M01"; event_type = "machine_started"; timestamp = $now },
  @{ event_id = [guid]::NewGuid().ToString(); machine_external_id = "M03"; event_type = "production_count_updated"; timestamp = $now; count = 1250; rejected = 5 }
)
$result = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/events/batch/ `
  -Headers $headers -ContentType "application/json" -Body $batch
$result.summary
$result.results
```

**The same with curl** (Git Bash, WSL, macOS or Linux):

```bash
curl -X POST http://localhost:8000/api/v1/events/ \
  -H "Authorization: Api-Key lm_xxxxxxxx_yyyyyyyy" \
  -H "Content-Type: application/json" \
  -d '{"event_id": "7f1c2e9a-0b5d-4c3e-9a1f-2b6d8e4c1a70", "machine_external_id": "M04",
       "event_type": "machine_stopped", "timestamp": "2026-10-12T10:05:00Z", "alarm_code": "E-204"}'
```

**4. See the result** in `GET /api/v1/lines/1/status/` (with a user token, see "Demo data and logging in") or in the Django admin under *Production*.

What the backend answers:
- **`201 "created"`**: the event is stored.
- **`200 "duplicate"`**: that `event_id` was already stored. Nothing changes, so it's safe to retry.
- **`400 "rejected"`**: `errors` lists the reason per field.

A batch always answers `200` with one result per event, plus a `summary`.

Rules for every event:
- `event_id` is a UUID.
- `event_type` is one of the types in [docs/PRODUCT.md §13](docs/PRODUCT.md).
- `timestamp` includes a timezone and is at most 5 minutes in the future.
- `machine_external_id` belongs to the key's line.
- `count` and `rejected` are integers ≥ 0. `count` is required for `production_count_updated`.

## Downtime and line stop incidents

Every state event the line sends is turned into stop records automatically, right after it is stored:

- Each non-running period of a machine becomes a **downtime event**:

  | Machine state | Downtime category |
  |---|---|
  | stopped | breakdown |
  | blocked | blocked |
  | starved | starved |
  | planned stop | planned |
  | no data (including a silence longer than the factory's stale threshold) | no_data |

  Stops shorter than the factory's minimum (5 s by default) are ignored. A stop that is still going on has no end time yet.
- Breakdowns, blocked and starved stops that overlap form a **line stop incident**. The earliest breakdown is the **first observed stop**: a clue to where the problem began, not proof of the root cause.
- Lost production is always an **estimate** (`is_estimate: true`): duration × nominal speed.
- People classify stops with a reason. Every change is kept as history and recorded in the audit log (Django admin → *Audit log*).

Classify a stop (PowerShell, with a user token as in "Demo data and logging in"):

```powershell
$reasons = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/downtime-reasons/?factory=1" -Headers $headers
$jam = ($reasons | Where-Object code -eq "MECH-JAM").id
$body = @{ reason = $jam; comment = "Label web snapped" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/downtime-events/<id>/classifications/" `
  -Headers $headers -ContentType "application/json" -Body $body
```

If you change a factory's `minimum_stop_seconds` or `stale_after_seconds`, recompute the history with `rebuild_downtime --line <id>`. Classifications are kept.

## Live line dashboard

Open http://localhost:5173 and sign in, for example as `production_supervisor@demo-beverages.test` (the password is `DEMO_USER_PASSWORD` from `.env`). With only one line you go straight to its overview:

- **Header:** the factory, line and current shift with the time left, plus a clock. All times are in the factory's timezone, which is shown.
- **Machine cards:** the six machines in line order. Each shows its state (colour, icon *and* text), the time in that state, the shift count and the alarm.
  - A machine without recent data shows **Unknown**.
  - Click a card for its state timeline and its downtime this shift.
- **Incident banner:** while the line is stopped, "Line stopped for … — first observed stop: Labeler (alarm E-204)" plus the affected machines. The first stop's card is outlined.
- **OEE:** the current shift's OEE (refreshed every minute and when a stop starts or ends), the backend's notes, and an hourly chart.

The screen updates live over a WebSocket. If the connection drops it shows "Live updates paused, reconnecting…", checks every 15 s, and recovers by itself.

**Watch a jam happen** (about 15 minutes; the jam starts at minute 5):

```powershell
docker compose run --rm simulator python main.py --scenario scenarios/labeler_jam.yaml --mode realtime
```

What you'll see:
1. The labeler turns red with alarm E-204.
2. The capper turns amber "Blocked", the packer amber "Starved", then the filler, rinser and feeder are blocked.
3. The banner names the labeler as the first observed stop.
4. After 90 s everything returns to green.

Use `--mode realtime` for this. In accelerated mode the simulated clock catches up with real time only at the end of the run, so while it runs the data looks out of date and machines show "Unknown".

## Quality

Defects come from the simulator's `quality_defect_detected` events. Each becomes one **inspection result**: where (station, machine), when, what (defect type, confidence), and what the line was doing then (product, machine state, last alarm, and a line stop that ended shortly before). Good bottles are not stored one by one; the inspected volume comes from the machine counters.

- **Quality page** (`/lines/<id>/quality`): summary cards, a defect Pareto (click a bar to filter the table), the defect-rate trend, the results table and CSV export. Quality inspectors, supervisors and managers can **review** a result: confirm it, mark it a **false reject** (it stops counting as a defect, but stays visible with its history), or reclassify it.
- **Overview:** a quality card with the shift's defect rate, defects and results still to review, updated live.
- **Quality setup** (`/lines/<id>/quality-setup`, factory managers): defect types and inspection stations.
- **OEE quality is line-wide:** a bottle rejected at the labeler never reaches the packer, so it is added to the total count and counts as a quality loss (see [docs/PRODUCT.md §4](docs/PRODUCT.md)). Reviews never change OEE: a false reject was still removed from the line.

## Alerts

LineMind watches the lines and tells the right people when something needs attention. Each factory has **alert rules** (managers edit them at `/alert-rules`):

- a line stop lasting too long;
- the same stop repeating;
- a machine sending no data;
- low OEE for the shift;
- a high defect rate;
- stops still waiting for a reason.

When a rule's condition becomes true, one **alert** opens, never duplicates. It closes by itself when the condition clears.

- **The bell** in the top bar counts your unread notifications, live; **Alerts** (`/alerts`) lists every alert, with Acknowledge and Resolve.
- **Email** goes to the people whose role the rule names. In development no real mail server is needed: open **Mailpit** at http://localhost:8025 to read them. Choose which alerts reach you by email under **Settings**.
- **Escalation:** an alert nobody acknowledges within its time (default 15 min) is sent to the next people, e.g. factory managers.
- **Background services:** `worker` and `beat` (Celery) check the rules every 30 seconds. If they stop, `/api/v1/health/` says `"alerts": "stale"` and supervisors see a red warning in the top bar.

## Maintenance

Any problem seen in LineMind can become a **maintenance action**: press **Create action** next to a line stop, an alert, a recurring stop, a defect or on a machine page. The form is filled in for you and the evidence is linked.

- **Supervisors** assign it (the technician is notified) and set its priority and due date.
- **Technicians** start it, log what they found and did (time and parts), record the **confirmed diagnosis** (optionally applied to the linked stops, with a preview first) and complete it. An action past its due date raises an alert.
- **Before / after:** for a recurring problem, the action page compares stops per 10 hours of run time before and after the fix, so a quieter week doesn't look like an improvement. A supervisor then verifies whether the fix was effective.
- Open **Maintenance** in the top bar. The wrench badge counts your open assigned actions.

## AI production assistant

Ask questions about production in plain language (English, French or Arabic): **Assistant** in the left menu, or **Ask the assistant** on the line overview and the Downtime page (it starts with that line and time range). Answers are built only from LineMind's data: each one shows the time range used, the key figures, links to the source screens, notes from the data, and "How I got this" (the data tools it called). A number the assistant could not find in LineMind's data is marked **not verified**.

> **Privacy:** with a hosted model such as Groq, your question and the data the assistant looks up are sent to that provider. Use a free tier **with test data only**. In production LineMind uses a local model, so data stays in the factory.

### Set it up with Groq (development, free tier)

1. Create a free account at https://console.groq.com and an API key (**API Keys**).
2. In `.env`:
   ```
   ASSISTANT_BASE_URL=https://api.groq.com/openai/v1
   ASSISTANT_MODEL=openai/gpt-oss-120b
   ASSISTANT_API_KEY=gsk_...your key...
   ASSISTANT_EXTRA_PARAMS={"reasoning_effort": "low"}
   ```
   Groq serves open models with tool calling; see https://console.groq.com/docs/tool-use. `openai/gpt-oss-120b` is the development choice. `openai/gpt-oss-20b` is the production candidate: it runs on one 16 GB GPU with Ollama.
3. Restart the backend: `docker compose up -d backend`.
4. Turn the assistant on for your organization: Django admin → **Assistant settings** → add → organization *Demo Beverages*, **Enabled** (the change is audited).
5. Check: `GET /api/v1/assistant/status/` should say `"reachable": true, "tool_calling": true`.

**Free-tier limits.** Groq limits requests and tokens per minute. When a limit is hit, LineMind waits and retries (it respects `retry-after`); if that is not enough, the assistant says it is busy. Ask again a moment later.

**Later, a local model:** only the variables change, e.g. `ASSISTANT_BASE_URL=http://<server>:11434/v1`, `ASSISTANT_MODEL=gpt-oss:20b`, `ASSISTANT_API_KEY=` (empty).

**Without any model:** `ASSISTANT_PROVIDER=fake` shows a fixed reply, for working on the screens.

### Evaluate a model

```powershell
docker compose exec backend python manage.py assistant_eval
docker compose exec backend python manage.py assistant_eval --models openai/gpt-oss-120b,openai/gpt-oss-20b
```

The command loads its own "Assistant Eval" data (simulator fixtures with known answers), asks about 20 questions (the examples in English, French and Arabic, plus questions that must be answered "no data available"), and writes a report to `backend/reports/assistant_eval/`. It shows the correct numbers, sources cited, unverified numbers, invalid tool calls and response time per question. The production candidate (gpt-oss-20b) is listed separately, with every question where it differs from the development model. Requests are paced to stay within free-tier limits, so a run takes several minutes per model.

## Factory simulator

The simulator (`simulator/`) is a virtual bottling line: M01 Bottle feeder → M02 Rinser → M03 Filler → M04 Capper → M05 Labeler → M06 Packer, with a conveyor (buffer) between each pair. It plays a **scenario** (a YAML file in `simulator/scenarios/`) and sends the resulting machine events to the event API.

### One-time setup

```powershell
# 1. Backend running and demo data loaded
docker compose up --build -d
docker compose exec backend python manage.py seed_demo

# 2. Create an API key for Bottling Line 1 (line id 1 after seed_demo)
docker compose exec backend python manage.py create_line_api_key 1 "Simulator"

# 3. Put the printed key in .env:
#    SIMULATOR_API_KEY=lm_xxxxxxxx_yyyyyyyy
```

The simulator always reaches the backend inside Docker (`http://backend:8000`), whatever `BACKEND_PORT` is.

### Run it (PowerShell, from the project folder)

| Mode | Command | Timestamps |
| --- | --- | --- |
| Backfill (history, as fast as possible) | `docker compose run --rm simulator python main.py --scenario scenarios/reference_1h.yaml --mode backfill --start 2026-10-05T06:00:00Z` | from `--start` (must end in the past); without `--start`, the scenario's `start` |
| Accelerated | `docker compose run --rm simulator python main.py --scenario scenarios/labeler_jam.yaml --mode accelerated --speed 60` | 1 real second = 60 simulated seconds; simulated time **ends now** (15 min in 15 s) |
| Real time | `docker compose run --rm simulator python main.py --scenario scenarios/sensor_dropout.yaml --mode realtime` | starts now, follows the clock |
| To a file (no backend needed) | `docker compose run --rm simulator python main.py --scenario scenarios/normal_shift.yaml --mode backfill --output file` | written to `simulator/data/<scenario>-<start>.jsonl` |

Other options:
- `--duration 30m` overrides the scenario length.
- `--file data\my_run.jsonl` chooses the output file.
- `--drain-timeout 300` is how long to keep retrying unsent events at the end.
- `--log-level DEBUG` gives more detail.

At the end the simulator prints a summary:
- per machine: produced, rejected, good, state changes, and time in each state;
- events created, duplicate and rejected, with the rejection reasons.

Then look at the results:
- `GET /api/v1/lines/1/status/`
- `GET /api/v1/machines/{id}/state-events/`
- the Django admin (*Production*)

After a **backfill**, `status` reports every machine as `unknown` (`is_stale: true`), because the data is in the past. The last real state is in `reported_state`. Use accelerated or real time mode to see live states.

### Bundled scenarios

| File | What happens | Known answer |
| --- | --- | --- |
| `reference_1h.yaml` | 1 h at 6,000/h, packer (M06) stopped 5 min, 3% exact defects at M06 | M06: produced **5,500**, rejected **165**, good **5,335** |
| `labeler_jam.yaml` | 15 min; labeler jams at 10:05 for 90 s | capper blocked 10:05:03, packer starved 10:05:08, filler blocked 10:05:40 |
| `sensor_dropout.yaml` | 10 min; the filler's sensor sends nothing from minute 3 to 5 | M03 shows `unknown` once its data is stale, then normal again |
| `normal_shift.yaml` | 8 h with four short faults, a 30-min break and ~1% random defects | realistic history |

### If the backend is down

Events are saved to a queue file (`simulator/data/queue.sqlite`) **before** they are sent. If the backend can't be reached, the simulator retries with growing waits (1 s, 2 s, 4 s … up to 60 s). Whatever is still unsent at the end stays in the file and is sent first by the next run, with the same `event_id`s. Running the same scenario with the same start again is safe: the backend answers `duplicate` and nothing is counted twice.

## Troubleshooting

- **"port is already allocated" for 8000.** Another program is using port 8000. Set `BACKEND_PORT=8001` in `.env` and restart. The frontend still works at http://localhost:5173.
- **"port is already allocated" for 5173.** Stop the other program using that port.
- **The login page shows `Backend: unreachable`.** Check `docker compose logs backend`.
- **The login page shows `Database: error`.** Check `docker compose logs db`. Make sure `.env` exists and its `POSTGRES_*` values haven't changed since the database volume was first created. If they have, run `docker compose down -v` to start with a fresh database.
- **Migration errors after pulling new code** (e.g. `InconsistentMigrationHistory`). The development database was created by older code. Reset it with `docker compose down -v` and start again. This deletes all local data; re-run `seed_demo` afterwards.
- **`failed to connect to the docker API`.** Docker Desktop isn't running. Start it and wait for "Engine running".
