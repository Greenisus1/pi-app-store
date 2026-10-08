#!/bin/bash
set -eu
command -v python3 >/dev/null || { echo 'Python 3 is needed. On DietPi run: apt-get install -y python3 wget'; exit 1; }
if [ "${1:-}" != --local ]; then
    command -v wget >/dev/null || { echo 'Install wget first.'; exit 1; }
fi
appdir="$HOME/.local/share/pi-app-store/program"
if [ "$(id -u)" -eq 0 ]; then
    bindir=/usr/local/bin
else
    bindir="$HOME/.local/bin"
fi
mkdir -p "$appdir" "$bindir"
tmp=$(mktemp "$appdir/appstore.XXXXXX")
trap 'rm -f "$tmp"' EXIT
if [ "${1:-}" = --local ]; then
    cp -- "$(dirname -- "$0")/appstore.py" "$tmp"
else
    wget -O "$tmp" https://raw.githubusercontent.com/Greenisus1/pi-app-store/main/appstore.py
fi
python3 - "$tmp" "$bindir" "$appdir/appstore.py" <<'PY'
import itertools
import os
from pathlib import Path
import shlex
import sys
source, bindir, program = sys.argv[1:]
compile(Path(source).read_bytes(), 'appstore.py', 'exec')
binpath = Path(bindir)
names = [''.join(chars) for chars in itertools.product(*[(c.lower(), c.upper()) for c in 'appstore'])]
# Never overwrite an unrelated command. Preflight every spelling before changes.
for name in names:
    path = binpath / name
    if path.is_symlink():
        if os.readlink(path) != 'AppStore':
            raise SystemExit('Another command already uses ' + str(path) + '. Nothing replaced.')
    elif path.exists():
        if name != 'AppStore' or not path.is_file() or program not in path.read_text():
            raise SystemExit('Another command already uses ' + str(path) + '. Nothing replaced.')
# Move validated code only after all name conflicts have been checked.
os.replace(source, program)
launcher = binpath / 'AppStore'
if launcher.is_symlink():
    launcher.unlink()
stage = binpath / '.pi-app-store-launcher.tmp'
stage.write_text('#!/bin/bash\nexec python3 ' + shlex.quote(program) + ' "$@"\n')
stage.chmod(0o755)
os.replace(stage, launcher)
for name in names:
    if name == 'AppStore':
        continue
    path = binpath / name
    if not path.is_symlink():
        path.symlink_to('AppStore')
PY
echo 'Installed. Any casing works: appstore, Appstore, AppStore, APPSTORE.'
echo 'Menu 2 runs installed apps. For no network checks: appstore --offline'
case ":$PATH:" in
    *":$bindir:"*) ;;
    *) echo "This account does not have $bindir on PATH. Use $bindir/appstore or add that directory to PATH." ;;
esac
