"""Exact WEPO API amount parsing must never round currency values."""

from __future__ import annotations

from decimal import Decimal
import os
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "wepo-blockchain" / "core"
sys.path.insert(0, str(CORE))
os.environ.setdefault("WEPO_NETWORK_PROFILE", "test")

from blockchain import COIN, SUPPLY_CAP  # noqa: E402
from wepo_node import parse_wepo_amount_to_atomic  # noqa: E402


def test_exact_decimal_amount_parser():
    parse = parse_wepo_amount_to_atomic

    assert parse("0.00000001", "amount") == 1
    assert parse("1.23456789", "amount") == 123_456_789
    assert parse(1, "amount") == COIN
    assert parse(0.0001, "fee") == 10_000
    assert parse(Decimal("2.5"), "amount") == 250_000_000
    assert parse("1e-8", "amount") == 1
    assert parse("0", "amount", allow_zero=True) == 0

    invalid_values = [
        True,
        False,
        "",
        " ",
        "not-money",
        "NaN",
        "Infinity",
        float("nan"),
        float("inf"),
        "-0.00000001",
        "0.000000001",
        object(),
    ]
    for value in invalid_values:
        with pytest.raises(ValueError):
            parse(value, "amount")

    with pytest.raises(ValueError):
        parse("0", "amount")
    with pytest.raises(ValueError):
        parse(str(Decimal(SUPPLY_CAP + 1) / COIN), "amount")
