#!/usr/bin/env bash
set -euo pipefail
# Startup and periodic reconciliation use this same path. It is safe to repeat.
exec python -m tsa reconcile
