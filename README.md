# LineMind

Manufacturing intelligence platform for bottling lines: production monitoring, downtime analysis, quality, maintenance and AI insights. The full specification is in [docs/PRODUCT.md](docs/PRODUCT.md).

## What runs where

| Service    | What it is                          | URL on your machine                        |
| ---------- | ----------------------------------- | ------------------------------------------ |
| `frontend` | React + TypeScript (Vite dev server) | http://localhost:5173                      |
| `backend`  | Django + Django REST Framework      | http://localhost:8000/api/v1/health/       |
| `db`       | PostgreSQL 16                       | internal only (not exposed to Windows)     |

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

Then open http://localhost:5173. You should see **LineMind** with `backend: ok` and `database: ok`.

Stop everything with `Ctrl+C`, or from another terminal with `docker compose down`.
Your database data is kept in a Docker volume. `docker compose down -v` deletes it.

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
| Create an admin user         | `docker compose exec backend python manage.py createsuperuser`   |
| Frontend lint                | `docker compose exec frontend npm run lint`                      |
| Frontend type check          | `docker compose exec frontend npm run typecheck`                 |

The `exec` commands need the services to be running (`docker compose up` in another terminal, or with `-d`).

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
| `GET /api/v1/health/` | Backend and database status (no login needed) |

Users only ever see the factories their membership allows; anything else returns 404.

Code changes are picked up automatically: Django restarts itself and Vite hot-reloads the page.
If you change `requirements.txt` or `package.json`, rebuild with `docker compose up --build`.
For a new frontend package, also run `docker compose down` first, so the container's `node_modules` volume is recreated.

## Troubleshooting

- **"port is already allocated" for 8000.** Another program is using port 8000. Set `BACKEND_PORT=8001` in `.env` and restart. The frontend still works at http://localhost:5173.
- **"port is already allocated" for 5173.** Stop the other program using that port.
- **The page shows `backend: unreachable`.** Check `docker compose logs backend`.
- **The page shows `database: error`.** Check `docker compose logs db`. Make sure `.env` exists and its `POSTGRES_*` values haven't changed since the database volume was first created. If they have, run `docker compose down -v` to start with a fresh database.
- **Migration errors after pulling new code** (e.g. `InconsistentMigrationHistory`). The development database was created by older code. Reset it with `docker compose down -v` and start again. This deletes all local data; re-run `seed_demo` afterwards.
- **`failed to connect to the docker API`.** Docker Desktop isn't running. Start it and wait for "Engine running".
