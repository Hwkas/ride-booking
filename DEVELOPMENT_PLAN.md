The scope is locked. Here is the build order. Each step is small, ends in a working and tested state, and gets its own commit, which gives the clean git history the reviewers want.

## Development Steps

| # | Step | What gets built | Done when |
|---|---|---|---|
| **1** | **Project setup** | Dependencies in `pyproject.toml` (via `uv`), ruff config, `.env.example`, updated `.gitignore`, `app/` folder layout | `uv sync` works and ruff passes |
| **2** | **Config & app skeleton** | `core/config.py` (pydantic-settings), `main.py` app factory, `GET /health` | The app runs and `/health` returns 200 |
| **3** | **Docker & database** | `docker-compose.yml` (Postgres + API), `Dockerfile`, async engine/session in `db/` | `docker compose up` starts both, and `/health` checks the database connection |
| **4** | **Models & migrations** | `User`, `Driver` and `Ride` models, enums, constraints and indexes; Alembic setup with the initial migration | `alembic upgrade head` creates the schema |
| **5** | **Error handling foundation** | Domain exceptions, one central exception handler, a consistent error body | Errors return `{ "error": { code, message } }` |
| **6** | **Test infrastructure** | pytest config, test database, per-test transaction rollback, async client fixture, factories | One smoke test passes against Postgres |
| **7** | **Authentication** | Password hashing, JWT, `register`, `login`, `GET /users/me`, current-user and role-guard dependencies | Auth tests pass: duplicate email, bad login, invalid or expired token |
| **8** | **Driver profile & availability** | `POST /drivers/profile`, `GET /drivers/me`, `PATCH /drivers/me/availability`, admin `GET /drivers` | Driver tests pass |
| **9** | **Ride state machine** | A pure transition table plus validation (no database) | Unit tests cover every valid and invalid transition |
| **10** | **Ride request & assignment** | `POST /rides`: fare estimate, nearest-driver lookup with `FOR UPDATE SKIP LOCKED`, a 409 when no driver is free | Assignment tests pass, plus a concurrency test showing two requests can't get the same driver |
| **11** | **Ride lifecycle endpoints** | `start`, `complete` (sets `final_fare`, frees the driver), `cancel` (frees the driver), with role and ownership checks | Lifecycle and authorization tests pass |
| **12** | **Ride listing** | `GET /rides` (scoped to the caller, paginated, status filter) and `GET /rides/{id}` | Listing and access tests pass |
| **13** | **Driver history & earnings** | `GET /drivers/me/rides` and `GET /drivers/me/earnings`, aggregated in SQL with a day/week/month breakdown | Earnings tests pass, including totals, excluded cancellations and an empty date range |
| **14** | **Admin seeding** | A script (or env variables) to create the admin user | An admin can log in |
| **15** | **Polish & coverage** | Coverage at 85% or more, OpenAPI tags and examples, final lint pass | All tests pass and the Swagger docs are clean |
| **16** | **README & submission** | Setup, how to run tests, API overview, design decisions, assumptions, future work; push to GitHub | The repository is ready to share |

Each step depends only on the ones before it, so we can stop after any step and still have a working app.

Should I start **Step 1: Project setup**?