# LineMind — Product Specification

> Place this file at `docs/PRODUCT.md`. It is the source of truth for what LineMind is and how it behaves.
> `CLAUDE.md` (repo root) holds the engineering rules. When the two disagree, ask before proceeding.

---

## 1. Vision

LineMind is a web-based, multi-tenant SaaS platform that monitors factory production lines, identifies exactly which machine stopped and why, detects defective products, and turns that data into accountable actions.

It answers four questions:

1. **What is happening?** Live machine states and production counts.
2. **Where did it happen?** The exact machine and moment of a stop or defect.
3. **Why did it happen?** Evidence: alarm codes, state sequences, history.
4. **What should we do?** Assigned actions, and a check that they worked.

The differentiator is the **link** between machine events, quality results and maintenance actions — not the presence of an AI chatbot.

**First use case:** beverage bottling lines. The data model stays generic so other industries can be added later.

**Development mode:** no hardware. A Python simulator generates realistic factory events and sends them to the backend over plain HTTP. No MQTT.

---

## 2. Glossary

| Term | Meaning |
| --- | --- |
| Production line | Ordered chain of machines a product passes through |
| Running | Machine is producing |
| Stopped | Machine has its own problem (breakdown, jam) |
| Blocked | Machine is fine but cannot output because downstream is full/stopped |
| Starved | Machine is fine but receives no input because upstream stopped |
| Planned stop | Scheduled stop: break, cleaning, changeover |
| Unknown | No recent data from the machine (stale telemetry) |
| Changeover | Switching the line from one product to another |
| Micro-stop | Very short stop (seconds) |
| Ideal cycle time | Fastest possible time to produce one unit |
| OEE | Overall Equipment Effectiveness = Availability × Performance × Quality |
| Downtime reason | Label explaining a stop (e.g. "Label roll empty") |
| PLC | Industrial controller of a machine (simulated for now) |
| Alarm code | Error code raised by a machine (e.g. `E-204`) |
| Tenant | A customer organization |
| Edge | Computer located in the factory, next to the line |

---

## 3. Modules

| # | Module | Purpose | Release |
| --- | --- | --- | --- |
| 1 | Production monitoring | Live states, counts, targets, OEE | MVP |
| 2 | Stoppage intelligence | Per-machine stops, first stop vs consequences, reasons, impact | MVP |
| 3 | AI quality inspection | Defect detection with camera + vision model | Prototype in MVP |
| 4 | Maintenance & corrective actions | Tasks from events, owner, deadline, before/after check | Release 2 (light) |
| 5 | AI production assistant | Natural-language questions answered from platform data | Release 2 |
| 6 | Multi-site analytics | Compare factories, lines, shifts | Release 3 (data model ready from day one) |

---

## 4. Module 1 — Production monitoring

### Features
- **Hierarchy:** Organization → Factory → ProductionLine → Machine.
- **Machine states:** `running`, `stopped`, `blocked`, `starved`, `planned_stop`, `unknown`.
- **Counts:** actual vs target output; good vs rejected units.
- **Cycle time:** actual vs ideal.
- **Shifts:** schedules, breaks, targets per shift.
- **OEE dashboard:** availability, performance, quality, OEE.
- **History:** filter by date, shift, product, machine, production order.
- **Alerts:** long stops, low output, excessive rejects.
- **Reports:** shift, daily, weekly, monthly.

### OEE definitions (must be implemented exactly)
- Planned production time = shift time − planned stops
- Run time = planned production time − unplanned downtime
- **Availability** = Run time ÷ Planned production time
- **Performance** = (Ideal cycle time × Total count) ÷ Run time
- **Quality** = Good count ÷ Total count
- **OEE** = Availability × Performance × Quality

Treatment of planned stops, micro-stops and changeovers is a **per-factory setting** and must be documented in code and UI. Default: planned stops and scheduled breaks are excluded from planned production time; changeovers count as downtime unless configured as planned; micro-stops below the minimum stop threshold are not recorded as downtime events but still reduce performance.

### Reference test case (OEE)
| Input | Value |
| --- | --- |
| Shift length | 480 min |
| Planned break | 30 min |
| Unplanned downtime | 50 min |
| Ideal cycle time | 0.6 s |
| Total count | 36,000 |
| Rejects | 720 |

Expected: planned time 450 min, run time 400 min, availability 88.89%, performance 90.00%, quality 98.00%, **OEE 78.40%**.

### Reference test case (OEE, end to end)
The simulator's `reference_1h` scenario (§14), sent through the event API and downtime derivation, for a 1-hour range fully inside a shift without breaks, with a product of ideal cycle time 0.6 s:

| Input | Value |
| --- | --- |
| Planned production time | 60 min |
| Unplanned downtime (packer stopped) | 5 min |
| Run time | 55 min |
| Total count (counting machine) | 5,500 |
| Rejects | 165 |
| Good count | 5,335 |

Expected: availability 91.67%, performance 100.00%, quality 97.00%, **OEE 88.92%**, no warnings, data coverage 100%.

### OEE settings (per factory, `Factory.oee_settings`)
| Setting | Default | Meaning |
| --- | --- | --- |
| `planned_stops_excluded` | `true` | Shift breaks and stops with state `planned_stop` are removed from planned production time. If `false`, breaks stay in planned time and planned stops count as unplanned downtime. |
| `changeovers_are_planned` | `false` | A stop is a changeover when its current classification uses a reason marked `is_changeover`. By default changeovers count as unplanned downtime; if `true` they are removed from planned production time. |
| `no_data_handling` | `"downtime"` | Time without data from the counting machine (a `no_data` stop, before its first event, or after its data went stale) counts as unplanned downtime. With `"exclude"` it is removed from planned production time. |
| `minimum_stop_seconds` | `5` | Stops shorter than this are not recorded as downtime events; they still reduce performance (fewer units in the same run time). |

Changing `minimum_stop_seconds` (or `stale_after_seconds`) needs `rebuild_downtime` to update existing downtime events.

### How the OEE inputs are built
All times are intersected and merged so that no second is ever counted twice. For a line and a time range (never beyond "now"):
1. **Shift time** = the factory's shift occurrences in the range (shift times are local factory time; a shift may cross midnight and belongs to the day it starts).
2. **Planned production time** = shift time minus breaks, planned stops, changeovers and no-data time, *as the settings above decide*.
3. **Unplanned downtime** = the counting machine's breakdown, blocked and starved time (plus changeovers, no-data time and planned stops when the settings count them as downtime), only inside planned production time.
4. **Run time** = planned production time − unplanned downtime.
5. **Counts** come from the line's counting machine (default: the last machine). Counters are cumulative: production is the difference between two consecutive readings, credited to the later reading's time, and only counted if that time is inside planned production time. A machine's first reading is only a starting point. A counter that goes down is a reset (the new value counts from zero, with a warning). Rejects come from the same machine's rejected counter.
6. **Ideal cycle time** = that of the product of the production order covering each reading (a line-specific value overrides the product's). Ideal production time = Σ ideal cycle time × count, which equals ideal cycle time × total count for one product. Without an order, the line's nominal speed (slowest machine) is used and a warning is returned.
7. Availability, Performance, Quality and OEE follow the definitions above. Performance above 100% is never capped; it returns a warning (the ideal cycle time is probably wrong). With no planned production time all results are null with a reason; a line that never ran has OEE 0.
8. **Data coverage** = share of planned time that has data from the counting machine (warning below 90%).
9. Results per hour, day or shift add up exactly: the total of a grouped request is calculated from the summed inputs, never by averaging percentages.

**Known limitation.** Quality currently only counts rejects reported by the line's counting machine. Bottles rejected upstream (e.g. at the labeler) never reach the counting machine, so they appear as a performance loss instead of a quality loss. Build step 9 must revisit this so that line-wide rejects count toward quality.

---

## 5. Module 2 — Stoppage intelligence

### Features
- Detect a stop from a state change, or from a counter that stops increasing.
- Record machine, start, end, duration.
- Classify: planned stop, breakdown, blocked, starved, material shortage, unknown.
- Operator enters or selects a reason.
- Attach alarm codes raised near the stop.
- Estimate lost production = stop duration × nominal speed (labelled **estimate**).
- Detect recurring stops.
- Rank possible causes using alarms and history (later, AI-assisted).
- Escalate to maintenance when a stop exceeds a configured threshold.

### First stop vs consequences
When one machine stops, others become blocked (upstream) or starved (downstream). Example:

| Time | Machine | Transition | Meaning |
| --- | --- | --- | --- |
| 10:05:00 | Labeler | running → stopped | Initiating event |
| 10:05:03 | Capper | running → blocked | Consequence |
| 10:05:08 | Packer | running → starved | Consequence |
| 10:05:40 | Filler | running → blocked | Consequence |

The system records **every** transition, groups them into one **line stop incident**, and marks the labeler as the **first observed stop**. The first observed stop is a clue, not proof of root cause.

### Acceptance criteria
- Every detected stop has a machine and timestamps.
- A configurable minimum duration (default 5 s) filters sensor flicker.
- Durations are computed consistently in one place.
- Operators can classify/correct an event; the original machine data is preserved.
- History filterable by machine, shift, reason.
- Loss figures are labelled as estimates when actual loss is unmeasured.

---

## 6. Module 3 — AI quality inspection

Start with one line, one inspection station, one defect type.

### Flow
1. Bottle reaches inspection station; camera is triggered.
2. Image preprocessed (OpenCV).
3. Vision model (e.g. YOLO) returns class + confidence.
4. Result compared with a validated threshold → pass/fail.
5. Local controller rejects the bottle (local loop, never dependent on the cloud).
6. Result sent to LineMind; linked to machine events and batch.

### Defect catalogue
| Code | Defect |
| --- | --- |
| Q01 | Empty or underfilled bottle |
| Q02 | Missing label |
| Q03 | Misaligned or wrinkled label |
| Q04 | Missing or tilted cap |
| Q05 | Unreadable or incorrect batch/date code (OCR) |
| Q06 | Damaged bottle |

### Rules
- No automatic rejection until validated: labelled dataset, separate test set, precision/recall/false-reject/missed-defect measured **per defect type**, varied conditions tested, reject timing verified, safe fallback defined.
- Shadow mode (log, do not reject) before any physical rejection.
- During development, defects come from the simulator; the vision prototype uses sample images.

---

## 7. Module 4 — Maintenance and corrective actions
- Create a request from a stop event.
- Owner, priority, deadline, status.
- Problem, diagnosis, repair, parts, resolution.
- Linked to stop and quality records.
- Overdue notifications.
- Before/after comparison of the related metric.
- Lightweight only; no spare-parts inventory or purchasing.

---

## 8. Module 5 — AI production assistant
- Answers questions using platform data only.
- Pattern: the LLM calls backend tools (e.g. `get_downtime_by_machine(line_id, start, end)`); Python code runs queries and computes all metrics; the LLM only summarizes.
- Every answer shows time range, metrics, links to source events, and uncertainty.
- Tools enforce the requesting user's permissions.
- Example questions: "Which machine caused the most downtime this week?", "Did label defects increase after the last changeover?"

---

## 9. Module 6 — Multi-site analytics
- Many organizations, factories, lines, machines.
- Per-site permissions.
- Standard KPIs with configurable local rules.
- Factory and group reports; CSV/PDF export.
- Comparisons must account for product, speed and schedule differences.

---

## 10. Roles and permissions (RBAC)

| Role | Permissions |
| --- | --- |
| Platform admin | Manage tenants, system configuration, platform health |
| Factory manager | Factory KPIs, users, targets, reports |
| Production supervisor | Monitor lines, classify stops, review shifts |
| Machine operator | Assigned lines, enter downtime reasons |
| Maintenance technician | Machine events, assigned maintenance actions |
| Quality inspector | Review defects, confirm/correct inspection results |
| Analyst | Read historical data, dashboards, exports |

A user from Factory A must never access Factory B's data, including by changing IDs in URLs or API calls. Enforced server-side.

---

## 11. Architecture

```
Python simulator ──HTTP POST──> Django + DRF ──> PostgreSQL
                                     │
                                     ├──> React + TypeScript dashboard (REST + live updates)
                                     └──> Celery + Redis (reports, alerts, scheduled jobs)

Later: edge connector (OPC UA / Modbus) and local vision replace the simulator as event sources.
```

- Modular monolith, not microservices.
- Machine control and rejection stay local to the factory; the platform stores, analyses, displays and reports.
- The event source is behind an interface so a real connector can replace the simulator without changing the backend.

### Stack
| Layer | Technology |
| --- | --- |
| Frontend | React + TypeScript (Vite) |
| Backend | Django + Django REST Framework |
| Database | PostgreSQL |
| Live updates | Django Channels (WebSockets) or server-sent events |
| Background jobs | Celery + Redis |
| Simulator | Python (`requests`/`httpx`) |
| Vision (later) | Python, OpenCV, YOLO-type model |
| File storage (later) | S3-compatible (MinIO locally) |
| Deployment | Docker Compose |

### Repository layout
```
linemind/
├── backend/
│   ├── config/
│   ├── apps/
│   │   ├── accounts/
│   │   ├── organizations/
│   │   ├── production/
│   │   ├── downtime/
│   │   ├── quality/
│   │   ├── maintenance/
│   │   ├── analytics/
│   │   └── notifications/
│   ├── manage.py
│   └── requirements.txt
├── simulator/
│   ├── main.py
│   ├── factory.py
│   ├── machines.py
│   ├── scenarios.py
│   └── settings.py
├── frontend/
├── vision/            # later
├── docs/
│   └── PRODUCT.md
├── compose.yaml
├── CLAUDE.md
└── README.md
```

---

## 12. Data model

| Entity | Key fields |
| --- | --- |
| Organization | name, subscription, settings |
| Factory | organization, name, timezone, OEE rule settings |
| ProductionLine | factory, name, configuration |
| Machine | line, name, type, position (order in line), external_id, nominal speed |
| MachineSignal | machine, name, source, unit |
| MachineStateEvent | machine, state, started_at, ended_at, source, event_id (unique) |
| DowntimeEvent | machine, incident, started_at, ended_at, duration, classification, reason, reason_source, is_first_stop |
| LineStopIncident | line, started_at, ended_at, first_machine |
| Shift | factory, name, start, end, breaks |
| Product | organization, name, ideal_cycle_time |
| ProductionOrder | product, line, planned_quantity, start, end |
| ProductionEvent | machine, timestamp, count, rejected, event_id (unique) |
| InspectionStation | line, machine, camera configuration |
| InspectionResult | station, timestamp, defect_code, confidence, outcome, reviewed_by |
| QualityImage | inspection_result, storage_key, retention |
| MaintenanceAction | machine, downtime_event, assignee, priority, status, due_date, resolution |
| Alert | source event, recipient, severity, acknowledged_at |
| AuditLog | user, action, entity, before, after, timestamp |

Indexes on machine, timestamps, factory and common combinations.

### Observations vs conclusions
Stored separately; one never overwrites another:

| Type | Example | Created by |
| --- | --- | --- |
| Observation | Labeler stopped at 10:05:00 | Machine/simulator |
| Operator classification | "Label jam" | Operator |
| AI assessment | "Possible label-feed issue" | AI, marked as suggestion |
| Confirmed diagnosis | "Worn roller, replaced" | Authorized technician |

---

## 13. Event API (simulator → backend)

`POST /api/v1/events/` — authenticated with a per-line API key (not a user session).

```json
{
  "event_id": "7f1c2e9a-0b5d-4c3e-9a1f-2b6d8e4c1a70",
  "machine_external_id": "M04",
  "event_type": "machine_stopped",
  "timestamp": "2026-10-12T10:05:00Z",
  "alarm_code": "E-204",
  "count": 18420,
  "rejected": 12,
  "payload": {}
}
```

Event types: `machine_started`, `machine_stopped`, `machine_blocked`, `machine_starved`, `planned_stop_started`, `planned_stop_ended`, `production_count_updated`, `quality_defect_detected`, `sensor_disconnected`, `sensor_reconnected`.

Rules: timestamps in UTC; `event_id` is unique (duplicates ignored, not double-counted); out-of-order events are accepted and ordered by timestamp; batch endpoint `POST /api/v1/events/batch/` accepts a list.

---

## 14. Simulator

- Virtual bottling line: **M01 Bottle feeder → M02 Rinser → M03 Filler → M04 Capper → M05 Labeler → M06 Packer**.
- Each machine: nominal speed, state, counter, defect probability.
- Buffers (conveyors) between machines with a capacity; when a machine stops, upstream machines become blocked when the buffer fills and downstream machines become starved when it empties.
- Scenarios define injected faults with known expected outcomes (e.g. capper jam 90 s at 10:05; 3% missing labels; sensor disconnected 2 min).
- Time can run in real time or accelerated.
- Sends events to the API over HTTP; retries and buffers on failure; never sends duplicates with a new `event_id`.

### Reference test case (simulator)
1 h at 6,000 bottles/h, 5 min unplanned downtime, 3% defects → planned 6,000; lost 500; produced 5,500; rejects 165; good 5,335.

---

## 15. Security, reliability, safety
- Secure login, password reset, RBAC, tenant isolation on every query, job, report and file.
- TLS, secrets in environment variables, audit log of configuration changes and corrections.
- Backups with tested restore; staging and production separated.
- Stale telemetry → state `unknown`, never `running`.
- Clock: all timestamps UTC; display in factory timezone.
- Raw observations immutable; classification changes logged.
- LineMind is never the sole safety controller; rejection logic stays local and is validated with factory automation engineers.

---

## 16. Success metrics
Data quality (missing/duplicate events, timestamp accuracy) · monitoring accuracy and latency · OEE agreement with verified records · downtime detection delay and classification accuracy · quality AI precision/recall per defect · maintenance time-to-resolve and recurrence · AI assistant correctness and traceability · business impact (lost time, scrap, good units).

---

## 17. Build plan (one step per Claude Code session)

| Step | Deliverable |
| --- | --- |
| 1 | Project skeleton: Docker Compose (PostgreSQL, Django + DRF, React + Vite), health endpoint, one test |
| 2 | Organizations, factories, lines, machines, users, roles, tenant isolation + permission tests |
| 3 | Event API: validation, idempotency, storage, API keys |
| 4 | Simulator: 6 machines, buffers, blocked/starved, scenarios |
| 5 | Downtime detection: stop records, incidents, first stop, threshold |
| 6 | Shifts, products, OEE with reference test cases |
| 7 | React dashboard: line overview, machine status, live updates |
| 8 | Downtime analysis UI: history, filters, Pareto, operator reasons |
| 9 | Quality records from simulated defects |
| 10 | Alerts → maintenance actions → AI assistant → vision prototype |

Out of MVP scope: MQTT, real PLC integration, automatic physical rejection, predictive maintenance, ERP integration, spare-parts inventory.
