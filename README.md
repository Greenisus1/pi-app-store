# Pi App Store

A small terminal app store for Raspberry Pi and DietPi. Browse opt-in GitHub apps, install them, and launch installed apps from one menu. A separate **Other software** menu installs Python 3 or Ollama.

Python 3.9+ and Bash are required. No Python packages, accounts, tokens, or keys are needed. Internet access is needed to browse and install. Startup update checks can take time if offline; failures are shown and installed apps can still launch without GitHub access.

## Start

On the Pi, with Python 3 and wget installed:

```sh
wget -O install-appstore.sh https://raw.githubusercontent.com/Greenisus1/pi-app-store/main/install.sh && bash install-appstore.sh
```

After installation, type `AppStore` to open it. On DietPi as root the launcher is `/usr/local/bin/AppStore`. Non-root installs use `~/.local/bin/AppStore`; that directory must be on PATH (the installer warns if it is not). The installer stores the program in `~/.local/share/pi-app-store/program/`.

If Python is missing on DietPi, run `apt-get update` then `apt-get install -y python3 wget` as root first. The store itself needs Python to start; the Python menu is for installing pip/venv or updating Python after that.

## Menus

- **GitHub apps:** public, non-fork, non-archived repos from `Greenisus1` that have the marker described below. Pick an app, review its installer, and confirm installation.
- **Installed apps:** choose an installed app to launch it. When the app exits, you return to the store.
- **Updates:** startup checks for newer App Store code and newer commits in installed app repos. Failed/offline checks are reported and do not stop the store. Checks never run new code or change installed apps. Pick Updates to confirm a change; app updates still show their installer for review. Self-updates replace only appstore.py after a syntax check, then require restarting with AppStore.
- **Other software:** Python uses Debian's apt packages. Ollama downloads the official installer with wget, shows it, and asks before running it. The upstream Ollama script may use curl internally. Model downloads are separate.

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

Discovery only reads markers; it does not run them. After choosing an app, the store resolves the current default branch to a commit, shows the marker from that commit, and asks for confirmation. It downloads the whole repo at that same commit, checks that the marker matches, rejects links and unsafe archive paths, then runs `bash app-store.sh install`.

The installer can call other files or the network. Review the repository too if you do not trust it. On DietPi's root account, installers and apps run as root and have full system access. There is no sandbox. Package installations may affect the system; this store does not roll them back.

Files and the installed list are stored under `~/.local/share/pi-app-store/`. Apps launch from their saved commit without downloading a new version. To update, choose Updates or browse and install again. Old commit folders remain; there is no uninstall menu in this first version. Deleting a folder does not undo a system package installation.

Downloads are bounded: 40 MB compressed, 100 MB extracted, at most 5,000 archive entries, and at most 20 MB per file. Very large apps need a different installer. GitHub's unauthenticated API has rate limits; errors are shown instead of claiming an empty list. Refresh by reopening GitHub apps.

## Add more other software

Edit `SOFTWARE` near the top of `appstore.py`. For an apt package:

```python
('Git', ['apt', 'git'])
```

Official Ollama installation reference: https://docs.ollama.com/linux

## Testing

Syntax and menu flow checked on Linux. Eleven offline tests passed, including update discovery, offline update handling, declining updates, and current-version checks. The installed AppStore launcher was also exercised in a temporary home directory. Offline tests cover marker filtering, a pinned install and launch, declining installs, failed installers, apt command construction, and unsafe archive rejection. Not yet tested on real Pi hardware; no apt or Ollama installation was run during development.
