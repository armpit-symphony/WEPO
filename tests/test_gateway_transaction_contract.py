"""Gateway contract tests for canonical addresses and exact WEPO decimals."""

import importlib
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

@pytest.fixture(autouse=True)
def restore_network_profile():
    previous = os.environ.get("WEPO_NETWORK_PROFILE")
    yield
    if previous is None:
        os.environ.pop("WEPO_NETWORK_PROFILE", None)
    else:
        os.environ["WEPO_NETWORK_PROFILE"] = previous



def load_security(profile: str):
    os.environ["WEPO_NETWORK_PROFILE"] = profile
    import security_utils

    return importlib.reload(security_utils).SecurityManager


def test_address_validation_is_profile_aware_and_fail_closed():
    canonical = f"wepo1q{'a' * 39}"
    legacy = f"wepo1{'b' * 32}"

    mainnet = load_security("mainnet")
    assert mainnet.validate_wepo_address(canonical)
    assert not mainnet.validate_wepo_address(canonical.upper())
    assert not mainnet.validate_wepo_address(f"wepo1q{'a' * 38}")
    assert not mainnet.validate_wepo_address(f"wepo1q{'a' * 40}")
    assert not mainnet.validate_wepo_address(f"javascript:{canonical}")
    assert not mainnet.validate_wepo_address(f"<script></script>{canonical}")
    assert not mainnet.validate_wepo_address(legacy)

    testnet = load_security("test")
    assert testnet.validate_wepo_address(canonical)
    assert testnet.validate_wepo_address(legacy)

    unknown = load_security("unexpected-profile")
    assert unknown.validate_wepo_address(canonical)
    assert not unknown.validate_wepo_address(legacy)


def test_amount_validation_preserves_exact_plain_decimals():
    validate = load_security("mainnet").validate_transaction_amount

    assert validate("0.00000001")["sanitized_amount"] == "0.00000001"
    assert validate("1.23000000")["sanitized_amount"] == "1.23"
    assert validate("1000000")["sanitized_amount"] == "1000000"
    assert validate(Decimal("10.50000000"))["sanitized_amount"] == "10.5"
    assert validate(10)["sanitized_amount"] == "10"


def test_amount_validation_rejects_ambiguous_or_out_of_policy_values():
    validate = load_security("mainnet").validate_transaction_amount

    for invalid in (
        "0",
        "-1",
        "+1",
        "01",
        "1000000.00000001",
        "1000001",
        "0.000000001",
        "1e-8",
        "NaN",
        "Infinity",
        True,
        0.1,
        None,
    ):
        result = validate(invalid)
        assert not result["is_valid"], invalid
        assert result["sanitized_amount"] == ""


def test_build_unsigned_gateway_forwards_only_canonical_decimal_strings(monkeypatch):
    monkeypatch.setenv("MONGO_URL", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("DB_NAME", "wepo_contract_test")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1")
    monkeypatch.setenv("WEPO_REQUIRE_REDIS_RATE_LIMIT", "0")
    monkeypatch.setenv("WEPO_NETWORK_PROFILE", "mainnet")

    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    monkeypatch.setattr(
        server.SecurityManager,
        "is_rate_limited",
        staticmethod(lambda _client, _operation: False),
    )

    captured = {}

    class NodeResponse:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {"unsigned_tx": {}, "sighash": "00" * 32}

    def node_post(url, json, timeout):
        captured.update({"url": url, "json": json, "timeout": timeout})
        return NodeResponse()

    monkeypatch.setattr(server.requests, "post", node_post)

    class Peer:
        host = "127.0.0.1"

    class Request:
        client = Peer()
        headers = {}

    sender = f"wepo1q{'a' * 39}"
    recipient = f"wepo1q{'b' * 39}"
    result = asyncio.run(
        server.build_unsigned_transaction(
            Request(),
            {
                "from_address": sender,
                "to_address": recipient,
                "amount": "1.23000000",
                "fee": "0.00010000",
            },
        )
    )

    assert result["sighash"] == "00" * 32
    assert captured["json"] == {
        "from_address": sender,
        "to_address": recipient,
        "amount": "1.23",
        "fee": "0.0001",
    }
    assert captured["timeout"] == 5

    captured.clear()
    quoted_result = asyncio.run(
        server.build_unsigned_transaction(
            Request(),
            {
                "from_address": sender,
                "to_address": recipient,
                "amount": "1.23000000",
            },
        )
    )
    assert quoted_result["sighash"] == "00" * 32
    assert captured["json"] == {
        "from_address": sender,
        "to_address": recipient,
        "amount": "1.23",
    }

    with pytest.raises(HTTPException) as rejected:
        asyncio.run(
            server.build_unsigned_transaction(
                Request(),
                {
                    "from_address": sender,
                    "to_address": recipient,
                    "amount": 0.1,
                    "fee": "0.0001",
                },
            )
        )
    assert rejected.value.status_code == 400


def test_gateway_lifespan_runs_cleanup_after_success_and_startup_failure(monkeypatch):
    monkeypatch.setenv("MONGO_URL", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("DB_NAME", "wepo_lifespan_test")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1")
    monkeypatch.setenv("WEPO_REQUIRE_REDIS_RATE_LIMIT", "0")
    monkeypatch.setenv("WEPO_NETWORK_PROFILE", "test")

    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    real_client = server.client
    calls = []

    async def successful_startup():
        calls.append("startup")

    async def cleanup():
        calls.append("shutdown")

    async def exercise_success():
        async with server.app_lifespan(server.app):
            calls.append("running")

    try:
        monkeypatch.setattr(server, "startup_event", successful_startup)
        monkeypatch.setattr(server, "shutdown_db_client", cleanup)
        asyncio.run(exercise_success())
        assert calls == ["startup", "running", "shutdown"]

        calls.clear()

        async def failing_startup():
            calls.append("startup")
            raise RuntimeError("injected startup failure")

        monkeypatch.setattr(server, "startup_event", failing_startup)
        with pytest.raises(RuntimeError, match="injected startup failure"):
            asyncio.run(exercise_success())
        assert calls == ["startup", "shutdown"]
    finally:
        real_client.close()
