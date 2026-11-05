"""Unit tests for `autobot.runtime.costs.cost_of`: no DB, no tenant context."""

import logging
from decimal import Decimal

import pytest

from autobot.runtime import costs


def test_cost_of_known_categories_sums_their_prices() -> None:
    counts: dict[str | None, int] = {"utility": 2, "marketing": 1}
    expected = costs.PRICE_EUR["utility"] * 2 + costs.PRICE_EUR["marketing"]
    assert costs.cost_of(counts) == expected.quantize(Decimal("0.01"))


def test_cost_of_unknown_category_uses_the_highest_price_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        cost = costs.cost_of({"marketing_lite": 1})
    assert cost == max(costs.PRICE_EUR.values()).quantize(Decimal("0.01"))
    assert "marketing_lite" in caplog.text


def test_cost_of_none_category_uses_the_highest_price_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        cost = costs.cost_of({None: 1})
    assert cost == max(costs.PRICE_EUR.values()).quantize(Decimal("0.01"))
    assert "None" in caplog.text


def test_cost_of_rounds_a_tie_half_up() -> None:
    # 10 * 0.0585 == 0.5850: exactly between 0.58 and 0.59.
    assert costs.cost_of({"marketing": 10}) == Decimal("0.59")
