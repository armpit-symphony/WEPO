import importlib
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / 'backend'
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def test_mainnet_redis_requirement_defaults_to_true_without_explicit_flag():
    os.environ.pop('WEPO_REQUIRE_REDIS_RATE_LIMIT', None)
    os.environ['WEPO_NETWORK_PROFILE'] = 'mainnet'
    import security_utils

    sec = importlib.reload(security_utils)
    assert sec.redis_required_for_rate_limits() is True


def test_non_mainnet_redis_requirement_defaults_to_false_without_explicit_flag():
    os.environ.pop('WEPO_REQUIRE_REDIS_RATE_LIMIT', None)
    os.environ['WEPO_NETWORK_PROFILE'] = 'test'
    import security_utils

    sec = importlib.reload(security_utils)
    assert sec.redis_required_for_rate_limits() is False
