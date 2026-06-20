#!/usr/bin/env python3
"""
Rate-limit client-identity tests.

Global API rate limiting is only meaningful if a single host cannot rotate its
identity to get a fresh bucket per request. The backend must therefore key on
the real socket peer unless explicitly told it sits behind a trusted proxy.

  * default (no proxy trust): spoofed X-Real-IP is ignored -> attacker throttled
  * WEPO_TRUST_PROXY_HEADERS=1: proxy-supplied client IP is honored

Run: python3 tests/test_rate_limit_identity.py
"""
import importlib
import os
import sys

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, os.path.abspath(BACKEND))

FAILURES = []


def check(name, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        FAILURES.append(name)


class _Peer:
    def __init__(self, host):
        self.host = host


class _Req:
    def __init__(self, x_real_ip=None, peer="203.0.113.7"):
        self.headers = {"X-Real-IP": x_real_ip} if x_real_ip else {}
        self.client = _Peer(peer)


def load_security(trust_proxy: bool):
    os.environ["WEPO_TRUST_PROXY_HEADERS"] = "1" if trust_proxy else "0"
    import security_utils
    importlib.reload(security_utils)
    return security_utils


def main():
    # Default: forwarding headers untrusted -> one real host stays one bucket.
    sec = load_security(trust_proxy=False)
    sec.rate_limit_storage.clear()
    SM = sec.SecurityManager
    blocked = sum(
        SM.is_rate_limited(SM.get_client_identifier(_Req(x_real_ip=f"10.0.0.{i}")), "global_api")
        for i in range(70)
    )
    check("default mode: spoofed X-Real-IP cannot bypass the limiter", blocked == 70 - 60)

    # Proxy trust: distinct downstream clients get distinct buckets.
    sec = load_security(trust_proxy=True)
    sec.rate_limit_storage.clear()
    SM = sec.SecurityManager
    blocked = sum(
        SM.is_rate_limited(SM.get_client_identifier(_Req(x_real_ip=f"198.51.100.{i}", peer="10.0.0.1")), "global_api")
        for i in range(70)
    )
    check("proxy mode: distinct real clients are not throttled together", blocked == 0)

    # Proxy trust: a single downstream client is still throttled at the limit.
    sec.rate_limit_storage.clear()
    blocked = sum(
        SM.is_rate_limited(SM.get_client_identifier(_Req(x_real_ip="198.51.100.42", peer="10.0.0.1")), "global_api")
        for i in range(70)
    )
    check("proxy mode: a single real client is throttled at 60/min", blocked == 70 - 60)

    os.environ.pop("WEPO_TRUST_PROXY_HEADERS", None)
    print()
    if FAILURES:
        print(f"RESULT: FAILED ({len(FAILURES)}): {FAILURES}")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
