#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "ERROR: speech command is required" >&2
  exit 64
fi

# The delivered Language service was launched from the user's interactive
# login shell. Recreate that environment without copying credentials into the
# repository or the browser bundle.
exec /bin/bash -lic '
  if [[ -z ${ANTHROPIC_API_KEY:-} && -z ${ANTHROPIC_AUTH_TOKEN:-} ]]; then
    echo "ERROR: Anthropic credentials are unavailable in the login environment" >&2
    exit 78
  fi
  exec "$@"
' thirdhand-speech "$@"
