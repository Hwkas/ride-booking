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
| ORM | SQLAlchemy 2.0 (async, `asyncpg`) |
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
| driver_id | FK → drivers | nullable, indexed |
| pickup_address / dropoff_address | varchar | |
| pickup_lat / pickup_lng / dropoff_lat / dropoff_lng | numeric | CHECK value ranges |
| status | enum | indexed |
| fare_estimate | numeric(10,2) | optional |
| requested_at, assigned_at, started_at, completed_at, cancelled_at | timestamptz | lifecycle audit |
| cancellation_reason | varchar | nullable |

**Constraints:**
- Enum types for role and status.
- CHECK constraints on coordinates.
- A partial unique index so a driver can have at most one active ride (`ASSIGNED` / `IN_PROGRESS`).

---

## 4. Ride Lifecycle (State Machine)

```
REQUESTED ──► ASSIGNED ──► IN_PROGRESS ──► COMPLETED
    │             │
    └─────────────┴──────► CANCELLED
```

| Transition | Allowed actor |
|---|---|
| REQUESTED → ASSIGNED | System (auto) / admin |
| ASSIGNED → IN_PROGRESS | Assigned driver |
| IN_PROGRESS → COMPLETED | Assigned driver |
| REQUESTED / ASSIGNED → CANCELLED | Rider (owner), assigned driver, admin |

**Rules:**
- An invalid transition returns **409 Conflict**.
- Transitions are defined in a single table-driven state machine, so they can be unit-tested in isolation.
- Each transition sets its corresponding timestamp.

---

## 5. Driver Assignment

- **Strategy:** select the nearest available driver (haversine distance) when coordinates exist; otherwise the longest-idle available driver.
- **Concurrency safety:** `SELECT ... FOR UPDATE SKIP LOCKED` inside a transaction ensures two simultaneous ride requests never receive the same driver.
- **Availability:** the driver becomes unavailable on assignment and available again on completion or cancellation.
- **No driver available:** the ride remains `REQUESTED` and the response indicates this. A manual or admin `/assign` endpoint can retry later.

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
| GET | `/drivers` | List drivers (filter by availability) | Admin |

### Rides
| Method | Path | Description | Auth |
|---|---|---|---|
| POST | `/rides` | Request a ride (attempts auto-assign) | Rider |
| GET | `/rides` | List rides scoped to caller; paginated; filter by status | Any |
| GET | `/rides/{id}` | Ride details (owner, assigned driver, or admin) | Any |
| POST | `/rides/{id}/assign` | Manually trigger or retry assignment | Admin |
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
  { "error": { "code": "INVALID_STATE_TRANSITION", "message": "Cannot start a ride in status REQUESTED" } }
  ```

| Status | When |
|---|---|
| 400 / 422 | Validation errors |
| 401 | Missing or invalid token |
| 403 | Wrong role, or not the resource owner |
| 404 | Resource not found |
| 409 | Duplicate email or plate, invalid transition, driver already busy |

---

## 9. Testing Plan

- **Auth:** register, duplicate email, login success/failure, expired or invalid token.
- **Authorization:** role guards; a rider cannot access another rider's ride.
- **State machine:** every valid transition succeeds and every invalid one returns 409 (parametrized).
- **Assignment:** nearest driver chosen, no-driver case, driver freed after complete/cancel.
- **Concurrency:** parallel ride requests with a single available driver result in exactly one assignment.
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
- Background job queue for assignment retries
- Rate limiting

---

## 12. Assumptions / Open Questions

1. **Roles:** rider, driver and admin, with a driver profile table linked to the user.
2. **Assignment:** automatic on ride creation, with a manual/admin endpoint for retries.
3. **Fare:** a simple distance-based estimate (base + per-km).
4. **SQLAlchemy:** async mode.
5. **Admin users:** seeded via a script or environment variables; they cannot self-register.

---

## 13. Implementation Plan

1. Project skeleton, config, Docker Compose, DB session, health check
2. Models + Alembic initial migration
3. Auth: register, login, JWT, role dependencies
4. Driver profile + availability
5. Ride creation + state machine + transition endpoints
6. Driver assignment with row locking
7. Central error handling
8. Tests (unit + integration + concurrency)
9. README, final cleanup, push to GitHub
