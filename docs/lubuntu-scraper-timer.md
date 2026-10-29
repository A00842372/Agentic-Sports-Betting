# Lubuntu minute timer: installation and operations

This guide operates the user timer delivered by
[#12](https://github.com/A00842372/Agentic-Sports-Betting/issues/12).
[#9](https://github.com/A00842372/Agentic-Sports-Betting/issues/9) owns the real
Lubuntu deployment smoke test. **The smoke test has not been executed by writing
this guide.** Record its evidence in #9 and the final
[#14 validation campaign](https://github.com/A00842372/Agentic-Sports-Betting/issues/14).

The timer checks the current UTC minute once per minute. Its one oneshot service
invokes the existing `Scrapper/generate_instance.py` command. Discovery retains
its separate existing trigger and cadence.

## Prerequisites

Use the actual scraping user's **local graphical Lubuntu login**, with systemd's
user manager and logind available. `DISPLAY` must let that user access the local
desktop, including XWayland when applicable. Prepare a Linux checkout and virtual
environment; a Windows `.venv/Scripts` environment is not the Linux environment.

From the repository root, install the Linux dependencies and browser:

```sh
sudo apt install python3-venv x11-utils
python3 -m venv Scrapper/.venv
. Scrapper/.venv/bin/activate
python -m pip install pandas requests playwright -r Scrapper/requirements-postgres.txt
python -m playwright install --with-deps chromium
```

Playwright's [browser installation guide](https://playwright.dev/python/docs/browsers)
describes the browser and OS dependency installation. Run Python/browser setup
as the scraping user so its browser installation is available to the user timer.

The database and discovery tables must already be initialized as described in
[POSTGRES.md](../Scrapper/POSTGRES.md). Keep database roles and model credentials
in [#8's history guide](../Scrapper/HISTORY.md), VPN setup in
[#10](https://github.com/A00842372/Agentic-Sports-Betting/issues/10), and backups
in [#11's runbook](collection-backups.md).

Pinnacle and Playdoit retain headed sessions and persistent Linux profiles at
`Scrapper/utilities/pinnacle_profile` and
`Scrapper/utilities/playwright_profile`. The scraping user needs write access.
Ensure other browser processes are not holding those profiles. Reusing a Windows
profile does not establish a working Linux browser profile; record any profile
or browser startup failure in the deployment gate.

Prepare the service's private environment file before installation, since the
installer can start the timer immediately from a valid graphical session:

```sh
install -d -m 0700 "$HOME/.config/agentic-sports-betting"
touch "$HOME/.config/agentic-sports-betting/scraper.env"
chmod 0600 "$HOME/.config/agentic-sports-betting/scraper.env"
```

Edit that file locally with the scraper's real connection value:

```ini
DATABASE_URL="postgresql://scraper@localhost/sports_betting"
# Optional persistent local queue override:
# SCRAPER_QUEUE_PATH=/persistent/local/path/outcomes.sqlite3
```

The example is a placeholder, not supplied credentials. This is a systemd
environment file: use `NAME=value` assignments, without shell substitution or
`export`. The unit reads this fixed `~/.config` location even when the desktop
uses a custom `XDG_CONFIG_HOME`. Existing file contents are preserved by the
installer; its newly created template alone is not a configured database.

## Install and start from a graphical terminal

Check the display/session guard and lingering state:

```sh
xdpyinfo -display "$DISPLAY" >/dev/null
loginctl list-sessions
bash Scrapper/run_lubuntu_minute.sh --check-session
loginctl show-user "$(id -u)" --property=Linger --value
```

The first check and the runner check must exit 0. Lingering must report `no`.
If it was previously enabled, have an administrator run
`sudo loginctl disable-linger "$(id -un)"`, then check again. The installer does
not change a pre-existing lingering setting and never enables it.

Install as the scraping user, without sudo:

```sh
bash Scrapper/install_lubuntu_timer.sh
```

The installer requires the launchers to be executable and
`Scrapper/.venv/bin/python` to exist. If a checkout lost executable permissions,
restore them before rerunning the installer:

```sh
chmod +x Scrapper/run_lubuntu_minute.sh Scrapper/start_lubuntu_timer.sh Scrapper/install_lubuntu_timer.sh
```

Installed user-owned artifacts are:

| Installed location | Purpose |
| --- | --- |
| `~/.local/bin/agentic-scraper-minute` | Symlink to `Scrapper/run_lubuntu_minute.sh`. |
| `~/.local/bin/start-agentic-scraper-timer` | Symlink to `Scrapper/start_lubuntu_timer.sh`. |
| `${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/agentic-scraper-minute.service` | The oneshot due-work service. |
| `${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/agentic-scraper-minute.timer` | The minute calendar timer. |
| `${XDG_CONFIG_HOME:-$HOME/.config}/autostart/agentic-scraper-minute.desktop` | Starts the helper at each graphical login. |
| `~/.config/agentic-sports-betting/scraper.env` | Private database/queue environment, preserved on reinstall. |

The XDG helper imports the current login's `DISPLAY`, `XAUTHORITY`,
`WAYLAND_DISPLAY` and `DBUS_SESSION_BUS_ADDRESS` into the user systemd manager.
It first clears those names so an absent value does not retain an earlier
login's credentials. It then starts the timer. In an already active graphical
session, start or refresh it with:

```sh
bash Scrapper/start_lubuntu_timer.sh
```

Use this helper for startup. The unit has no boot-time enablement target; its
lifecycle starts through graphical autostart. A helper invocation with no local
graphical session skips without starting the timer. The installed symlinks point
to this checkout, so rerun the installer after moving it.

## Observe and operate

```sh
systemctl --user list-timers --all agentic-scraper-minute.timer
systemctl --user status agentic-scraper-minute.timer agentic-scraper-minute.service
systemctl --user show agentic-scraper-minute.service -p ActiveState -p SubState -p Result -p ExecMainCode -p ExecMainStatus
journalctl --user -u agentic-scraper-minute.service -u agentic-scraper-minute.timer --since today --no-pager
```

For live Python and browser errors:

```sh
journalctl --user -f -u agentic-scraper-minute.service
```

Normal Python output and tracebacks go to the user journal. The runner propagates
Python's exit status. A oneshot can remain `activating` while collection is
running, then return to inactive between activations; this is compatible with an
active timer. A tick without due matches
prints the no-matches message and need not create a run.

The calendar is `*-*-* *:*:00`, `AccuracySec=1s`, `Persistent=false`. Systemd
serializes activations of this service. It does not launch parallel copies while
one invocation is active and does not backfill missed timer activations. The
existing CLI reconciles missed scheduled slots on its next successful check.

For `--check-session`, exit 0 allows collection, exit 1 is an expected skip, and
exit 255 reports a missing required command. The
[ExecCondition contract](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html#ExecCondition=)
keeps that expected skip from becoming a failed scrape. Both ExecCondition and the runner
check the current UID's active, non-remote X11/Wayland session and usable display.
An old DISPLAY alone is insufficient. Units also follow
`graphical-session.target` when the desktop manages that target. If an SSH login
keeps the user manager alive after logout, an armed timer can still show ticks;
the guard must prevent Python from starting. Verify that behavior in #9.

Inspect only the imported desktop variables when diagnosing display problems:

```sh
systemctl --user show-environment | sed -n '/^DISPLAY=/p; /^XAUTHORITY=/p; /^WAYLAND_DISPLAY=/p; /^DBUS_SESSION_BUS_ADDRESS=/p'
```

Use the helper from a valid graphical login to refresh them. If logind or the
actual Lubuntu display cannot satisfy the guard, record a blocker in #9. A
headless browser change or fabricated session/display value is not a verified
deployment fix.

### Stop, disable and uninstall

Stop future ticks while allowing any active collection to finish:

```sh
systemctl --user stop agentic-scraper-minute.timer
```

To interrupt an active collection deliberately:

```sh
systemctl --user stop agentic-scraper-minute.service
```

The service stops its process group, including browser children. An interrupted
collection can leave an incomplete run; inspect its actual database status.

To keep the timer off at subsequent graphical logins, also disable its XDG entry:

```sh
user_config_directory=${XDG_CONFIG_HOME:-"$HOME/.config"}
mv -- "$user_config_directory/autostart/agentic-scraper-minute.desktop" "$user_config_directory/autostart/agentic-scraper-minute.desktop.disabled"
```

To restore graphical startup, rename that file back to `.desktop` and run the
start helper from a local graphical terminal. For uninstall, keep the timer
stopped, disable autostart, and wait until the service is inactive before removing
only the installed launchers/units/entry:

```sh
if service_state=$(systemctl --user show agentic-scraper-minute.service --property=ActiveState --value) && [ "$service_state" = inactive ]; then
    user_config_directory=${XDG_CONFIG_HOME:-"$HOME/.config"}
    rm -f -- "$HOME/.local/bin/agentic-scraper-minute" "$HOME/.local/bin/start-agentic-scraper-timer"
    rm -f -- "$user_config_directory/systemd/user/agentic-scraper-minute.service" "$user_config_directory/systemd/user/agentic-scraper-minute.timer"
    rm -f -- "$user_config_directory/autostart/agentic-scraper-minute.desktop" "$user_config_directory/autostart/agentic-scraper-minute.desktop.disabled"
    systemctl --user daemon-reload
else
    printf '%s\n' 'Service is not confirmed inactive; inspect its state and wait/stop before rerunning uninstall.'
fi
```

The removal branch requires a successful query reporting `inactive`; it blocks
on a running/transitioning/failed unit or an unavailable user manager. Inspect
errors and stop/reset a failed unit before retrying. Keep the
credential file, queue, database, backup
artifacts and repository. The Windows batch launchers are historical context and
are not part of this installation.

## Deployment smoke checklist — execute on Lubuntu

Use a safe isolated database with the delivered schema, actual due sample work,
and valid current bookmaker links. Fake fixture URLs cannot prove headed-browser
operation. Follow the existing storage guide to populate it; this timer does not
add a discovery scheduler. Configure the service and model reader for that test
database using their existing credential instructions.

Record the code commit, local/UTC times, relevant match/slot/run IDs, unit states,
and sanitized journal/database evidence for every step:

1. **Local graphical login:** log in through the Lubuntu desktop and observe at
   least two consecutive minute activations in the journal and timer status.
   Expect the no-argument due-work CLI once per activation, using the Linux
   virtual environment. No due work means no required database run.
2. **Headed sample collection:** select a currently due real sample with both
   Pinnacle and Playdoit links. Observe their headed windows and usable Linux
   profiles. Expect a real run and bookmaker outcomes with current actual start
   and attempt times. Record any session/profile failure as a failed or blocked
   smoke result; do not substitute headless mode.
3. **Graphical logout:** record the logout UTC time and actually log out, rather
   than merely locking the screen. Observe from another device or an SSH session
   used only for status/history inspection. Expect no new scraping run during
   the interval without a local graphical session. Record lingering work or
   browser activity as a gate failure requiring investigation.
4. **SSH-only session:** while no local graphical session exists, inspect the
   journal and run only `bash Scrapper/run_lubuntu_minute.sh --check-session`.
   Expect skip status 1 and no Python collection. Repeat this check with the
   recorded old DISPLAY supplied only to the check command to prove that stale
   display credentials cannot bypass the logind guard.
5. **Resume after passed slots:** leave known due slots unrun during logout, then
   log back in locally. Expect fresh environment import and resumed timer ticks.
   The CLI must mark the passed unrun slots missed with their intended times,
   without bookmaker attempts or synthetic odds. Any new/late real run must
   retain its actual time rather than pretending to have run in the missed slot.
6. **Discovery cadence:** compare the pre-install discovery trigger and recorded
   intervals with those after installation. Expect the same independent cadence.
   Inspect the installed unit and runner: they invoke only the due-work CLI,
   not match discovery. If the existing discovery schedule is unknown, leave
   this check unverified and record the missing baseline in #9.
7. **Logs and lifecycle:** verify Python failures are visible in the user journal,
   a running oneshot is serialized, stop/disable prevents future starts, and
   graphical startup can be restored using the documented helper and XDG entry.

Use the public model history query to inspect the selected sample from the
repository root. Set `MODEL_DATABASE_URL` externally as described in #8, and
replace the sample UUID below:

```sh
export SCRAPER_SMOKE_MATCH_ID='replace-with-the-real-match-uuid'
```

```sh
Scrapper/.venv/bin/python - <<'PY'
import os
from Scrapper.match_history import read_match_history

history = read_match_history(os.environ["SCRAPER_SMOKE_MATCH_ID"])
columns = ["slot_id", "scheduled_time", "run_id", "started_at", "outcome_id",
           "attempted_at", "detected_at", "bookmaker", "status"]
print(history[columns].drop_duplicates().tail(40).to_string(index=False))
PY
```

Run that Python snippet in the Linux environment; the duplicated odds-field rows
are reduced only for readable inspection, with distinct outcome IDs retained.
Compare these times/identities with the recorded login/logout intervals. Missed
rows must have no run/outcome ID or actual attempt time; current attempts retain
their real run/outcome IDs and actual times.

Attach commands, observed outcomes, IDs, timestamps and remaining environment
limitations to #9 and #14. Installation, syntax checks and documentation review
alone do not complete the Lubuntu smoke gate.
