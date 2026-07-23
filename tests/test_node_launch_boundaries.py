#!/usr/bin/env python3
"""
Node launch-boundary tests for disabled privacy and retired server-side custody.

Run: python3 tests/test_node_launch_boundaries.py
"""
import asyncio
import os
import sys
import shutil
import tempfile

os.environ.setdefault("WEPO_NETWORK_PROFILE", "test")
os.environ.pop("WEPO_FEATURE_PRIVACY", None)
os.environ.pop("WEPO_NODE_ALLOWED_ORIGINS", None)
os.environ.pop("WEPO_NODE_API_HOST", None)

CORE = os.path.join(os.path.dirname(__file__), "..", "wepo-blockchain", "core")
sys.path.insert(0, os.path.abspath(CORE))

import httpx  # noqa: E402
from wepo_node import WepoFullNode  # noqa: E402

FAILURES = []


def check(name, condition):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}")
    if not condition:
        FAILURES.append(name)


async def main_async():
    temp_dir = tempfile.mkdtemp(prefix="wepo-node-boundaries-")
    try:
        node = WepoFullNode(
            data_dir=temp_dir,
            p2p_port=0,
            api_port=0,
            enable_mining=False,
            background_mining_enabled=False,
            difficulty_override=1,
            network_profile="test",
        )
        check("node API binds to localhost by default", node.api_host == "127.0.0.1")
        check("node CORS has no default browser origins", node.api_allowed_origins == [])

        transport = httpx.ASGITransport(app=node.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://node.invalid") as client:
            privacy_response = await client.post(
                "/api/privacy/create-proof",
                json={"transaction_data": {"amount": 1}},
            )
            wallet_response = await client.post("/api/quantum/wallet/create")
            wallet_payload = wallet_response.json()
            tx_response = await client.post(
                "/api/quantum/transaction/create",
                json={"private_key": "secret", "from_address": "a", "to_address": "b", "amount": 1},
            )
            status_response = await client.get("/api/quantum/status")
            dilithium_response = await client.get("/api/quantum/dilithium")
            cors_response = await client.options(
                "/api/quantum/dilithium",
                headers={
                    "Origin": "https://example.invalid",
                    "Access-Control-Request-Method": "GET",
                },
            )

        print("Node launch boundaries:")
        check("privacy proof endpoint is disabled by default", privacy_response.status_code == 503)
        check("server-side wallet creation is retired", wallet_response.status_code == 410)
        check("retired wallet route does not return a private key", "private_key" not in str(wallet_payload).lower())
        check("server-side transaction signing is retired", tx_response.status_code == 410)
        check("parallel quantum-chain status is retired", status_response.status_code == 410)
        check("Dilithium implementation metadata remains available", dilithium_response.status_code == 200)
        check(
            "node CORS does not allow wildcard browser credentials",
            cors_response.headers.get("access-control-allow-origin") != "*"
            and cors_response.headers.get("access-control-allow-credentials") != "true",
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    asyncio.run(main_async())
    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)} failing): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
