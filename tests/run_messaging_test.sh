#!/usr/bin/env bash
# Post-quantum E2E messaging test (client crypto). Requires frontend deps
# installed (npm install in frontend/) so @noble resolves.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
echo "== PQ E2E messaging (ML-KEM-768 + AES-256-GCM + ML-DSA-44) =="
node "$HERE/wepo_messaging_test.mjs"
