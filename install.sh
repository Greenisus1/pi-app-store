#!/bin/bash
set -eu
command -v python3 >/dev/null || { echo 'Python 3 is needed. On DietPi run: apt-get install -y python3 wget'; exit 1; }
command -v wget >/dev/null || { echo 'Install wget first.'; exit 1; }
appdir="$HOME/.local/share/pi-app-store/program"
mkdir -p "$appdir"
tmp=$(mktemp "$appdir/appstore.XXXXXX")
trap 'rm -f "$tmp"' EXIT
if [ "${1:-}" = --local ]; then
    cp -- "$(dirname -- "$0")/appstore.py" "$tmp"
else
    wget -O "$tmp" https://raw.githubusercontent.com/Greenisus1/pi-app-store/main/appstore.py
fi
python3 - "$tmp" <<'PY'
import sys
from pathlib import Path
compile(Path(sys.argv[1]).read_bytes(), 'appstore.py', 'exec')
PY
mv "$tmp" "$appdir/appstore.py"
if [ "$(id -u)" -eq 0 ]; then
    bindir=/usr/local/bin
else
    bindir="$HOME/.local/bin"
fi
mkdir -p "$bindir"
printf '#!/bin/bash\nexec python3 %q "$@"\n' "$appdir/appstore.py" > "$bindir/AppStore"
chmod 755 "$bindir/AppStore"
echo 'Installed. Run AppStore to open the store.'
case ":$PATH:" in
    *":$bindir:"*) ;;
    *) echo "This account does not have $bindir on PATH. Use $bindir/AppStore or add that directory to PATH." ;;
esac
