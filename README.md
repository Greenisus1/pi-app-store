# Pi App Store

Terminal-first app catalog for Raspberry Pi and DietPi. Python 3.9+ and Bash. Optional Tk window needs a desktop. No sandbox: a confirmed app installer still has root access. The catalog is not a curated or signed distribution. Do not install code you cannot review.

## Security changes in 1.8.0

- Every app install/update shows the exact `bash app-store.sh install` command, pinned commit, and all checkout text files with SHA256 before asking. It does not show only the dispatcher. Binary checkouts or more than 2 MB of review content are refused. Nested downloaded code cannot be certified by this review.
- apt entries show exact commands and ask. The downloaded Ollama installer is disabled; install it yourself after upstream review.
- Store replacement requires a separately trusted exact commit/SHA256 pin and explicit full-source confirmation. Wrong/missing pins stop without replacement. A hash is not a signature. Get the expected hash independently from a maintainer you trust, not from the same untrusted download.
- Automatic boot updates and login app execution are disabled, including invocations from old hooks/services. Settings lets you clear old hooks/settings; it cannot enable them. Existing older installed versions must be upgraded manually to receive this protection.
- One lowercase `appstore` command replaces the 256 case variants. Installer cleanup removes only old links it can identify as its own. Unrelated commands are preserved. Arbitrary casing no longer works.

## Install a reviewed checkout

Read all source files first. Run:

```sh
bash install.sh --local
```

It asks before installing. Root installs use `/usr/local/bin/appstore`; normal-user installs use `~/.local/bin/appstore`. Program location: `~/.local/share/pi-app-store/program/appstore.py`. Put the normal-user bin directory on PATH if needed.

For a pinned download, download and review `install.sh`, then supply the exact 40-character commit and independently verified 64-character program SHA256:

```sh
bash install.sh COMMIT SHA256
```

Placeholders above are not runnable values. Installation fails without the pin. HTTPS/download checks and compile checks are not a signature or a security audit.

## Updates

Startup checks are read-only. `appstore --offline` disables network checks. Updates never run on startup or boot. For a Store update, after independent verification:

```sh
appstore --trust-store-update COMMIT SHA256
```

This asks before saving the pin. Open Updates, review the source and confirm replacement. A program-only update does not replace launchers; rerun the reviewed local installer to migrate old casing links. No automatic remote upgrade was performed on your Pi.

## Use

`appstore` opens the fullscreen terminal view. `--plain` opens the numbered menu; `--gui` opens the optional desktop window. R/F5 refresh, arrows select, Enter opens, q quits. s opens Settings, o sorts, u reviews uninstall, U opens update. Games, 3D games, learning games and beta categories are preserved. Update all keeps each install's confirmation and failed/cancelled items pending.

Installed checkouts are tracked inside the Store, not a separate tool. Installing an already-present identical commit reports installed and does not rerun the installer. Missing checkouts can be reinstalled; changed commits use the same reviewed install flow. Apps installed outside the Store are not automatically imported.

## Add an app

A public source repo needs root `app-store.sh` with `# pi-app-store: 1` in the first five lines, and `install`/`run` actions. Optional `# pi-app-store-category: games` is also within the first five lines. `app-version.json` contains the app version. These markers are discovery metadata, not approval, signing or security certification.

The Store resolves a commit, checks the marker against the checkout, rejects archive links/path traversal, stages the full checkout, then reviews before executing. Code can call external commands/network. Root apps remain unsandboxed; package changes are not rolled back.

## Old startup integrations

The updated `--boot-self-update` and `--login-start` commands are no-ops. Use Settings to remove the Store's marked legacy service/profile hook. Unrelated service/profile content is preserved. Old installed versions still need manual replacement. No device changes are made merely by publishing this version.

## Limits and tests

Linux mocked security/unit tests and terminal checks are used. Physical Raspberry Pi, actual apt installation and real hardware changes are not covered by those tests. No DietPi core scripts are patched by this repository. The separate DietPi PR is not updated by this release. Licensed under MIT, copyright 2026 Greenisus1. Copies or substantial portions must keep the copyright and permission notice. See LICENSE.

## Request an app

Suggest an app using the [Pi App Store App Request form](https://docs.google.com/forms/d/e/1FAIpQLSdTDiZ4kCPN49FF0DOuXw1XkccwWpcI3Fj4TofkIFs6nJXBqA/viewform). The link is also in `appstore --help`, or run `appstore --request-app`. A request is a suggestion, not an automatic installation or approval.

## Third-party package apps

`nnn` and `btop` appear alongside the existing Apps; `moon-buggy` appears in Games. They are small package-manager wrappers, not rebranded copies of the upstream projects. Each checks the installed Debian package and executable before apt installation. Apt checks your configured package candidate; the wrappers do not fetch upstream scripts. Use a regular account for interactive tools. Removing the Store checkout leaves the system package installed, and apt manages package updates.
