"""Helpers for interpreting database errors."""

from sqlalchemy.exc import IntegrityError


def violated_constraint(exc: IntegrityError) -> str | None:
    """Name of the constraint/index an IntegrityError violated, if known.

    Relies on the deterministic names from the models' naming convention, so
    services can map specific violations to specific domain errors.
    """
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)
