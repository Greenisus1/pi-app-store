#!/usr/bin/env python3
"""Small, opt-in GitHub app store for Debian-based Raspberry Pi systems."""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import threading
import urllib.error
import urllib.parse
import urllib.request

OWNER = 'Greenisus1'
MARKER = 'app-store.sh'
SIGNATURE = '# pi-app-store: 1'
VERSION = '1.2.0'
VERSION_FILE = 'app-version.json'
OFFLINE = False
NETWORK_TIMEOUT = 5
HOME = Path.home() / '.local' / 'share' / 'pi-app-store'
# Add another apt entry here: ('Display name', ['apt', 'package', ...]).
SOFTWARE = [('Python 3', ['apt', 'python3', 'python3-pip', 'python3-venv']),
            ('Ollama', ['script', 'https://ollama.com/install.sh'])]


def fetch(url, limit=2_000_000):
    if OFFLINE:
        raise OSError('Offline mode: network access disabled')
    req = urllib.request.Request(url, headers={'User-Agent': 'pi-app-store/1',
                                               'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Download exceeds size limit')
    return data


def api(path):
    return json.loads(fetch('https://api.github.com/' + path))


def raw(repo, ref, path=MARKER):
    return 'https://raw.githubusercontent.com/{}/{}/{}/{}'.format(
        OWNER, repo, urllib.parse.quote(ref, safe=''), path)


def parse_version(data):
    value = json.loads(data)
    if (not isinstance(value, dict) or not isinstance(value.get('version'), str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,63}', value['version'])):
        raise ValueError('Invalid app-version.json: expected a short version string')
    return value['version']


def remote_version(name, commit):
    try:
        return parse_version(fetch(raw(name, commit, VERSION_FILE), 4096))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise



def valid_marker(data):
    text = data.decode('utf-8')
    return SIGNATURE in text.splitlines()[:5]


def marker_category(data):
    # Optional marker line in the first 5 lines: # pi-app-store-category: games
    for line in data.decode('utf-8').splitlines()[:5]:
        key, _, value = line.partition(':')
        if key.strip() == '# pi-app-store-category':
            value = value.strip().lower()
            return value if re.fullmatch(r'[a-z0-9-]{1,24}', value) else 'apps'
    return 'apps'


def discover():
    repos = []
    for page in range(1, 21):
        batch = api(f'users/{OWNER}/repos?per_page=100&page={page}')
        repos.extend(r for r in batch if not r['archived'] and not r['fork'])
        if len(batch) < 100:
            break
    errors = []
    def check(repo):
        try:
            marker = fetch(raw(repo['name'], repo['default_branch']), 16_384)
            if valid_marker(marker):
                return dict(repo, category=marker_category(marker))
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                errors.append(f"{repo['name']}: HTTP {exc.code}")
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append(f"{repo['name']}: {exc}")
        return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        apps = [r for r in pool.map(check, repos) if r]
    if errors:
        print('Some repositories could not be checked:')
        print('\n'.join(errors))
    return sorted(apps, key=lambda r: r['name'].lower())


def ask(prompt):
    return input(prompt + ' [y/N] ').strip().lower() == 'y'


def state_path():
    return HOME / 'installed.json'


def load_state():
    try:
        value = json.loads(state_path().read_text())
        if not isinstance(value, dict):
            raise ValueError('Invalid installed list')
        for name, item in value.items():
            if (not isinstance(name, str) or not isinstance(item, dict)
                    or not isinstance(item.get('directory'), str)
                    or not isinstance(item.get('commit'), str)):
                raise ValueError('Invalid installed record. Your files have not been changed.')
        return value
    except FileNotFoundError:
        return {}



def save_state(state):
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = state_path().with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2) + '\n')
    os.replace(tmp, state_path())


def extract(data, dest):
    """Extract regular files only, with bounded sizes and no escaping paths."""
    total = 0
    count = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive:
            count += 1
            parts = PurePosixPath(member.name).parts
            if count > 5000 or not parts or '..' in parts or member.name.startswith('/'):
                raise ValueError('Unsafe archive path or too many files')
            relative = parts[1:]  # GitHub archive has one enclosing directory.
            if not relative:
                continue
            target = dest.joinpath(*relative)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                total += member.size
                if total > 100_000_000 or member.size > 20_000_000:
                    raise ValueError('Archive exceeds size limit')
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open('wb') as out:
                    shutil.copyfileobj(source, out)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
            else:
                raise ValueError('Archive contains a link or special file')


def install(repo, selected_commit=None):
    name = repo['name']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..'):
        raise ValueError('Invalid repository name')
    branch = urllib.parse.quote(repo['default_branch'], safe='')
    commit = selected_commit or api(f'repos/{OWNER}/{name}/commits/{branch}')['sha']
    previous = load_state().get(name)
    if previous and previous.get('commit') == commit and Path(previous['directory']).is_dir():
        print('This commit is already installed. Open Installed apps to launch it.')
        return
    marker = fetch(raw(name, commit), 16_384)
    if not valid_marker(marker):
        raise ValueError('Missing valid app marker at chosen commit')
    version = remote_version(name, commit)
    print(f'\nInstall {OWNER}/{name} at {commit[:12]}')
    print('App version: ' + (version or 'legacy commit tracking'))
    print('Installer to review:\n' + marker.decode())
    print('This script can change files and run commands with your current privileges.')
    if os.geteuid() == 0:
        print('WARNING: you are root. The installer will have full system access.')
    if not ask('Trust this installer and install?'):
        return
    HOME.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=HOME) as tmp:
        stage = Path(tmp) / 'app'
        stage.mkdir()
        extract(fetch(f'https://api.github.com/repos/{OWNER}/{name}/tarball/{commit}',
                      40_000_000), stage)
        if (stage / MARKER).read_bytes() != marker:
            raise ValueError('Installer mismatch')
        final = HOME / 'apps' / name / commit
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            shutil.rmtree(final)
        shutil.move(str(stage), final)
    try:
        subprocess.run(['bash', MARKER, 'install'], cwd=final, check=True)
    except BaseException:
        shutil.rmtree(final)
        raise
    state = load_state()
    state[name] = {'commit': commit, 'directory': str(final), 'version': version,
                   'branch': repo['default_branch']}
    save_state(state)
    print('Installed. Open Installed apps to launch it.')


def plain(value):
    # Repository descriptions and error text must never emit terminal escapes.
    return ''.join(c if c.isprintable() and c != '\x1b' else ' ' for c in str(value))


class Terminal:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.color = (self.stream.isatty() and os.environ.get('TERM', '') not in ('', 'dumb')
                      and 'NO_COLOR' not in os.environ)

    @property
    def width(self):
        return max(24, min(76, shutil.get_terminal_size((76, 24)).columns))

    def write(self, value='', code=None):
        text = plain(value)
        for line in textwrap.wrap(text, self.width, replace_whitespace=False) or ['']:
            if self.color and code:
                line = '\x1b[' + code + 'm' + line + '\x1b[0m'
            print(line, file=self.stream)

    def heading(self, title, subtitle=''):
        self.write()
        self.write('-' * self.width, '36')
        self.write(title, '1;36')
        if subtitle:
            self.write(subtitle, '2')
        self.write('-' * self.width, '36')


UI = Terminal()


def choose(title, rows):
    UI.heading(title)
    for index, text in enumerate(rows, 1):
        UI.write(f'  {index:>2}  {text}')
    UI.write('   0  Back', '2')
    while True:
        value = input('Choose a number: ').strip()
        if value == '0':
            return None
        if value.isascii() and value.isdigit() and 1 <= int(value) <= len(rows):
            return int(value) - 1
        UI.write('Choose a listed number, or 0 to go back.', '33')


def installed_directory(item):
    directory = Path(item['directory']).resolve()
    root = (HOME / 'apps').resolve()
    if directory == root or not directory.is_relative_to(root):
        raise ValueError('Invalid installed directory')
    marker = directory / MARKER
    if marker.is_symlink() or not marker.is_file() or not valid_marker(marker.read_bytes()):
        raise ValueError('App files are missing or invalid. Reinstall from GitHub apps.')
    return directory


def installed():
    while True:
        state = load_state()
        names = sorted(state, key=str.casefold)
        tools = [(label, executable) for label, executable in
                 [('Python 3 (system)', 'python3'), ('Ollama (installed models)', 'ollama')]
                 if shutil.which(executable)]
        if not names and not tools:
            UI.heading('RUN APPS', 'Installed through this store')
            UI.write('No apps installed yet. Open GitHub apps to install one.')
            return
        rows = []
        for name in names:
            try:
                installed_directory(state[name])
                status = 'ready'
            except (OSError, ValueError, UnicodeError):
                status = 'missing / reinstall'
            rows.append(f'{name}  [{status}]')
        rows.extend(label for label, _ in tools)
        choice = choose('RUN APPS - installed apps and system tools', rows)
        if choice is None:
            return
        if choice >= len(names):
            run_tool(tools[choice - len(names)][1])
            continue
        name = names[choice]
        try:
            directory = installed_directory(state[name])
            UI.heading('RUNNING ' + name, 'Exit the app to return here. No download needed.')
            result = subprocess.run(['bash', MARKER, 'run'], cwd=directory)
            if result.returncode:
                UI.write(f'{name} exited with code {result.returncode}.', '33')
            else:
                UI.write('Back in the App Store.', '32')
        except KeyboardInterrupt:
            UI.write('App interrupted. Back in the App Store.', '33')
        except (OSError, ValueError, UnicodeError) as exc:
            UI.write('Cannot run ' + name + ': ' + str(exc), '33')



def run_tool(executable):
    try:
        if executable == 'python3':
            UI.write('Python interactive shell. Type exit() or press Ctrl+D to return.')
            subprocess.run(['python3'])
        else:
            result = subprocess.run(['ollama', 'list'], capture_output=True, text=True, timeout=10)
            if result.returncode:
                UI.write('Ollama is not ready. Check that its service is running.', '33')
                return
            models = [line.split()[0] for line in result.stdout.splitlines()[1:] if line.split()]
            if not models:
                UI.write('No local Ollama models. Download a model separately first.')
                return
            choice = choose('OLLAMA - local models', models)
            if choice is not None:
                UI.write('Type /bye to return to the store.')
                subprocess.run(['ollama', 'run', models[choice]])
    except (OSError, subprocess.TimeoutExpired) as exc:
        UI.write('Cannot run system tool: ' + str(exc), '33')
    except KeyboardInterrupt:
        UI.write('Back in the App Store.')


SOFTWARE_SOURCES = {'Python 3': 'python/cpython', 'Ollama': 'ollama/ollama'}
SOFTWARE_ERRORS = []


def check_software_changes():
    """Record latest default-branch edits, not a package-upgrade recommendation."""
    if OFFLINE:
        return
    target = HOME / 'software-changes.json'
    try:
        state = json.loads(target.read_text())
        if not isinstance(state, dict) or not isinstance(state.get('software', {}), dict):
            raise ValueError('Invalid software change record')
    except FileNotFoundError:
        state = {'schema': 1, 'software': {}}
    except (OSError, ValueError) as exc:
        SOFTWARE_ERRORS[:] = ['Cannot read software-changes.json: ' + str(exc)]
        return
    records = state.setdefault('software', {})
    errors = []
    for name, repository in SOFTWARE_SOURCES.items():
        try:
            repo = api('repos/' + repository)
            branch = urllib.parse.quote(repo['default_branch'], safe='')
            row = api('repos/' + repository + '/commits/' + branch)
            sha = row['sha']
            latest = {'commit': sha, 'date': row['commit']['committer']['date'],
                      'summary': plain(row['commit']['message'].splitlines()[0]),
                      'url': row['html_url']}
            old = records.get(name, {})
            history = old.get('history', [])
            if old.get('latest', {}).get('commit') != sha:
                history = (history + [latest])[-20:]
            records[name] = {'repository': repository, 'latest': latest, 'history': history,
                             'checked_at': datetime.now(timezone.utc).isoformat()}
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            errors.append(name + ': ' + str(exc))
    state['last_errors'] = errors
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(state, indent=2) + '\n')
        os.replace(temp, target)
    except OSError as exc:
        errors.append('Cannot save software changes: ' + str(exc))
    SOFTWARE_ERRORS[:] = errors


def show_software_changes():
    UI.heading('OTHER SOFTWARE - UPSTREAM EDITS')
    UI.write('Source edits only. These are not installed-package update checks.')
    try:
        state = json.loads((HOME / 'software-changes.json').read_text())
        for name, row in state.get('software', {}).items():
            item = row['latest']
            UI.write(name + '  ' + item['commit'][:12] + '  ' + item['date'])
            UI.write(item['summary'])
            UI.write('Checked: ' + row['checked_at'])
            UI.write(item['url'])
    except FileNotFoundError:
        UI.write('No recorded checks yet. Internet is needed for the first check.')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        UI.write('Cannot read records: ' + str(exc))
    for error in SOFTWARE_ERRORS:
        UI.write('Check unavailable: ' + error, '33')
    UI.write('Record: ' + str(HOME / 'software-changes.json'))


def other():
    choice = choose('OTHER SOFTWARE', [name for name, _ in SOFTWARE] + ['View recorded upstream edits'])
    if choice is None:
        return
    if choice == len(SOFTWARE):
        show_software_changes()
        return
    if OFFLINE:
        UI.write('Installing software needs internet. Restart without --offline.')
        return
    name, recipe = SOFTWARE[choice]
    prefix = [] if os.geteuid() == 0 else ['sudo']
    if prefix and not shutil.which('sudo'):
        raise ValueError('Run as root or install sudo first')
    if recipe[0] == 'apt':
        print('Will refresh apt and install: ' + ', '.join(recipe[1:]))
        if ask('Install ' + name + '?'):
            subprocess.run(prefix + ['apt-get', 'update'], check=True)
            subprocess.run(prefix + ['apt-get', 'install', '-y'] + recipe[1:], check=True)
    else:
        print('Official installer: ' + recipe[1])
        print('This installs a system service and may download large files.')
        if not shutil.which('wget'):
            raise ValueError('Install wget first')
        if ask('Download the Ollama installer for review?'):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'install.sh'
                subprocess.run(['wget', '-O', str(path), recipe[1]], check=True)
                print(path.read_text())
                print('The upstream installer may use curl internally.')
                if ask('Run this official installer with system privileges?'):
                    subprocess.run(prefix + ['sh', str(path)], check=True)


def check_updates(report=True):
    """Read-only check. Worker threads never write into an active menu."""
    pending, errors = [], []
    if OFFLINE:
        return []
    def self_check():
        repo = api(f'repos/{OWNER}/pi-app-store')
        branch = urllib.parse.quote(repo['default_branch'], safe='')
        latest = api(f'repos/{OWNER}/pi-app-store/commits/{branch}')['sha']
        version = remote_version('pi-app-store', latest)
        if version is not None and version == VERSION:
            return None
        source = fetch(raw('pi-app-store', latest, 'appstore.py'))
        if source != Path(__file__).read_bytes():
            return ('App Store itself' + (' - ' + version if version else ''),
                    'pi-app-store', latest, source)
    def app_check(name, item):
        branch = item.get('branch')
        if not branch:
            branch = api(f'repos/{OWNER}/{name}')['default_branch']
        latest = api(f'repos/{OWNER}/{name}/commits/{urllib.parse.quote(branch, safe="")}')['sha']
        version = remote_version(name, latest)
        if version is None:
            changed = latest != item['commit']
            label = name + ' (legacy commit check)'
        else:
            old = item.get('version')
            if old is None:
                saved_version = installed_directory(item) / VERSION_FILE
                if saved_version.is_file():
                    old = parse_version(saved_version.read_bytes())
            changed = version != old
            label = name + ' - ' + (old or 'unversioned') + ' -> ' + version
        if changed:
            return (label, name, latest, None)
    jobs = [('App Store', self_check, ())]
    try:
        jobs.extend((name, app_check, (name, item)) for name, item in load_state().items()
                    if name != 'pi-app-store')
    except (OSError, ValueError) as exc:
        errors.append('Installed list: ' + str(exc))
    for name, fn, args in jobs:
        try:
            row = fn(*args)
            if row:
                pending.append(row)
        except (OSError, ValueError, IndexError, KeyError, TypeError) as exc:
            errors.append(name + ': ' + str(exc))
    CHECK_ERRORS[:] = errors
    if report:
        report_updates(pending)
    return pending


CHECK_ERRORS = []


def report_updates(pending):
    if OFFLINE:
        UI.write('Offline mode. Installed apps are available; updates need internet.')
        return
    for error in CHECK_ERRORS:
        UI.write('Update check unavailable: ' + error, '33')
    if pending:
        UI.write('Updates available: ' + ', '.join(row[0] for row in pending), '33')
        UI.write('Choose Updates to review. Nothing changes automatically.')
    elif not CHECK_ERRORS:
        UI.write('All completed update checks are current.', '32')



def updates(pending):
    if not pending:
        return
    if not pending:
        return
    choice = choose('Updates', [row[0] for row in pending])
    if choice is None:
        return
    label, name, commit, source = pending[choice]
    if source is not None:
        print('Update source: ' + raw(name, commit, 'appstore.py'))
        print('This replaces the App Store program. Restart with AppStore afterward.')
        if not ask('Trust this repository and update App Store?'):
            return
        compile(source, 'appstore.py', 'exec')
        target = Path(__file__).resolve()
        tmp = target.with_suffix('.update.tmp')
        tmp.write_bytes(source)
        os.replace(tmp, target)
        print('App Store updated. Quit and run AppStore again.')
        pending.pop(choice)
    else:
        repo = api(f'repos/{OWNER}/{name}')
        install(repo, selected_commit=commit)
        if load_state().get(name, {}).get('commit') == commit:
            pending.pop(choice)


def main(argv=None):
    global OFFLINE, UI
    parser = argparse.ArgumentParser(description='Pi App Store - install and run your GitHub apps')
    parser.add_argument('--offline', action='store_true', help='run installed apps without network checks')
    parser.add_argument('--no-color', action='store_true', help='disable terminal colors')
    parser.add_argument('--version', action='version', version='Pi App Store ' + VERSION)
    args = parser.parse_args(argv)
    OFFLINE = args.offline
    UI = Terminal()
    if args.no_color:
        UI.color = False
    pending = []
    # Daemon worker lets Run apps and Quit work immediately, even without internet.
    done = threading.Event()
    def background_check():
        try:
            pending.extend(check_updates(report=False))
            check_software_changes()
        finally:
            done.set()
    if OFFLINE:
        done.set()
    else:
        threading.Thread(target=background_check, daemon=True).start()
    while True:
        UI.heading('PI APP STORE  /  ' + VERSION, 'Your GitHub apps. One place to install and run.')
        if OFFLINE:
            UI.write('OFFLINE  -  installed apps still work', '33')
        elif not done.is_set():
            UI.write('Checking updates in the background...', '2')
        elif CHECK_ERRORS:
            UI.write('Some update checks failed. Open Updates for details.', '33')
        else:
            UI.write(f'{len(pending)} update(s) available. Nothing changes automatically.', '2')
        UI.write()
        for line in ('  1  GitHub apps     Browse and install',
                     '  2  Run apps        Launch installed apps',
                     '  3  Other software  Python, Ollama',
                     '  4  Updates         Review available updates',
                     '  0  Quit'):
            UI.write(line)
        UI.write()
        try:
            choice = input('Choose a number: ').strip()
            if choice == '0':
                UI.write('Goodbye.')
                return
            if choice == '1':
                if OFFLINE:
                    UI.write('Browsing needs internet. Restart without --offline.')
                    continue
                UI.write('Checking opt-in repositories...')
                apps = discover()
                if not apps:
                    UI.write('No marked apps found. Each app needs app-store.sh.')
                    continue
                if any(r.get('category') == 'games' for r in apps):
                    kind = choose('BROWSE', ['Apps', 'Games'])
                    if kind is None:
                        continue
                    apps = [r for r in apps if (r.get('category') == 'games') == (kind == 1)]
                    if not apps:
                        UI.write('Nothing in that folder yet.')
                        continue
                    title = 'GAMES' if kind == 1 else 'GITHUB APPS'
                else:
                    title = 'GITHUB APPS'
                selected = choose(title, [r['name'] + ' - ' + (r.get('description') or '') for r in apps])
                if selected is not None:
                    install(apps[selected])
            elif choice == '2':
                installed()
            elif choice == '3':
                other()
            elif choice == '4':
                if not done.is_set():
                    UI.write('Checks are still running. Run apps is available now.')
                    continue
                report_updates(pending)
                if not OFFLINE:
                    updates(pending)
            else:
                UI.write('Choose 0, 1, 2, 3 or 4.', '33')
        except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as exc:
            UI.write('Could not finish: ' + str(exc), '33')
        except (EOFError, KeyboardInterrupt):
            UI.write('Goodbye.')
            return


if __name__ == '__main__':
    main()
