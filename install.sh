#!/bin/bash
set -eu
command -v python3 >/dev/null || { echo 'Python 3 required.'; exit 1; }
appdir="$HOME/.local/share/pi-app-store/program"
if [ "$(id -u)" -eq 0 ]; then bindir=/usr/local/bin; else bindir="$HOME/.local/bin"; fi
mkdir -p "$appdir" "$bindir"
tmp=$(mktemp "$appdir/appstore.XXXXXX")
trap 'rm -f "$tmp"' EXIT
if [ "${1:-}" = --local ]; then
    cp -- "$(dirname -- "$0")/appstore.py" "$tmp"
else
    commit=${1:-};digest=${2:-}
    [[ "$commit" =~ ^[a-f0-9]{40}$ && "$digest" =~ ^[a-f0-9]{64}$ ]] || { echo 'Use: bash install.sh COMMIT SHA256 (hash independently verified). Or --local for a reviewed checkout.'; exit 1; }
    command -v wget >/dev/null || { echo 'Install wget first.'; exit 1; }
    wget -O "$tmp" "https://raw.githubusercontent.com/Greenisus1/pi-app-store/$commit/appstore.py"
    printf '%s  %s\n' "$digest" "$tmp" | sha256sum -c -
fi
printf "Install reviewed Store program into %s? [y/N] " "$appdir/appstore.py"
IFS= read -r answer
[ "$answer" = y ] || { echo Cancelled.; exit 1; }
python3 - "$tmp" "$bindir" "$appdir/appstore.py" <<'PY'
import itertools,os,shlex,sys,tempfile
from pathlib import Path
source,bindir,program=sys.argv[1:]
compile(Path(source).read_bytes(),'appstore.py','exec')
binpath=Path(bindir);launcher=binpath/'appstore'
old=binpath/'AppStore'
old_owned=old.is_file() and not old.is_symlink() and program in old.read_text() and 'exec python3' in old.read_text()
if launcher.is_symlink():
    if os.readlink(launcher)!='AppStore' or not old_owned:raise SystemExit('Unrelated appstore symlink. Nothing replaced.')
elif launcher.exists():
    if not launcher.is_file() or program not in launcher.read_text() or 'exec python3' not in launcher.read_text():raise SystemExit('Unrelated appstore command. Nothing replaced.')
print('Installing reviewed Store program into',program)
print('One command: appstore. Mixed-case spellings are removed only when they belong to this installer.')

os.replace(source,program)
# Clean only symlinks owned by previous releases; never delete unrelated commands.
for chars in itertools.product(*[(c.lower(),c.upper()) for c in 'appstore']):
    path=binpath/''.join(chars)
    if path.is_symlink() and os.readlink(path)=='AppStore' and old_owned:path.unlink()
if old_owned:old.unlink()
fd,stage=tempfile.mkstemp(prefix='.appstore-launcher-',dir=binpath)
with os.fdopen(fd,'w') as stream:stream.write('#!/bin/bash\nexec python3 '+shlex.quote(program)+' "$@"\n')
os.chmod(stage,0o755);os.replace(stage,launcher)
PY
printf 'Installed. Use appstore. To avoid network checks: appstore --offline\n'
