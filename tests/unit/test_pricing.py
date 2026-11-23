from decimal import Decimal

import pytest

from app.core.geo import haversine_km
from app.services.pricing import estimate_fare, trip_distance_km


@pytest.mark.parametrize(
    ("a", "b", "expected_km"),
    [
        ((51.5074, -0.1278), (48.8566, 2.3522), 343.5),  # London -> Paris
        ((40.7128, -74.0060), (34.0522, -118.2437), 3935.7),  # NYC -> LA
        ((0, 0), (0, 180), 20015.1),  # half the equator
        ((12.9716, 77.5946), (12.9716, 77.5946), 0.0),
    ],
)
def test_haversine_known_distances(a, b, expected_km):
    assert haversine_km(*a, *b) == pytest.approx(expected_km, abs=0.5)


def test_haversine_is_symmetric():
    a, b = (12.9756, 77.6059), (12.9784, 77.6408)

    assert haversine_km(*a, *b) == pytest.approx(haversine_km(*b, *a))


def test_trip_distance_is_rounded_decimal():
    distance = trip_distance_km(
        (Decimal("12.975600"), Decimal("77.605900")),
        (Decimal("12.978400"), Decimal("77.640800")),
    )

    assert distance == Decimal("3.79")
    assert distance.as_tuple().exponent == -2


@pytest.mark.parametrize(
    ("distance", "expected"),
    [
        (Decimal("0.00"), Decimal("2.50")),  # base fare only
        (Decimal("3.79"), Decimal("7.05")),  # 2.50 + 1.20 * 3.79 = 7.048
        (Decimal("10.00"), Decimal("14.50")),
        (Decimal("0.01"), Decimal("2.51")),  # 2.512 rounds down
        (Decimal("0.03"), Decimal("2.54")),  # 2.536 rounds up
    ],
)
def test_fare_is_base_plus_per_km_rounded_to_cents(distance, expected):
    assert estimate_fare(distance) == expected
