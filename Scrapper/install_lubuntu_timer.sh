#!/usr/bin/env bash
set -euo pipefail

if (( $# )); then
    if [[ $# == 1 && ( $1 == --help || $1 == -h ) ]]; then
        echo 'Usage: install_lubuntu_timer.sh'
        echo 'Run as the desktop user with a Linux Scrapper/.venv and x11-utils installed.'
        echo 'Installs user units, user-owned launcher links, and graphical XDG autostart.'
        exit 0
    fi
    echo 'Usage: install_lubuntu_timer.sh' >&2
    exit 2
fi
if (( EUID == 0 )); then
    echo 'Run this installer as the desktop user, without sudo.' >&2
    exit 1
fi
for dependency in loginctl systemctl xdpyinfo timeout readlink install; do
    if ! command -v "$dependency" >/dev/null 2>&1; then
        echo "Missing required command: $dependency (xdpyinfo is in x11-utils)." >&2
        exit 1
    fi
done

script_path=$(readlink -f -- "${BASH_SOURCE[0]}")
script_directory=$(dirname -- "$script_path")
if [[ ! -x $script_directory/.venv/bin/python ]]; then
    echo 'Create the Linux virtual environment at Scrapper/.venv before installing.' >&2
    exit 1
fi
for launcher in run_lubuntu_minute.sh start_lubuntu_timer.sh; do
    if [[ ! -x $script_directory/$launcher ]]; then
        echo "Launcher must be executable: $script_directory/$launcher" >&2
        exit 1
    fi
done

user_bin_directory=$HOME/.local/bin
user_config_directory=${XDG_CONFIG_HOME:-"$HOME/.config"}
unit_directory=$user_config_directory/systemd/user
autostart_directory=$user_config_directory/autostart
credential_directory=$HOME/.config/agentic-sports-betting
credential_file=$credential_directory/scraper.env
mkdir -p -- "$user_bin_directory" "$unit_directory" "$autostart_directory"
install -d -m 0700 -- "$credential_directory"
if [[ ! -e $credential_file && ! -L $credential_file ]]; then
    (
        umask 077
        set -o noclobber
        printf '%s\n' '# Set DATABASE_URL to the scraper PostgreSQL connection string.' \
            '# Optional: SCRAPER_QUEUE_PATH=/persistent/local/path/outcomes.sqlite3' > "$credential_file"
    )
fi

ln -sfnT -- "$script_directory/run_lubuntu_minute.sh" "$user_bin_directory/agentic-scraper-minute"
start_link=$user_bin_directory/start-agentic-scraper-timer
ln -sfnT -- "$script_directory/start_lubuntu_timer.sh" "$start_link"
for unit in agentic-scraper-minute.service agentic-scraper-minute.timer; do
    install -m 0644 -- "$script_directory/systemd/$unit" "$unit_directory/$unit"
done

# Desktop Exec quoting is applied after general string unescaping: encode both
# layers and escape literal field-code percent signs. Bash is the fixed command
# so unusual characters in the user's home remain a quoted script argument.
desktop_argument=$start_link
desktop_argument=${desktop_argument//\\/\\\\}
desktop_argument=${desktop_argument//\"/\\\"}
desktop_argument=${desktop_argument//\`/\\\`}
desktop_argument=${desktop_argument//\$/\\\$}
desktop_argument=${desktop_argument//%/%%}
desktop_argument=${desktop_argument//\\/\\\\}
desktop_argument=${desktop_argument//$'\n'/\\n}
desktop_argument=${desktop_argument//$'\r'/\\r}
desktop_argument=${desktop_argument//$'\t'/\\t}
autostart_file=$autostart_directory/agentic-scraper-minute.desktop
{
    printf '%s\n' '[Desktop Entry]' 'Type=Application' \
        'Name=Agentic scraper minute timer' \
        'Comment=Start due-work checks in the local graphical session'
    printf 'Exec=/bin/bash "%s"\n' "$desktop_argument"
    printf '%s\n' 'Terminal=false'
} > "$autostart_file"
chmod 0644 -- "$autostart_file"

systemctl --user daemon-reload
printf 'Installed user timer and graphical autostart: %s\n' "$autostart_file"
printf 'Set DATABASE_URL in %s (keep this file private).\n' "$credential_file"
echo 'The desktop autostart starts the timer at graphical login; no lingering is enabled.'
"$script_directory/start_lubuntu_timer.sh"
