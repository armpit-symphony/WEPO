#!/usr/bin/env bash
# JS -> Python interop for the messaging spend-key ownership binding. Requires
# frontend deps installed (npm install in frontend/) so @noble resolves in node.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
echo "== owner-binding interop (JS wallet produces -> Python relay verifies) =="
node "$HERE/owner_binding_emit.mjs" | python3 "$HERE/test_owner_binding_interop.py"
