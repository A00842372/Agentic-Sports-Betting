#!/usr/bin/env bash
set -euo pipefail

display_server() {
    if [[ $1 =~ ^(.*:[0-9]+)\.[0-9]+$ ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
    else
        printf '%s\n' "$1"
    fi
}

check_session() {
    if [[ -z ${DISPLAY:-} ]]; then
        echo 'Skipping scrape: DISPLAY is not set.'
        return 1
    fi
    local dependency
    for dependency in loginctl timeout; do
        if ! command -v "$dependency" >/dev/null 2>&1; then
            echo "Missing required command: $dependency" >&2
            return 255
        fi
    done

    local current_uid sessions session_id session_uid remainder properties
    local owner active remote session_type session_display key value
    current_uid=$(id -u)
    if ! sessions=$(timeout 5s loginctl list-sessions --no-legend --no-pager 2>/dev/null); then
        echo 'Skipping scrape: logind session information is unavailable.'
        return 1
    fi
    while read -r session_id session_uid remainder; do
        [[ -n $session_id && $session_uid == "$current_uid" ]] || continue
        if ! properties=$(timeout 5s loginctl show-session "$session_id" --no-pager \
            --property=User --property=Active --property=Remote --property=Type \
            --property=Display 2>/dev/null); then
            continue
        fi
        owner= active= remote= session_type= session_display=
        while IFS='=' read -r key value; do
            case "$key" in
                User) owner=$value ;;
                Active) active=$value ;;
                Remote) remote=$value ;;
                Type) session_type=$value ;;
                Display) session_display=$value ;;
            esac
        done <<< "$properties"
        [[ $owner == "$current_uid" && $active == yes && $remote == no ]] || continue
        [[ $session_type == x11 || $session_type == wayland ]] || continue
        if [[ $session_type == x11 && -n $session_display ]] && \
            [[ $(display_server "$session_display") != "$(display_server "$DISPLAY")" ]]; then
            continue
        fi
        if ! command -v xdpyinfo >/dev/null 2>&1; then
            echo 'Missing xdpyinfo: install the x11-utils package.' >&2
            return 255
        fi
        if timeout 5s xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
            return 0
        fi
        echo 'Skipping scrape: the desktop display is not accessible.'
        return 1
    done <<< "$sessions"
    echo 'Skipping scrape: no active local graphical session for this user.'
    return 1
}

case "${1:-}" in
    --help|-h)
        echo 'Usage: run_lubuntu_minute.sh [--check-session]'
        echo 'Runs the existing due-work CLI once using Scrapper/.venv/bin/python.'
        echo 'Session check: 0=allowed, 1=skip, 255=missing required commands.'
        exit 0
        ;;
    ''|--check-session) ;;
    *) echo 'Usage: run_lubuntu_minute.sh [--check-session]' >&2; exit 2 ;;
esac
if (( $# > 1 )); then
    echo 'Expected at most one argument.' >&2
    exit 2
fi
if check_session; then
    [[ ${1:-} != --check-session ]] || exit 0
else
    exit "$?"
fi

# Resolve the installed user-owned symlink back to the repository.
script_path=$(readlink -f -- "${BASH_SOURCE[0]}")
script_directory=$(dirname -- "$script_path")
cd -- "$script_directory"
if [[ ! -x .venv/bin/python ]]; then
    echo 'Missing Linux virtual environment: Scrapper/.venv/bin/python' >&2
    exit 1
fi
exec .venv/bin/python -u generate_instance.py
