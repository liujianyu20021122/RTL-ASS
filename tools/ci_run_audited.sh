#!/usr/bin/env bash
set -euo pipefail

if (( $# < 3 )); then
    echo "usage: ci_run_audited.sh LABEL LOG_PATH COMMAND [ARG ...]" >&2
    exit 64
fi

label=$1
log_path=$2
shift 2

mkdir -p -- "$(dirname -- "$log_path")"
: >"$log_path"

# Prevent command output from being interpreted as workflow commands. Only this
# wrapper emits the final, bounded annotation after command execution finishes.
stop_marker="rtl_ass_ci_${RANDOM}_${RANDOM}_$$"
printf '::stop-commands::%s\n' "$stop_marker"

set +e
"$@" 2>&1 | tee "$log_path"
pipeline_status=("${PIPESTATUS[@]}")
set -e

printf '::%s::\n' "$stop_marker"

command_status=${pipeline_status[0]}
tee_status=${pipeline_status[1]}
if (( command_status == 0 && tee_status == 0 )); then
    exit 0
fi
if (( command_status == 0 )); then
    command_status=$tee_status
fi

diagnostic=$(tail -n 40 -- "$log_path" | tail -c 12000 | tr -d '\000')
diagnostic=${diagnostic//'%'/'%25'}
diagnostic=${diagnostic//$'\r'/'%0D'}
diagnostic=${diagnostic//$'\n'/'%0A'}
annotation_title=${label//'%'/'%25'}
annotation_title=${annotation_title//$'\r'/'%0D'}
annotation_title=${annotation_title//$'\n'/'%0A'}
annotation_title=${annotation_title//':'/'%3A'}
annotation_title=${annotation_title//','/'%2C'}
printf '::error title=%s::exit=%d%%0A%s\n' "$annotation_title" "$command_status" "$diagnostic"
exit "$command_status"
