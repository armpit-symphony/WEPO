#!/usr/bin/env python3
"""Redis runtime failure must deny requests when production limiting is required.

Run: python3 tests/test_redis_rate_limit_fail_closed.py
"""

import importlib
import os
import sys

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, os.path.abspath(BACKEND))


class BrokenPipeline:
    def incr(self, key):
        return self

    def expire(self, key, seconds):
        return self

    def execute(self):
        raise ConnectionError("simulated Redis outage after startup")


class BrokenRedis:
    def pipeline(self):
        return BrokenPipeline()


def main():
    os.environ["WEPO_REQUIRE_REDIS_RATE_LIMIT"] = "1"
    try:
        import security_utils

        sec = importlib.reload(security_utils)
        sec.redis_client = BrokenRedis()
        blocked = sec.SecurityManager.is_rate_limited("client", "global_api")
    finally:
        os.environ.pop("WEPO_REQUIRE_REDIS_RATE_LIMIT", None)

    print("Redis runtime fail-closed boundary:")
    print(f"  [{'PASS' if blocked else 'FAIL'}] runtime Redis outage denies the request")
    if not blocked:
        print("RESULT: FAILED")
        return 1
    print("RESULT: ALL CHECKS PASSED")
    return 0


def test_regression_suite():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
