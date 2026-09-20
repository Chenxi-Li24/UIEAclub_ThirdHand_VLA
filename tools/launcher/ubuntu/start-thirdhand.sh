#!/usr/bin/env bash
set -u

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd -P)"
cd "$ROOT" || exit 1

./thirdhand ensure --profile manual-control
status=$?
if [[ $status -eq 0 ]]; then
  printf '\nAll configured ThirdHand service ports are ready.\n'
else
  printf '\nThirdHand is only partially ready. Review the feedback above.\n'
fi
read -r -p 'Press Enter to close... '
exit "$status"
