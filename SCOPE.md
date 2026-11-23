# Scope: Ride Booking & Driver Assignment API

> This is the planning document, kept up to date with what was built. For setup,
> usage and the reasoning behind each design decision, start with the
> [README](README.md).

## 1. Objective

Build a simplified backend system that provides user authentication, ride creation, driver assignment, ride status management and sound database handling.

**Evaluation focus:** code quality, architecture, database design, error handling, problem-solving approach and automated testing.

> **Note:** The detailed assessment requirements were not available when this scope was written. Any explicit requirements in that document take precedence over the assumptions below.

---

## 2. Tech Stack

| Concern | Choice |
|---|---|
| Language | Python 3.13 |
| Framework | FastAPI |
| Validation | Pydantic v2, pydantic-settings for config |
| Database | PostgreSQL (19 in Docker Compose) |
| ORM | SQLAlchemy 2.x (async for the API, sync for scripts and migrations; `psycopg` 3 driver) |
| Migrations | Alembic (applied automatically when the API container starts) |
| Auth | JWT (PyJWT) + bcrypt password hashing |
| Testing | pytest, pytest-asyncio, pytest-cov, httpx `AsyncClient`, against a real Postgres test DB |
| Tooling | uv, ruff, Docker + Docker Compose, Makefile |

---

## 3. Domain Model

Enums are stored as `VARCHAR` + `CHECK` (adding a value is a simple migration). Every table has an integer `id` primary key and `created_at` / `updated_at` (`timestamptz`). All constraints have deterministic names via a naming convention.

### `users`
| Column | Type | Notes |
|---|---|---|
| email | varchar(254) | unique; stored lower-cased |
| password_hash | varchar(255) | bcrypt; never the raw password |
| full_name | varchar(128) | |
| role | enum | `rider`, `driver`, `admin` |
| is_active | bool | default true; disabling revokes existing tokens |

### `drivers`
| Column | Type | Notes |
|---|---|---|
| user_id | FK → users | unique (one profile per user); `ON DELETE CASCADE` |
| vehicle_model | varchar(100) | |
| license_plate | varchar(20) | unique; normalised (upper-case, no spaces/hyphens) |
| is_available | bool | default false (profiles start offline) |
| available_since | timestamptz | when the driver last became free; tie-breaker for "longest idle" |
| current_lat / current_lng | numeric(9,6) | optional; both or neither; used for nearest-driver search |

### `rides`
| Column | Type | Notes |
|---|---|---|
| rider_id | FK → users | `ON DELETE RESTRICT` |
| driver_id | FK → drivers | NOT NULL (every ride has a driver); `ON DELETE RESTRICT` |
| pickup_address / dropoff_address | varchar(255) | |
| pickup_lat / pickup_lng / dropoff_lat / dropoff_lng | numeric(9,6) | CHECK value ranges |
| distance_km | numeric(8,2) | straight-line (haversine) distance, stored for auditability |
| fare_estimate | numeric(10,2) | set at request time: base + per-km × distance |
| status | enum | `assigned`, `in_progress`, `completed`, `cancelled` |
| final_fare | numeric(10,2) | set on completion; source of driver earnings |
| started_at, completed_at, cancelled_at | timestamptz | lifecycle audit (`created_at` is the request time) |
| cancellation_reason | varchar(255) | optional |

**Constraints and indexes:**
- CHECK constraints on coordinate ranges and non-negative distance and fares.
- CHECK constraints tie each status to its data: `in_progress` needs `started_at`; `completed` needs `started_at`, `completed_at` and `final_fare`; `cancelled` needs `cancelled_at`.
- Partial unique index: a driver can have at most one active ride (`assigned` / `in_progress`).
- Partial unique index: a rider can have at most one active ride (a second request returns 409).
- Partial index on available drivers (by `available_since`) for assignment.
- Composite index `(driver_id, status, completed_at)` for driver history and earnings; `(rider_id, created_at)` for rider listing; index on `status`.

---

## 4. Ride Lifecycle (State Machine)

```
(request) ──► ASSIGNED ──► IN_PROGRESS ──► COMPLETED
                 │
                 └──────► CANCELLED
```

| Transition | Allowed actor | Side effects |
|---|---|---|
| (request) → ASSIGNED | System, at creation; only if a driver is available | driver marked busy |
| ASSIGNED → IN_PROGRESS | Assigned driver | `started_at` |
| IN_PROGRESS → COMPLETED | Assigned driver | `completed_at`, `final_fare`, driver back online |
| ASSIGNED → CANCELLED | Rider (owner), assigned driver, admin | `cancelled_at`, optional reason, driver back online |

There is no `REQUESTED` or pending status. A ride only exists once a driver has been assigned to it.

**Rules:**
- All transitions are defined in one table-driven state machine (`app/services/ride_lifecycle.py`), unit-tested against every status × action × actor combination.
- Permission is checked before state: an actor who may never perform an action gets **403**; an allowed actor at the wrong time gets **409** `INVALID_STATE_TRANSITION`.
- Callers unrelated to a ride get **404**, so ride ids cannot be probed.
- The ride and its driver are row-locked before a transition, so concurrent actions on one ride apply one at a time.

---

## 5. Driver Assignment

- **Strategy:** among active, available drivers, pick the nearest (haversine distance computed in SQL); drivers without a location go last; ties go to the longest-idle driver (`available_since`).
- **Flow on `POST /rides`:** in one transaction, lock that driver with `SELECT ... FOR UPDATE SKIP LOCKED`, create the ride as `ASSIGNED`, and mark the driver unavailable.
- **Concurrency safety:** `SKIP LOCKED` means concurrent requests move on to the next driver instead of waiting, so two requests never get the same driver. The partial unique indexes are the final guard if a race slips past the application checks; violations are mapped to the matching 409.
- **Lock order:** lifecycle actions lock ride → driver; assignment and availability changes lock only the driver. A single order means no deadlocks.
- **No driver available:** nothing is persisted. The request fails with **409 `NO_DRIVER_AVAILABLE`**, and the rider tries again later.
- **One active ride per rider:** a second request returns **409 `ACTIVE_RIDE_EXISTS`**.
- **Availability:** the driver becomes unavailable on assignment and available again on completion or cancellation. Going online is refused while the driver has an active ride.
- **No queue:** there are no pending requests, no background matching and no manual assign endpoint.

---

## 6. API Endpoints (`/api/v1`)

### Auth & Users
| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/auth/register` | Register as rider or driver (admins cannot self-register) | Public |
| POST | `/auth/login` | Returns a JWT access token | Public |
| GET | `/users/me` | Current user profile | Any |

### Drivers
| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/drivers/profile` | Create driver profile (vehicle info); starts offline | Driver |
| GET | `/drivers/me` | Own driver profile | Driver |
| PATCH | `/drivers/me/availability` | Go online/offline, update location | Driver |
| GET | `/drivers/me/rides` | Full ride history; paginated; status filter; `from`/`to` on request date | Driver |
| GET | `/drivers/me/earnings` | Earnings summary (see below) | Driver |
| GET | `/drivers` | List drivers; filter by availability; paginated | Admin |

**Earnings response** (`?from=2026-11-01&to=2026-11-30&group_by=day|week|month`):
```json
{
  "from": "2026-11-01",
  "to": "2026-11-30",
  "group_by": "day",
  "total_earnings": "1240.50",
  "completed_rides": 42,
  "average_fare": "29.54",
  "breakdown": [
    { "period": "2026-11-01", "earnings": "85.00", "rides": 3 }
  ]
}
```
- Earnings are the sum of `final_fare` over the driver's `completed` rides, aggregated in SQL (`SUM`, `COUNT`, `date_trunc`), not in Python. Cancelled rides earn nothing.
- `from` and `to` are whole UTC days, inclusive, filtering on completion time; both are optional (default: all time). A reversed range returns 422.
- `breakdown` is `null` unless `group_by` is given; it lists only periods with earnings, oldest first. Weeks start on Monday. Grouping is done in UTC regardless of the database session time zone.
- Monetary values are `Decimal`, serialized as strings so no precision is lost.

### Rides
| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/rides` | Request a ride; assigns an available driver or returns 409 `NO_DRIVER_AVAILABLE` | Rider |
| GET | `/rides` | Rides scoped to the caller (admins: all); paginated; repeatable `status` filter | Any |
| GET | `/rides/{id}` | Ride details (owner, assigned driver or admin; 404 otherwise) | Any |
| POST | `/rides/{id}/start` | Start ride | Assigned driver |
| POST | `/rides/{id}/complete` | Complete ride | Assigned driver |
| POST | `/rides/{id}/cancel` | Cancel ride (optional reason) | Rider / driver / admin |

### System
| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness + DB connectivity check (503 when the DB is unreachable) |

---

## 7. Architecture

Layered design, with business logic kept out of the routers. Dependencies point one way: `api → services → repositories → models`.

```
app/
├── core/          # config, security (JWT, hashing), domain exceptions, geo
├── db/            # async + sync engines and sessions, constraint-error helper
├── models/        # SQLAlchemy models, enums, constraints
├── schemas/       # Pydantic request/response models, shared types
├── repositories/  # data-access layer (queries only)
├── services/      # business logic: auth, drivers, rides, state machine, pricing, earnings
├── api/
│   ├── deps.py    # DB session, current user, role guards
│   ├── errors.py  # exception → HTTP mapping, error body
│   ├── params.py  # shared query parameters (date range)
│   └── v1/        # routers: health, auth, users, drivers, rides
└── main.py        # app factory, exception handlers, router registration
alembic/           # migrations
scripts/seed.py    # idempotent admin seed
deploy/            # compose.yml, API Dockerfile + entrypoint, Postgres init (test DB)
tests/
├── unit/          # state machine, pricing, security, config, error mapping
└── integration/   # API tests, concurrency, constraint fallbacks, seed, infrastructure
```

---

## 8. Error Handling

- Services raise domain exceptions that know nothing about HTTP. Each has a stable `code`, and they form a hierarchy (`AuthenticationError`, `PermissionDeniedError`, `NotFoundError`, `ConflictError` and their subclasses).
- One central handler maps them to status codes by class hierarchy, so a new conflict type is automatically a 409.
- Validation errors, framework errors (404/405), unhandled constraint violations and unexpected exceptions use the same body; 500s never leak internals.
- Every error uses a consistent body:
  ```json
  { "error": { "code": "INVALID_STATE_TRANSITION",
               "message": "Cannot complete a ride that is assigned.",
               "details": { "status": "assigned", "action": "complete" } } }
  ```

| Status | When |
|---|---|
| 401 | Missing, invalid or expired token; wrong credentials; disabled account |
| 403 | Wrong role for the endpoint or action |
| 404 | Resource not found, or a ride the caller is not part of |
| 409 | Duplicate email or plate, existing driver profile, invalid transition, no driver available, active ride already exists |
| 422 | Validation errors, with per-field `details` |
| 503 | Health check when the database is unreachable |

---

## 9. Testing

- **Real PostgreSQL**, separate test database; the schema is built by the real Alembic migrations, and a test checks the models and migrations don't drift.
- **Isolation:** each test runs in a transaction that is rolled back; each API request inside a test gets its own savepoint, mirroring production's transaction per request.
- **Auth:** register, duplicate email, login success/failure, expired, forged or malformed tokens, disabled accounts, every role-guard combination.
- **State machine:** every status × action × actor combination (unit), plus every lifecycle endpoint through the API.
- **Assignment:** nearest driver, drivers without a location, longest-idle tie-break, offline/disabled drivers skipped, no driver → 409 with no ride saved, driver freed after complete/cancel.
- **Concurrency** (real parallel requests on committed data): 8 riders/1 driver → exactly 1 ride; 5 riders/5 drivers → each driver once; one rider double-submitting → 1 ride; 4 starts + 4 cancels on one ride → exactly 1 success. Each test was verified to fail when the relevant lock is removed.
- **Constraint fallbacks:** each pre-check is disabled so the unique constraint fires, proving the violation still maps to the right 409.
- **Driver history & earnings:** totals, day/week/month breakdown, midnight boundaries, open and empty ranges, cancelled rides and other drivers excluded; also run with the DB session in a non-UTC time zone.
- **Coverage:** 99% (floor 90%, enforced by `make coverage`).

---

## 10. Deliverables

- [ ] Source code in a GitHub repository with a clean, incremental commit history (pending push)
- [x] `docker compose up` (`make run`) brings up the API and Postgres, with migrations applied and the admin seeded
- [x] Alembic migrations
- [x] Test suite runnable with a single command (`make test`)
- [x] Swagger/OpenAPI docs at `/docs`
- [x] README covering setup, environment variables, running tests, API overview, design decisions, assumptions and future improvements
- [x] `.env.example`

---

## 11. Out of Scope (Future Improvements)

- Ride request queue / pending matching when no driver is free
- Maximum pickup radius; PostGIS for driver search at scale
- Real maps/routing or dynamic pricing; platform commission
- Payments
- Real-time tracking (WebSockets)
- Refresh tokens, token revocation and rate limiting
- Ratings and reviews
- CI pipeline

---

## 12. Assumptions

1. **Roles:** rider, driver and admin, with a driver profile table linked to the user.
2. **Assignment:** happens immediately when a ride is requested. If no driver is available, the request is rejected; no pending rides or queue.
3. **One active ride** per rider and per driver.
4. **Cancellation** is only allowed before pickup (`assigned`).
5. **Fare:** a distance-based estimate (base + per-km × straight-line distance) at request time. `final_fare` is set on completion and equals the estimate, since there is no live tracking.
6. **Earnings:** the driver keeps 100% of the fare. No commission is modelled, but a commission rate could be added in config.
7. **No maximum pickup radius:** the nearest available driver is assigned however far away.
8. **Dates** in `from`/`to` filters are whole UTC days, inclusive.
9. **Drivers** go back online automatically after completing or cancelling a ride.
10. **Admin users** are seeded from `ADMIN_EMAIL` / `ADMIN_PASSWORD` by an idempotent script; they cannot self-register, and the seed never promotes an existing account.

---

## 13. Implementation Plan

1. [x] Project setup: dependencies, tooling, package layout
2. [x] Config and app skeleton with health check
3. [x] Docker and database sessions
4. [x] Models and initial migration
5. [x] Error handling foundation
6. [x] Test infrastructure
7. [x] Authentication
8. [x] Driver profile and availability
9. [x] Ride state machine
10. [x] Ride request and driver assignment
11. [x] Ride lifecycle endpoints
12. [x] Ride listing
13. [x] Driver history and earnings
14. [x] Admin seeding
15. [x] Coverage and polish
16. [x] README (push to GitHub pending)
