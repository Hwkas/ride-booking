"""Ride state machine: pure rules, no I/O.

A ride is created already ``ASSIGNED`` (assignment happens at request time), so
the lifecycle only has to handle what comes after::

    ASSIGNED ──start──► IN_PROGRESS ──complete──► COMPLETED
        │
        └──cancel──► CANCELLED

Every rule lives in the ``TRANSITIONS`` table below; the service layer only
decides *who* the caller is relative to the ride and persists the result.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.core.exceptions import InvalidStateTransitionError, PermissionDeniedError
from app.models import Ride, RideStatus


class RideAction(StrEnum):
    """Things that can be done to an existing ride."""

    START = "start"
    COMPLETE = "complete"
    CANCEL = "cancel"


class RideActor(StrEnum):
    """The caller's relationship to a specific ride."""

    RIDER = "rider"  # the rider who requested this ride
    DRIVER = "driver"  # the driver assigned to this ride
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class Transition:
    """One edge of the state machine and its side effects."""

    sources: frozenset[RideStatus]
    target: RideStatus
    actors: frozenset[RideActor]
    timestamp_field: str
    releases_driver: bool


TRANSITIONS: dict[RideAction, Transition] = {
    RideAction.START: Transition(
        sources=frozenset({RideStatus.ASSIGNED}),
        target=RideStatus.IN_PROGRESS,
        actors=frozenset({RideActor.DRIVER}),
        timestamp_field="started_at",
        releases_driver=False,
    ),
    RideAction.COMPLETE: Transition(
        sources=frozenset({RideStatus.IN_PROGRESS}),
        target=RideStatus.COMPLETED,
        actors=frozenset({RideActor.DRIVER}),
        timestamp_field="completed_at",
        releases_driver=True,
    ),
    RideAction.CANCEL: Transition(
        sources=frozenset({RideStatus.ASSIGNED}),
        target=RideStatus.CANCELLED,
        actors=frozenset({RideActor.RIDER, RideActor.DRIVER, RideActor.ADMIN}),
        timestamp_field="cancelled_at",
        releases_driver=True,
    ),
}

TERMINAL_STATUSES = frozenset({RideStatus.COMPLETED, RideStatus.CANCELLED})


def check_transition(
    status: RideStatus, action: RideAction, actor: RideActor
) -> Transition:
    """Return the transition for ``action`` or raise why it is not allowed.

    Permission is checked before state: an actor who may never perform the
    action gets 403 whatever the ride's status; an allowed actor acting at the
    wrong time gets 409.
    """
    transition = TRANSITIONS[action]
    if actor not in transition.actors:
        raise PermissionDeniedError(f"You are not allowed to {action.value} this ride.")
    if status not in transition.sources:
        raise InvalidStateTransitionError(
            f"Cannot {action.value} a ride that is {status.value}.",
            details={"status": status.value, "action": action.value},
        )
    return transition


def apply_transition(
    ride: Ride, action: RideAction, actor: RideActor, *, at: datetime
) -> Transition:
    """Validate and apply ``action`` to ``ride`` in memory (status + timestamp).

    Persistence and side effects such as freeing the driver or setting the
    final fare are the caller's job; the returned ``Transition`` says which
    apply.
    """
    transition = check_transition(ride.status, action, actor)
    ride.status = transition.target
    setattr(ride, transition.timestamp_field, at)
    return transition
