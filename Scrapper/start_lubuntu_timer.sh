#!/usr/bin/env bash
set -euo pipefail

if (( $# )); then
    if [[ $# == 1 && ( $1 == --help || $1 == -h ) ]]; then
        echo 'Usage: start_lubuntu_timer.sh'
        echo 'Import the current graphical login environment and start the user timer.'
        exit 0
    fi
    echo 'Usage: start_lubuntu_timer.sh' >&2
    exit 2
fi

script_path=$(readlink -f -- "${BASH_SOURCE[0]}")
script_directory=$(dirname -- "$script_path")
if "$script_directory/run_lubuntu_minute.sh" --check-session; then
    :
else
    check_status=$?
    # No desktop is an expected skip for an installer run from a terminal/SSH.
    [[ $check_status != 1 ]] || exit 0
    exit "$check_status"
fi

systemctl --user daemon-reload
desktop_variables=(DISPLAY XAUTHORITY WAYLAND_DISPLAY DBUS_SESSION_BUS_ADDRESS)
# Remove values from the previous login before importing this desktop's values.
systemctl --user unset-environment "${desktop_variables[@]}"
available_variables=()
for variable in "${desktop_variables[@]}"; do
    if [[ -n ${!variable:-} ]]; then
        available_variables+=("$variable")
    fi
done
systemctl --user import-environment "${available_variables[@]}"
systemctl --user start agentic-scraper-minute.timer
echo 'Started agentic-scraper-minute.timer for the current graphical login.'
