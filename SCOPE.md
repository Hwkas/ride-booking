# Scope: Ride Booking & Driver Assignment API

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
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2.x (async for the API, sync for scripts; `psycopg` 3 driver) |
| Migrations | Alembic |
| Auth | JWT (PyJWT) + bcrypt password hashing |
| Testing | pytest, pytest-asyncio, httpx `AsyncClient`, against a real Postgres test DB |
| Tooling | uv, ruff, Docker + Docker Compose |

---

## 3. Domain Model

### `users`
| Column | Type | Notes |
|---|---|---|
| id | UUID / int | PK |
| email | varchar | unique, indexed |
| hashed_password | varchar | |
| full_name | varchar | |
| role | enum | `rider`, `driver`, `admin` |
| is_active | bool | default true |
| created_at / updated_at | timestamptz | |

### `drivers`
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| user_id | FK → users | unique (one profile per user) |
| vehicle_model | varchar | |
| license_plate | varchar | unique |
| is_available | bool | indexed |
| current_lat / current_lng | numeric | optional, used for nearest-driver assignment |
| created_at / updated_at | timestamptz | |

### `rides`
| Column | Type | Notes |
|---|---|---|
| id | PK | |
| rider_id | FK → users | indexed |
| driver_id | FK → drivers | NOT NULL, indexed (every ride has a driver) |
| pickup_address / dropoff_address | varchar | |
| pickup_lat / pickup_lng / dropoff_lat / dropoff_lng | numeric | CHECK value ranges |
| status | enum | indexed |
| fare_estimate | numeric(10,2) | set at request time (distance-based) |
| final_fare | numeric(10,2) | set on completion; source of driver earnings |
| requested_at (= assigned_at), started_at, completed_at, cancelled_at | timestamptz | lifecycle audit |
| cancellation_reason | varchar | nullable |

**Constraints:**
- Enum types for role and status.
- Composite index on `(driver_id, status, completed_at)` for driver history and earnings queries.
- CHECK constraints on coordinates.
- A partial unique index so a driver can have at most one active ride (`ASSIGNED` / `IN_PROGRESS`).
- A partial unique index so a rider can have at most one active ride (a second request returns 409).

---

## 4. Ride Lifecycle (State Machine)

```
(request) ──► ASSIGNED ──► IN_PROGRESS ──► COMPLETED
                 │
                 └──────► CANCELLED
```

| Transition | Allowed actor |
|---|---|
| (request) → ASSIGNED | System, at creation; only if a driver is available |
| ASSIGNED → IN_PROGRESS | Assigned driver |
| IN_PROGRESS → COMPLETED | Assigned driver |
| ASSIGNED → CANCELLED | Rider (owner), assigned driver, admin |

There is no `REQUESTED` or pending status. A ride only exists once a driver has been assigned to it.

**Rules:**
- An invalid transition returns **409 Conflict**.
- Transitions are defined in a single table-driven state machine, so they can be unit-tested in isolation.
- Each transition sets its corresponding timestamp.

---

## 5. Driver Assignment

- **Strategy:** select the nearest available driver (haversine distance) when coordinates exist; otherwise the longest-idle available driver.
- **Concurrency safety:** `SELECT ... FOR UPDATE SKIP LOCKED` inside a transaction ensures two simultaneous ride requests never receive the same driver.
- **Availability:** the driver becomes unavailable on assignment and available again on completion or cancellation.
- **Flow on `POST /rides`:** in one transaction, lock an available driver, create the ride as `ASSIGNED`, and mark the driver unavailable.
- **No driver available:** nothing is persisted. The request fails with **409 `NO_DRIVER_AVAILABLE`**, and the rider simply tries again later.
- **No queue:** there are no pending requests, no background matching and no manual assign endpoint.

---

## 6. API Endpoints (`/api/v1`)

### Auth & Users
| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/auth/register` | Register rider or driver | Public |
| POST | `/auth/login` | Returns JWT access token | Public |
| GET | `/users/me` | Current user profile | Any |

### Drivers
| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/drivers/profile` | Create driver profile (vehicle info) | Driver |
| GET | `/drivers/me` | Own driver profile | Driver |
| PATCH | `/drivers/me/availability` | Go online/offline, update location | Driver |
| GET | `/drivers/me/rides` | Full ride history; paginated; filter by status and date range | Driver |
| GET | `/drivers/me/earnings` | Earnings summary for a date range (see below) | Driver |
| GET | `/drivers` | List drivers (filter by availability) | Admin |

**Earnings response** (`?from=2026-11-01&to=2026-11-30&group_by=day|week|month`):
```json
{
  "from": "2026-11-01",
  "to": "2026-11-30",
  "total_earnings": "1240.50",
  "completed_rides": 42,
  "average_fare": "29.54",
  "breakdown": [
    { "period": "2026-11-01", "earnings": "85.00", "rides": 3 }
  ]
}
```
- Earnings are the sum of `final_fare` over the driver's `COMPLETED` rides, aggregated in SQL (`SUM`, `COUNT`, `date_trunc`), not in Python.
- Monetary values are `Decimal`, serialized as strings so no precision is lost.
- `from` and `to` are optional; the default is all time, with no breakdown.

### Rides
| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/rides` | Request a ride; assigns an available driver or returns 409 `NO_DRIVER_AVAILABLE` | Rider |
| GET | `/rides` | List rides scoped to caller; paginated; filter by status | Any |
| GET | `/rides/{id}` | Ride details (owner, assigned driver, or admin) | Any |
| POST | `/rides/{id}/start` | Start ride | Assigned driver |
| POST | `/rides/{id}/complete` | Complete ride | Assigned driver |
| POST | `/rides/{id}/cancel` | Cancel ride (optional reason) | Rider / driver / admin |

### System
| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness + DB connectivity check |

---

## 7. Architecture

Layered design, with business logic kept out of the routers:

```
app/
├── core/          # config, security (JWT, hashing), exceptions, logging
├── db/            # engine, session, declarative base
├── models/        # SQLAlchemy ORM models
├── schemas/       # Pydantic request/response models
├── repositories/  # data-access layer (queries only)
├── services/      # business logic: auth, rides, assignment, state machine
├── api/
│   ├── deps.py    # DB session, current user, role guards
│   └── v1/        # routers: auth, users, drivers, rides
└── main.py        # app factory, exception handlers, router registration
alembic/
tests/
├── unit/          # state machine, security, assignment logic
└── integration/   # API endpoint tests against Postgres
docker-compose.yml
Dockerfile
```

---

## 8. Error Handling

- Domain exceptions (`NotFoundError`, `InvalidStateTransitionError`, `NoDriverAvailableError`, `PermissionDeniedError`, `ConflictError`) are raised in the service layer.
- These exceptions are mapped to HTTP responses in one central handler.
- Every error uses a consistent body:
  ```json
  { "error": { "code": "INVALID_STATE_TRANSITION", "message": "Cannot complete a ride in status ASSIGNED" } }
  ```

| Status | When |
|---|---|
| 400 / 422 | Validation errors |
| 401 | Missing or invalid token |
| 403 | Wrong role, or not the resource owner |
| 404 | Resource not found |
| 409 | Duplicate email or plate, invalid transition, no driver available, rider already has an active ride |

---

## 9. Testing Plan

- **Auth:** register, duplicate email, login success/failure, expired or invalid token.
- **Authorization:** role guards; a rider cannot access another rider's ride.
- **State machine:** every valid transition succeeds and every invalid one returns 409 (parametrized).
- **Assignment:** nearest driver chosen; no driver available returns 409 and creates no ride row; driver freed after complete/cancel.
- **Concurrency:** parallel ride requests with a single available driver result in exactly one assignment.
- **Driver history & earnings:** a driver sees only their own rides; filters and pagination work; totals and the day/week/month breakdown are correct; cancelled rides are excluded from earnings; an empty range returns zero.
- **Infrastructure:** isolated test DB, with a transaction rolled back per test; fixtures and factories for users, drivers and rides.
- **Coverage target:** ≥ 85%.

---

## 10. Deliverables

- [ ] Source code in a public GitHub repository with a clean, incremental commit history
- [ ] `docker compose up` brings up the API and Postgres, with migrations applied
- [ ] Alembic migrations
- [ ] Test suite runnable with a single command
- [ ] Swagger/OpenAPI docs at `/docs`
- [ ] README covering setup, environment variables, running tests, API overview, design decisions, assumptions and future improvements
- [ ] `.env.example`

---

## 11. Out of Scope (Future Improvements)

- Real maps/routing or dynamic pricing
- Payments
- Real-time tracking (WebSockets)
- Refresh tokens and token revocation
- Ratings and reviews
- Ride request queue / pending matching when no driver is free
- Rate limiting

---

## 12. Assumptions / Open Questions

1. **Roles:** rider, driver and admin, with a driver profile table linked to the user.
2. **Assignment:** happens immediately when a ride is requested. If no driver is available, the request is rejected; no pending rides or queue.
3. **Fare:** a distance-based estimate (base + per-km) at request time. `final_fare` is set on completion and equals the estimate, since there is no live tracking.
4. **Earnings:** the driver keeps 100% of the fare. No commission is modelled, but a commission rate could be added in config.
5. **SQLAlchemy:** async mode.
6. **Admin users:** seeded via a script or environment variables; they cannot self-register.

---

## 13. Implementation Plan

1. Project skeleton, config, Docker Compose, DB session, health check
2. Models + Alembic initial migration
3. Auth: register, login, JWT, role dependencies
4. Driver profile + availability
5. Ride creation + state machine + transition endpoints
6. Driver assignment with row locking (reject when no driver is free)
7. Driver ride history + earnings
8. Central error handling
9. Tests (unit + integration + concurrency)
10. README, final cleanup, push to GitHub
