#!/usr/bin/env bash
set -euo pipefail
read -r -p 'Import an existing key or request a new role? (import/new): ' process
if [[ "${process}" == import ]]; then
  read -r -p 'Local key name: ' name
  exec python -m tsa import-key --name "${name}"
elif [[ "${process}" == new ]]; then
  read -r -p 'Guild ID (for example 0-1): ' guild
  read -r -p 'Unique role name: ' name
  # The chain gives a new player's primary key the full protocol grant.
  exec python -m tsa request-role --name "${name}" --guild-id "${guild}" --permissions 33554431
else
  echo 'Choose import or new' >&2
  exit 1
fi
