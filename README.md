# Pi App Store

A small terminal app store for Raspberry Pi and DietPi. Browse opt-in GitHub apps, install them, and launch installed apps from one menu. A separate **Other software** menu installs Python 3 or Ollama.

Python 3.9+ and Bash are required. No Python packages, accounts, tokens, or keys are needed. Internet access is needed to browse and install. Startup update and upstream-edit checks run in a background daemon thread. The menu and Run apps open immediately, even when the network is down. Each request has a five-second socket timeout; slow networks can delay completing checks, but not launching apps or quitting. Use `appstore --offline` to disable every network check, or `appstore --no-color` to disable colors. Colors are also disabled for redirected output, dumb terminals, and NO_COLOR. Long menu text wraps to the terminal width (minimum 24 columns).

## Start

On the Pi, with Python 3 and wget installed:

```sh
wget -O install-appstore.sh https://raw$(printf .)githubusercontent$(printf .)com/Greenisus1/pi-app-store/main/install.sh && bash install-appstore.sh
```

After installation, type `appstore` to open it. Every casing works, including `Appstore`, `AppStore`, and `APPSTORE`: the installer creates all 256 case variants. It refuses to replace unrelated commands. Rerun this installer to add the new command spellings; a program-only self-update does not change launchers. On DietPi as root the launcher is `/usr/local/bin/AppStore`. Non-root installs use `~/.local/bin/AppStore`; that directory must be on PATH (the installer warns if it is not). The installer stores the program in `~/.local/share/pi-app-store/program/`.

If Python is missing on DietPi, run `apt-get update` then `apt-get install -y python3 wget` as root first. The store itself needs Python to start; the Python menu is for installing pip/venv or updating Python after that.

## Default view

On a real terminal (including plain SSH on a headless Pi) the store opens a colored block view: a sidebar with Apps, Games, Run apps, Updates and Other software, a highlighted list you move with the arrow keys, and a detail box. It uses only Python's built-in curses, no desktop needed.

Keys: Up/Down (or j/k) move, Left/Right or Tab switch section (or press 1 to 5), Enter opens the item (runs it if installed, installs it if not), i install, r run, u update, / search, s change the sort order in Apps and Games (newest first by default, then A-Z, then Z-A), F5 refresh, ? help, q quit. Installers, prompts and apps run in the normal terminal and return to the store when done. Use `appstore --plain` (or set APPSTORE_PLAIN=1) for the plain numbered menu. It is also used automatically on dumb terminals and when output is not a terminal. `--no-color` keeps the layout in black and white. A terminal needs at least 40 columns by 10 rows. The selected app's full description shows in the panel at the bottom (taller terminals show more lines).

## Menus

- **GitHub apps:** public, non-fork, non-archived repos from `Greenisus1` that have the marker described below. Pick an app and press Enter or i; there is no approval prompt. Installing only works when the store runs as root (`sudo appstore`).
- **Games folder:** a game puts `# pi-app-store-category: games` on line 3 of its `app-store.sh` (within the first 5 lines, after the signature). GitHub apps then asks Apps or Games first. Without that line an app is a normal app.
- **Window (optional):** `appstore --gui` opens a file-manager style window: sidebar with Apps, Games, Run apps, Updates and Other software, a searchable list, and Install / Run / Run in terminal / Update buttons. It needs Python Tk and a desktop or VNC session (`apt-get install -y python3-tk`); over plain SSH there is no screen, so use the terminal menu (`appstore`) there. Installer scripts can run with your account privileges; review the source before installing. Root execution has no extra review prompt. Installer progress prints in the terminal that started the window. Keyboard apps (such as Walk AI) use Run in terminal; window apps use Run.
- **Run apps:** choose any app installed by this store. Ready and missing-file status is shown. Apps launch locally without downloads. When the app exits or fails, you return to Run apps. Press 0 to return to the main menu. Missing or invalid apps cannot launch; reinstall them. Python 3 opens an interactive shell; Ollama lists locally installed models and lets you run one. System tools appear only when their command is installed. Apps installed outside this store are not automatically imported.
- **Updates:** background startup checks for changed app versions (or newer commits for legacy apps). Failed/offline checks are reported and do not stop the store. Checks never run new code or change installed apps. Pick Updates to confirm a change; app updates can run their installer; review source before choosing them. Self-updates replace only appstore.py after a syntax check, then require restarting with AppStore.
- **Other software:** Python and Python Tk (python3-tk, needed by window apps) use Debian's apt packages; each entry shows installed or missing. Ollama downloads the official installer with wget, shows it, and asks before running it. The upstream Ollama script may use curl internally. Model downloads are separate.

Apps without a marker are deliberately hidden. At first the list can be empty until existing app repos opt in. This store repo includes its own marker so it can appear too.

## Make a repo an app

Add **app-store.sh** at the root of the app repo, on its default branch. Put `# pi-app-store: 1` in its first five lines. The script must handle two arguments:

- `install`: install dependencies or prepare the app; return nonzero on failure.
- `run`: launch the app from the repo directory. Include any needed arguments or prompts here.

For a single-file Python app, a starting point is:

```bash
#!/bin/bash
# pi-app-store: 1
set -eu
cd -- "$(dirname -- "$0")"
case "${1:-}" in
  install) python3 -m py_compile myapp.py ;;
  run) exec python3 myapp.py ;;
  *) echo 'Use: bash app-store.sh install OR bash app-store.sh run'; exit 1 ;;
esac
```

Replace `myapp.py` with the real filename. A Bash app can use `bash -n myapp.sh` to check syntax in `install`, and `exec bash myapp.sh` for `run`. Apps needing inputs (such as cview) should prompt or declare arguments in their run action. This is an opt-in marker, **not proof of authorship or a security certification**.

## Install details and safety

Discovery only reads markers; it does not run them. After choosing an app, the store resolves the current default branch to a commit, checks the marker from that commit, and (only if the store was started as root, for example `sudo appstore`) goes straight on without asking. Without root it stops and says to rerun with `sudo appstore`. It downloads the whole repo at that same commit, checks that the marker matches, rejects links and unsafe archive paths, then runs `bash app-store.sh install`.

Because there is no approval step, installs, software installs and updates all need root (`sudo appstore`); browsing and searching work without it. The installer can call other files or the network. Review the repository too if you do not trust it. On DietPi's root account, installers and apps run as root and have full system access. There is no sandbox. Package installations may affect the system; this store does not roll them back.

Files and the installed list are stored under `~/.local/share/pi-app-store/`. Apps launch from their saved commit without downloading a new version. To update, choose Updates or browse and install again. Old commit folders remain; there is no uninstall menu in this first version. Deleting a folder does not undo a system package installation.

Downloads are bounded: 40 MB compressed, 100 MB extracted, at most 5,000 archive entries, and at most 20 MB per file. Very large apps need a different installer. Discovery and version checks use public HTML/Atom/raw/codeload, not the REST API quota. Errors are reported without pretending the catalog is empty. Refresh with GUI Refresh, rich F5/R or plain R.

## Add more other software

Edit `SOFTWARE` near the top of `appstore.py`. For an apt package:

```python
('Git', ['apt', 'git'])
```

Official Ollama installation reference: https://docs.ollama.com/linux

## App version files

Put **app-version.json** in each app repository root, beside app-store.sh:

```json
{"version": "1.0.0"}
```

Change the string when shipping an app update. Keep it at most 64 characters, using letters, digits, dots, underscores, plus or minus. A changed string means an update is available; comparison is equality, not numeric version ordering. Use new version strings for new releases. Documentation-only commits need not change it.

The store reads this file from the app's current default-branch commit and compares it with the version saved at install time. Existing installs without a saved version use the version file in their installed folder if available. Apps without any version file retain legacy commit-based checks. Adding a version file to an unversioned app offers one update so its version is recorded. An invalid version file reports a failed check instead of guessing. Update installation stays pinned to the commit checked, even if the repository changes afterward. Install/browse validates the marker; root users can run its installer without a second confirmation. The App Store itself carries app-version.json too; its version must match VERSION in appstore.py.

## Other software edit records

On each online startup, a read-only background check looks at the latest default-branch source commit for **python/cpython** and **ollama/ollama** through public HTML and Atom feeds. These are upstream edits, not release announcements and not checks of which package version apt offers. No software is updated automatically.

The local file `~/.local/share/pi-app-store/software-changes.json` records each latest commit SHA, source timestamp, first-line summary, observed commit URL, check timestamp, and up to 20 distinct observations per software item. It includes last-check errors and preserves prior records when a check fails. View these records under **Other software > View recorded upstream edits**, including offline. The history starts when this feature is first run; it is not a full upstream changelog. HTML/Atom requests can still be throttled. JSON contains metadata only, not credentials.

## Testing

For the full1.6.0 suite, extract store-release-tests.zip into a temporary folder and run `python3 -m unittest -v` there. Archive includes the exact1.6.0 program, installer, modules and test sources. Tests use temporary homes and fake network responses; no apt, Ollama installation or real network is used. Case-variant launch tests execute all 256 launchers. UI preview is checked at 76 and 40 columns. Tested on Linux, not yet on a real Raspberry Pi. Apps requiring hardware or system packages still need their own environment tests.


## GitHub rate-limit repair in 1.5.1

No api.github.com requests remain. Public repo discovery reads GitHub's public source-repository HTML pages; default branch is read from repo HTML, and immutable 40-character commits from GitHub Atom feeds. Installer/program/version files use raw.githubusercontent.com; app archives use codeload.github.com at that same commit. Existing marker equality, bounded extraction and root install gate are kept. Other Software upstream-edit checks use HTML/Atom too. No token or gh login needed.

HTML/Atom/raw/codeload still need network and can fail or be throttled separately; this avoids the anonymous REST API quota, not every GitHub outage. HTTP 403/429 gives a clear stop-and-try-later message, no automatic retries; installed apps remain available offline. If HTML/feed format changes the store refuses to guess a branch/commit. Source lists exclude forks, as before. All public marked repos are checked; private repos remain outside discovery. Newest sorting uses latest commit-feed timestamps when available, otherwise falls back to name.

Verified 47 unit tests, live public HTML/Atom/raw/archive read+extraction on Linux; no actual app installer, apt or Pi install in the live test. Physical Raspberry Pi untested. Upgrade from broken older Store: use existing installer download instructions rather than the old API-based in-app update check.


## Light/dark in 1.5.2

Press T in the rich terminal view to toggle light/dark, or use `appstore --theme light` / `appstore --theme dark` to choose the starting palette. Default dark. Plain numbered menu has t for the colored text palette (cannot repaint the terminal's entire background). Optional GUI has a Light/dark button. In1.5.2 theme was session-only. Version1.6.0 saves the preference. --no-color/NO_COLOR keeps monochrome behavior and terminal colors can vary. Child apps/installers keep their own palettes; themed store view returns afterward.

53 unit tests, dark/light terminal pixel previews, actual T toggle and GUI button previews checked on Linux. No physical Pi test. No desktop is required: GUI remains optional. Installs keep 1.5.1 no-API fix and root/no-prompt behavior.


## Version 1.6.0: Settings and safe startup

Settings: GUI button, terminal rich view comma key, plain menu5. Light/dark preference is saved privately for next launch. Refresh: GUI button, rich F5/R, plain R. Catalog skips positively identified empty repos, preserving errors for unknown page formats; worker checks no longer print over the terminal UI. Ctrl-C exits cleanly.

Store self-update at OS boot is optional, DEFAULT OFF. Enabling requires root and confirmation, creates only its marked systemd oneshot, does not start it now, and updates Store program only from verified GitHub commit/source. No package or installed-app auto-update. Disable in Settings to remove its service. No systemd means unavailable, not fake success.

Auto-run is per-app, DEFAULT OFF, at visible terminal LOGIN, not unattended OS boot. You pick apps and confirm a marked account profile hook; original profile backup kept. Multiple apps run sequentially, with your account privileges. Disable all to remove the hook. Supported profile selection: .bash_profile, .bash_login, .profile. Unrelated/symlink profiles/services aren't silently replaced. No chosen app starts while configuring.

Other software adds Lua5.4, apt-rdepends and official rpi-imager. Guarded flash: GUI Flash image button, plain Other software Run guarded Pi Imager, rich Other software f key. Local extracted .img only; removable unmounted writable whole disks only, mounted descendants/boot disks rejected, size and state rechecked. Exact ERASE /dev/... phrase required. Uses official rpi-imager --cli --sha256, verification remains ON, never dd or system-drive override. Still destructive: verify image, drive model/serial/size and backups yourself before confirming. No flash performed during tests.

84 tests pass including packaging, preferences, startup rollback, catalog-empty handling and mocked flasher/boot checks. Actual Linux terminal-login PTY and dark/light GUI scroll-list pixels inspected. Hardware flashing, real boot service and Raspberry Pi hardware remain untested. No user's boot/profile toggles enabled by this release. Settings/features do not prove installed on the user's Pi until they update.


## Version1.6.2: Beta apps

Beta is separate from Apps/Games in GUI sidebar, rich3 shortcut and plain Browse. Marker # pi-app-store-category: beta in first5 lines. Root Beta install still asks review confirmation. Beta apps remain in Run apps/Updates after install. Experimental apps may be unstable; read their README limits.87 Linux tests and actual GUI/rich Beta visuals checked. No Raspberry Pi hardware test. No force-update or download-fallback changes in this release.

1.6.2 adds a separate Learning games category in plain/rich/GUI views. Category marker learning-games stays outside Apps/Games/Beta. No force-update, fallback mirror or description-suppression changes included.

## Version 1.7.0

Updates has an Update all button in the optional GUI, an A keyboard action in the rich terminal, and an Update all option in the plain menu. The batch asks for confirmation, keeps each app installer review, reports successes/failures separately, retains failed or cancelled updates, and updates the Store itself last. This does not automatically update installed apps. Restart the Store after its own code update.

Games has a 3D games child listing (marker category games-3d). Terminal and optional Tk GUI layouts checked on Linux, with 95 tests. Physical Raspberry Pi and non-Linux systems remain untested.
