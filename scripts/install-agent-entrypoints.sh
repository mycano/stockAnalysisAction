#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$#" -eq 0 ]]; then
  set -- all
fi
exec python3 "$ROOT/scripts/install_agent_entrypoints.py" "$@"
