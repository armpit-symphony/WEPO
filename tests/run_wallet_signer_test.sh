#!/usr/bin/env bash
# Cross-runtime wallet-signer test: the JS wallet module signs a transaction and
# the Python chain verifies + accepts it. Requires frontend deps installed
# (npm install in frontend/) and dilithium_py available for Python.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

echo "== JS: derive keypair, build + sign transfer (shipped wallet module) =="
node "$HERE/wallet_signer_xcheck.mjs"

echo "== Python: verify signature + consensus acceptance =="
python3 "$HERE/wallet_signer_xcheck.py"
