"""Shared pytest path setup for tests that are also executable scripts."""

import os
from pathlib import Path
import sys


# Pytest must never inherit the production-default profile or depend on module
# collection order. Tests that exercise mainnet boundaries request it explicitly.
os.environ.setdefault("WEPO_NETWORK_PROFILE", "test")

TESTS_DIRECTORY = Path(__file__).resolve().parent
tests_path = str(TESTS_DIRECTORY)
if tests_path not in sys.path:
    # Script-mode tests already receive this path from Python; pytest does not
    # guarantee it for an individually selected file.
    sys.path.insert(0, tests_path)
