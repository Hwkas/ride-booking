"""The ride state machine, tested exhaustively without a database."""

from datetime import UTC, datetime
from decimal import Decimal
from itertools import product

import pytest

from app.core.exceptions import InvalidStateTransitionError, PermissionDeniedError
from app.models import Ride, RideStatus
from app.services.ride_lifecycle import (
    TERMINAL_STATUSES,
    TRANSITIONS,
    RideAction,
    RideActor,
    apply_transition,
    check_transition,
)


S, A, R = RideStatus, RideAction, RideActor

# The complete specification, written out by hand so the table in the code is
# checked against an independent statement of the rules.
ALLOWED: dict[tuple[RideStatus, RideAction, RideActor], RideStatus] = {
    (S.ASSIGNED, A.START, R.DRIVER): S.IN_PROGRESS,
    (S.IN_PROGRESS, A.COMPLETE, R.DRIVER): S.COMPLETED,
    (S.ASSIGNED, A.CANCEL, R.RIDER): S.CANCELLED,
    (S.ASSIGNED, A.CANCEL, R.DRIVER): S.CANCELLED,
    (S.ASSIGNED, A.CANCEL, R.ADMIN): S.CANCELLED,
}

# Who may perform each action at all (in some status).
PERMITTED_ACTORS = {
    A.START: {R.DRIVER},
    A.COMPLETE: {R.DRIVER},
    A.CANCEL: {R.RIDER, R.DRIVER, R.ADMIN},
}

ALL_CASES = list(product(RideStatus, RideAction, RideActor))


def make_ride(status: RideStatus) -> Ride:
    return Ride(
        rider_id=1,
        driver_id=1,
        pickup_address="A",
        pickup_lat=Decimal(0),
        pickup_lng=Decimal(0),
        dropoff_address="B",
        dropoff_lat=Decimal(1),
        dropoff_lng=Decimal(1),
        distance_km=Decimal("1.00"),
        fare_estimate=Decimal("5.00"),
        status=status,
    )


@pytest.mark.parametrize(("status", "action", "actor"), ALL_CASES)
def test_every_status_action_actor_combination(status, action, actor):
    key = (status, action, actor)

    if key in ALLOWED:
        assert check_transition(status, action, actor).target is ALLOWED[key]
    elif actor not in PERMITTED_ACTORS[action]:
        with pytest.raises(PermissionDeniedError):
            check_transition(status, action, actor)
    else:
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check_transition(status, action, actor)
        assert exc_info.value.details == {
            "status": status.value,
            "action": action.value,
        }


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
def test_terminal_statuses_allow_nothing(status):
    for action, actor in product(RideAction, RideActor):
        with pytest.raises((InvalidStateTransitionError, PermissionDeniedError)):
            check_transition(status, action, actor)


def test_permission_is_checked_before_state():
    # A rider may never start a ride, so the answer is 403 even when the ride
    # is in a status where starting would be impossible anyway.
    with pytest.raises(PermissionDeniedError):
        check_transition(S.COMPLETED, A.START, R.RIDER)


def test_error_message_names_action_and_status():
    with pytest.raises(InvalidStateTransitionError, match="Cannot complete a ride"):
        check_transition(S.ASSIGNED, A.COMPLETE, R.DRIVER)


@pytest.mark.parametrize(
    ("action", "start_status", "timestamp_field", "releases_driver"),
    [
        (A.START, S.ASSIGNED, "started_at", False),
        (A.COMPLETE, S.IN_PROGRESS, "completed_at", True),
        (A.CANCEL, S.ASSIGNED, "cancelled_at", True),
    ],
)
def test_apply_sets_status_timestamp_and_reports_side_effects(
    action, start_status, timestamp_field, releases_driver
):
    ride = make_ride(start_status)
    at = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)

    transition = apply_transition(ride, action, R.DRIVER, at=at)

    assert ride.status is TRANSITIONS[action].target
    assert getattr(ride, timestamp_field) == at
    assert transition.releases_driver is releases_driver


def test_apply_leaves_ride_untouched_when_refused():
    ride = make_ride(S.ASSIGNED)

    with pytest.raises(InvalidStateTransitionError):
        apply_transition(ride, A.COMPLETE, R.DRIVER, at=datetime.now(UTC))

    assert ride.status is S.ASSIGNED
    assert ride.completed_at is None


def test_full_happy_path():
    ride = make_ride(S.ASSIGNED)
    now = datetime.now(UTC)

    apply_transition(ride, A.START, R.DRIVER, at=now)
    apply_transition(ride, A.COMPLETE, R.DRIVER, at=now)

    assert ride.status is S.COMPLETED
    assert ride.started_at == ride.completed_at == now


def test_table_invariants():
    for action, transition in TRANSITIONS.items():
        # Nothing leaves a terminal status, and nothing goes back to ASSIGNED.
        assert not transition.sources & TERMINAL_STATUSES, action
        assert transition.target is not S.ASSIGNED, action
        # Every transition records when it happened.
        assert hasattr(Ride, transition.timestamp_field), action
        # Only transitions into a terminal status free the driver.
        assert transition.releases_driver == (transition.target in TERMINAL_STATUSES), (
            action
        )
