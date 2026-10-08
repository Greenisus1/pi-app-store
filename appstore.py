#!/usr/bin/env python3
"""Small, opt-in GitHub app store for Debian-based Raspberry Pi systems."""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path, PurePosixPath
import queue
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
VERSION = '1.4.1'
VERSION_FILE = 'app-version.json'
OFFLINE = False
NETWORK_TIMEOUT = 5
HOME = Path.home() / '.local' / 'share' / 'pi-app-store'
# Add another apt entry here: ('Display name', ['apt', 'package', ...]).
SOFTWARE = [('Python 3', ['apt', 'python3', 'python3-pip', 'python3-venv']),
            ('Ollama', ['script', 'https://ollama.com/install.sh']),
            ('Python Tk (python3-tk)', ['apt', 'python3-tk'])]


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


def install(repo, selected_commit=None, confirm=None):
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
    if not (confirm(marker.decode()) if confirm else ask('Trust this installer and install?')):
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


def software_status(name):
    """Honest local status. Only checks whether the tool is present, not its version."""
    if name.startswith('Python Tk'):
        import importlib.util
        return 'installed' if importlib.util.find_spec('_tkinter') else 'missing'
    executable = {'Python 3': 'python3', 'Ollama': 'ollama'}.get(name)
    if executable:
        return 'installed' if shutil.which(executable) else 'missing'
    return 'unknown'


def install_software(name, recipe, confirm):
    prefix = [] if os.geteuid() == 0 else ['sudo']
    if prefix and not shutil.which('sudo'):
        raise ValueError('Run as root or install sudo first')
    if recipe[0] == 'apt':
        message = 'Will refresh apt and install: ' + ', '.join(recipe[1:])
        print(message)
        if confirm(message, 'Install ' + name + '?'):
            subprocess.run(prefix + ['apt-get', 'update'], check=True)
            subprocess.run(prefix + ['apt-get', 'install', '-y'] + recipe[1:], check=True)
            return True
    else:
        print('Official installer: ' + recipe[1])
        print('This installs a system service and may download large files.')
        if not shutil.which('wget'):
            raise ValueError('Install wget first')
        if confirm('Official installer: ' + recipe[1] + '\nThis installs a system service and may download large files.',
                   'Download the Ollama installer for review?'):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'install.sh'
                subprocess.run(['wget', '-O', str(path), recipe[1]], check=True)
                text = path.read_text()
                print(text)
                print('The upstream installer may use curl internally.')
                if confirm(text + '\nThe upstream installer may use curl internally.',
                           'Run this official installer with system privileges?'):
                    subprocess.run(prefix + ['sh', str(path)], check=True)
                    return True
    return False


def other():
    choice = choose('OTHER SOFTWARE', [f'{name}  [{software_status(name)}]' for name, _ in SOFTWARE]
                    + ['View recorded upstream edits'])
    if choice is None:
        return
    if choice == len(SOFTWARE):
        show_software_changes()
        return
    if OFFLINE:
        UI.write('Installing software needs internet. Restart without --offline.')
        return
    name, recipe = SOFTWARE[choice]
    install_software(name, recipe, lambda text, question: ask(question))


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


def build_rows(view, apps, state, pending, software=None):
    """Pure helper for the window: list rows for one section. No network, no Tk."""
    waiting = {row[1] for row in pending}
    rows = []
    if view in ('apps', 'games'):
        for repo in apps:
            games = repo.get('category') == 'games'
            if games != (view == 'games'):
                continue
            name = repo['name']
            item = state.get(name)
            if name in waiting:
                status = 'update available'
            elif item:
                status = 'installed ' + (item.get('version') or '')
            else:
                status = 'not installed'
            rows.append({'name': name, 'status': status.strip(), 'desc': plain(repo.get('description') or ''),
                         'repo': repo, 'installed': bool(item)})
    elif view == 'installed':
        for name in sorted(state, key=str.casefold):
            item = state[name]
            try:
                installed_directory(item)
                status = 'ready' + (' - update available' if name in waiting else '')
                ok = True
            except (OSError, ValueError, UnicodeError):
                status, ok = 'missing - reinstall', False
            rows.append({'name': name, 'status': status, 'desc': 'version ' + (item.get('version') or 'legacy'),
                         'repo': None, 'installed': ok})
    elif view == 'updates':
        for label, name, commit, source in pending:
            rows.append({'name': label, 'status': 'update available', 'desc': 'commit ' + commit[:12],
                         'repo': None, 'installed': True, 'pending': (label, name, commit, source)})
    elif view == 'other':
        for name, recipe in SOFTWARE:
            rows.append({'name': name, 'status': software_status(name),
                         'desc': 'apt: ' + ' '.join(recipe[1:]) if recipe[0] == 'apt' else 'official installer, reviewed first',
                         'repo': None, 'installed': False, 'software': (name, recipe)})
        for name, row in (software or {}).items():
            latest = row.get('latest', {})
            rows.append({'name': name + ' (upstream edits)', 'status': 'source edit ' + latest.get('commit', '')[:10],
                         'desc': latest.get('summary', ''), 'repo': None, 'installed': False})
    return rows


def terminal_command(directory):
    """Terminal emulator command for apps that need a keyboard window, or None."""
    script = 'bash ' + MARKER + ' run; echo; read -r -p "Press Enter to close" _'
    for exe, flag in (('x-terminal-emulator', '-e'), ('lxterminal', '-e'), ('xterm', '-e'),
                      ('xfce4-terminal', '-x'), ('mate-terminal', '-x'), ('gnome-terminal', '--')):
        path = shutil.which(exe)
        if path:
            return [path, flag, 'bash', '-c', script]
    return None


def apply_update(row, confirm):
    label, name, commit, source = row
    if source is not None:
        if not confirm('Replace the App Store program with the version from ' + raw(name, commit, 'appstore.py') + '?'):
            return False
        compile(source, 'appstore.py', 'exec')
        target = Path(__file__).resolve()
        tmp = target.with_suffix('.update.tmp')
        tmp.write_bytes(source)
        os.replace(tmp, target)
        return True
    install(api(f'repos/{OWNER}/{name}'), selected_commit=commit, confirm=confirm)
    return load_state().get(name, {}).get('commit') == commit


def gui():
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print('The window needs Tk. On DietPi run: apt-get install -y python3-tk')
        print('It also needs a desktop or VNC. The terminal menu still works: AppStore')
        return 1
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print('No desktop display found (' + str(exc) + '). Use a desktop or VNC, or run AppStore for the terminal menu.')
        return 1
    root.title('Pi App Store ' + VERSION)
    root.geometry('900x560')
    root.minsize(760, 440)
    BG, SIDE, SIDE_TXT, ACCENT = '#f4f5f7', '#23272e', '#d7dae0', '#3b82f6'
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except tk.TclError:
        pass
    style.configure('Treeview', rowheight=28, font=('TkDefaultFont', 10), background='white', fieldbackground='white', borderwidth=0)
    style.configure('Treeview.Heading', font=('TkDefaultFont', 10, 'bold'), background='#e6e8ec', relief='flat')
    style.map('Treeview', background=[('selected', ACCENT)], foreground=[('selected', 'white')])
    style.configure('Accent.TButton', background=ACCENT, foreground='white', padding=(14, 6))
    style.map('Accent.TButton', background=[('active', '#2f6fd0'), ('disabled', '#a9b8cf')])
    style.configure('TButton', padding=(12, 6))

    data = {'apps': [], 'pending': [], 'view': 'apps', 'rows': [], 'loaded': False, 'busy': False}
    jobs = queue.Queue()

    def call_main(fn):
        box = {}
        done = threading.Event()
        def run():
            box['value'] = fn()
            done.set()
        jobs.put(run)
        done.wait()
        return box.get('value')

    def pump():
        while True:
            try:
                jobs.get_nowait()()
            except queue.Empty:
                break
        root.after(100, pump)

    def confirm(text):
        def ask_user():
            return confirm_dialog('Review before continuing', text)
        return call_main(ask_user)

    def confirm_dialog(title, text):
        win = tk.Toplevel(root)
        win.title(title)
        win.transient(root)
        win.geometry('620x380')
        answer = {'ok': False}
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Trust this and continue? It can run commands with your account.',
                  wraplength=580).pack(anchor='w')
        box = tk.Text(frame, height=12, wrap='word', font=('TkFixedFont', 9), bg='white')
        box.insert('1.0', plain_text(text))
        box.configure(state='disabled')
        box.pack(fill='both', expand=True, pady=8)
        buttons = ttk.Frame(frame)
        buttons.pack(anchor='e')
        def choose_(value):
            answer['ok'] = value
            win.destroy()
        ttk.Button(buttons, text='Cancel', command=lambda: choose_(False)).pack(side='left', padx=6)
        ttk.Button(buttons, text='Continue', style='Accent.TButton', command=lambda: choose_(True)).pack(side='left')
        win.protocol('WM_DELETE_WINDOW', lambda: choose_(False))
        win.grab_set()
        root.wait_window(win)
        return answer['ok']

    def plain_text(text):
        return ''.join(c if c.isprintable() or c in '\n\t' else ' ' for c in str(text))

    # Layout: sidebar | (path bar, list, details) | status bar
    side = tk.Frame(root, bg=SIDE, width=190)
    side.pack(side='left', fill='y')
    side.pack_propagate(False)
    tk.Label(side, text='Pi App Store', bg=SIDE, fg='white', font=('TkDefaultFont', 13, 'bold'),
             anchor='w', padx=16, pady=16).pack(fill='x')
    main_area = tk.Frame(root, bg=BG)
    main_area.pack(side='left', fill='both', expand=True)
    head = tk.Frame(main_area, bg=BG)
    head.pack(fill='x', padx=14, pady=(12, 0))
    path_label = tk.Label(head, text='', bg=BG, fg='#222', font=('TkDefaultFont', 12, 'bold'), anchor='w')
    path_label.pack(side='left')
    top = tk.Frame(main_area, bg=BG)
    top.pack(fill='x', padx=14, pady=(6, 6))
    ttk.Button(top, text='Refresh', command=lambda: show(data['view'], reload=True)).pack(side='right')
    tk.Label(top, text='Search', bg=BG, fg='#666').pack(side='left')
    search = tk.StringVar()
    entry = ttk.Entry(top, textvariable=search)
    entry.pack(side='left', fill='x', expand=True, padx=8)

    columns = ('status', 'desc')
    tree = ttk.Treeview(main_area, columns=columns, selectmode='browse')
    tree.heading('#0', text='Name', anchor='w')
    tree.heading('status', text='Status', anchor='w')
    tree.heading('desc', text='Description', anchor='w')
    tree.column('#0', width=190, stretch=False)
    tree.column('status', width=140, stretch=False)
    tree.column('desc', width=360)
    details = tk.Label(main_area, text='Pick something from the list.', bg=BG, fg='#444', anchor='w',
                       justify='left', wraplength=620, padx=14, pady=8)
    details.pack(fill='x')
    bar = tk.Frame(main_area, bg=BG)
    bar.pack(fill='x', padx=14, pady=(0, 8))
    btn = {}
    for key, text, style_name in (('install', 'Install', 'Accent.TButton'), ('run', 'Run', 'Accent.TButton'),
                                  ('term', 'Run in terminal', 'TButton'), ('update', 'Update', 'Accent.TButton')):
        btn[key] = ttk.Button(bar, text=text, style=style_name, state='disabled')
        btn[key].pack(side='left', padx=(0, 8))
    status = tk.Label(root, text='', bg='#e6e8ec', fg='#333', anchor='w', padx=10)
    status.pack(side='bottom', fill='x', before=side)
    bar.pack_forget()
    details.pack_forget()
    bar.pack(side='bottom', fill='x', padx=14, pady=(0, 8))
    details.pack(side='bottom', fill='x')
    tree.pack(fill='both', expand=True, padx=14)

    def say(text):
        status.config(text=text)

    def selected():
        picked = tree.selection()
        return data['rows'][int(picked[0])] if picked else None

    def update_buttons(event=None):
        row = selected()
        for button in btn.values():
            button.state(['disabled'])
        if not row:
            details.config(text='Pick something from the list.')
            return
        details.config(text=row['name'] + '\n' + row['status'] + (' - ' + row['desc'] if row['desc'] else ''))
        view = data['view']
        if view in ('apps', 'games') and not OFFLINE:
            btn['install'].state(['!disabled'])
        if view == 'other' and row.get('software') and not OFFLINE:
            btn['install'].state(['!disabled'])
        if row['installed'] and view in ('apps', 'games', 'installed') and row['name'] in load_state():
            btn['run'].state(['!disabled'])
            if terminal_command(Path('.')):
                btn['term'].state(['!disabled'])
        if view == 'updates' or 'update available' in row['status']:
            btn['update'].state(['!disabled'])

    def fill():
        tree.delete(*tree.get_children())
        needle = search.get().strip().lower()
        software = {}
        if data['view'] == 'other':
            try:
                software = json.loads((HOME / 'software-changes.json').read_text()).get('software', {})
            except (OSError, ValueError):
                software = {}
        rows = [r for r in build_rows(data['view'], data['apps'], load_state(), data['pending'], software)
                if needle in (r['name'] + ' ' + r['desc']).lower()]
        data['rows'] = rows
        for index, row in enumerate(rows):
            tree.insert('', 'end', iid=str(index), text='  ' + row['name'], values=(row['status'], row['desc']))
        if not rows:
            empty = {'apps': 'No apps found yet.', 'games': 'No games yet.', 'installed': 'Nothing installed yet.',
                     'updates': 'No updates waiting.', 'other': 'No recorded checks yet.'}[data['view']]
            tree.insert('', 'end', iid='empty', text='  ' + empty)
        update_buttons()

    def background(work, finish, message):
        if data['busy']:
            say('Still working, please wait.')
            return
        data['busy'] = True
        say(message)
        def target():
            try:
                result, error = work(), None
            except Exception as exc:  # worker must always report back
                result, error = None, str(exc)
            jobs.put(lambda: finish(result, error))
        threading.Thread(target=target, daemon=True).start()

    def done_with(message):
        data['busy'] = False
        say(message)

    TITLES = {'apps': 'Apps', 'games': 'Games', 'installed': 'Run apps', 'other': 'Other software',
              'updates': 'Updates'}

    def show(view, reload=False):
        data['view'] = view
        path_label.config(text='Pi App Store  >  ' + TITLES[view])
        for key, button in nav.items():
            button.config(bg=ACCENT if key == view else SIDE)
        needs_net = view in ('apps', 'games') and (reload or not data['loaded']) and not OFFLINE
        if needs_net:
            def finish(result, error):
                if error:
                    done_with('Could not reach GitHub: ' + error)
                else:
                    data['apps'], data['loaded'] = result, True
                    done_with(f'{len(result)} app(s) found.')
                fill()
            fill()
            background(discover, finish, 'Looking for apps...')
        else:
            fill()
            if view in ('apps', 'games') and OFFLINE:
                say('Offline: browsing needs internet. Run apps still works.')

    nav = {}
    for key in ('apps', 'games', 'installed', 'updates', 'other'):
        button = tk.Button(side, text='   ' + TITLES[key], anchor='w', bg=SIDE, fg=SIDE_TXT, activebackground='#3a3f48',
                           activeforeground='white', relief='flat', bd=0, padx=10, pady=9, font=('TkDefaultFont', 10),
                           command=lambda k=key: show(k))
        button.pack(fill='x')
        nav[key] = button

    def do_install():
        row = selected()
        if row and row.get('software'):
            name, recipe = row['software']
            def work_software():
                return install_software(name, recipe, lambda text, question: confirm(text + '\n\n' + question))
            def finish_software(result, error):
                done_with(('Install stopped: ' + error) if error else
                          ('Installed ' + name if result else 'Cancelled.'))
                fill()
            background(work_software, finish_software, 'Installing ' + name + '... (progress is in the terminal that opened the store)')
            return
        if not row or not row.get('repo'):
            return
        def work():
            install(row['repo'], confirm=confirm)
        def finish(result, error):
            done_with(('Install stopped: ' + error) if error else 'Install finished (or cancelled). Check Run apps.')
            fill()
        background(work, finish, 'Installing ' + row['name'] + '... (installer output is in the terminal window that opened the store)')

    def do_run(in_terminal=False):
        row = selected()
        if not row:
            return
        try:
            directory = installed_directory(load_state()[row['name']])
            if in_terminal:
                subprocess.Popen(terminal_command(directory), cwd=directory)
            else:
                subprocess.Popen(['bash', MARKER, 'run'], cwd=directory, stdin=subprocess.DEVNULL)
            say('Started ' + row['name'] + '. Keyboard apps work best with Run in terminal.')
        except (OSError, ValueError, KeyError, UnicodeError) as exc:
            say('Cannot run ' + row['name'] + ': ' + str(exc))

    def do_update():
        row = selected()
        if not row:
            return
        pend = row.get('pending') or next((p for p in data['pending'] if p[1] == row['name']), None)
        if not pend:
            return
        def finish(result, error):
            if error:
                done_with('Update stopped: ' + error)
            elif result:
                data['pending'] = [p for p in data['pending'] if p[1] != pend[1]]
                done_with('Updated. ' + ('Restart the App Store to use the new version.' if pend[3] is not None else ''))
            else:
                done_with('Update cancelled.')
            fill()
        background(lambda: apply_update(pend, confirm), finish, 'Updating...')

    btn['install'].config(command=do_install)
    btn['run'].config(command=do_run)
    btn['term'].config(command=lambda: do_run(True))
    btn['update'].config(command=do_update)
    tree.bind('<<TreeviewSelect>>', update_buttons)
    tree.bind('<Double-1>', lambda e: (btn['run'].invoke() if str(btn['run'].cget('state')) != 'disabled'
                                       else btn['install'].invoke() if str(btn['install'].cget('state')) != 'disabled' else None))
    search.trace_add('write', lambda *a: fill())

    def start_checks():
        def finish(result, error):
            if not error:
                data['pending'] = result
            data['busy'] = False
            say(f'{len(data["pending"])} update(s) available.' if not error else 'Update check failed: ' + error)
            fill()
        if not OFFLINE:
            data['busy'] = False
            background(lambda: (check_updates(report=False), check_software_changes())[0], finish, 'Checking updates...')

    pump()
    show('apps')
    if not OFFLINE:
        root.after(800, start_checks)
    root.mainloop()
    return 0


SORTS = [('newest', 'Newest first'), ('az', 'A-Z'), ('za', 'Z-A')]


def sort_apps(rows, mode):
    """Pure helper: order app rows. Newest uses the repo's last push, then creation date."""
    if mode == 'az':
        return sorted(rows, key=lambda r: r['name'].casefold())
    if mode == 'za':
        return sorted(rows, key=lambda r: r['name'].casefold(), reverse=True)
    by_name = sorted(rows, key=lambda r: r['name'].casefold())
    return sorted(by_name, key=lambda r: ((r.get('repo') or {}).get('pushed_at') or (r.get('repo') or {}).get('created_at') or ''), reverse=True)


SECTIONS = [('apps', 'Apps'), ('games', 'Games'), ('installed', 'Run apps'),
            ('updates', 'Updates'), ('other', 'Other software')]


def read_software_records():
    try:
        return json.loads((HOME / 'software-changes.json').read_text()).get('software', {})
    except (OSError, ValueError, AttributeError):
        return {}


def ellipsize(text, width):
    text = plain(text)
    if width <= 0:
        return ''
    return text if len(text) <= width else text[:max(0, width - 1)] + '\u2026'


def use_rich(plain_flag, env, stdin_tty, stdout_tty):
    """Rich keyboard view is the default only on a real, capable terminal."""
    if plain_flag or env.get('APPSTORE_PLAIN') or not (stdin_tty and stdout_tty):
        return False
    return env.get('TERM', '') not in ('', 'dumb', 'unknown')


def tui(no_color=False):
    os.environ.setdefault('ESCDELAY', '25')
    import curses
    import locale
    try:
        locale.setlocale(locale.LC_ALL, '')
    except locale.Error:
        pass
    utf8 = 'utf' in (locale.getpreferredencoding(False) or '').lower()
    BLOCK, DOT, HALF, UP, DOWN = ('\u2588', '\u25cf', '\u258c', '\u25b2', '\u25bc') if utf8 else ('#', '*', '>', '^', 'v')
    H, V = ('\u2500', '\u2502') if utf8 else ('-', '|')
    TLR, TRR, BLR, BRR = ('\u256d', '\u256e', '\u2570', '\u256f') if utf8 else ('+', '+', '+', '+')
    data = {'apps': [], 'pending': [], 'loaded': False, 'busy': None, 'rows': [], 'software': {}}
    jobs = queue.Queue()
    ui = {'view': 0, 'sel': 0, 'top': 0, 'search': '', 'typing': False, 'msg': '', 'help': False, 'sort': 0}

    def run(stdscr):
        colors = curses.has_colors() and not no_color and 'NO_COLOR' not in os.environ
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.keypad(True)
        stdscr.timeout(120)
        attr = {}
        if colors:
            curses.start_color()
            try:
                curses.use_default_colors()
            except curses.error:
                pass
            pairs = {'head': (curses.COLOR_WHITE, curses.COLOR_BLUE), 'sel': (curses.COLOR_BLACK, curses.COLOR_CYAN),
                     'ok': (curses.COLOR_GREEN, -1), 'warn': (curses.COLOR_YELLOW, -1), 'bad': (curses.COLOR_RED, -1),
                     'foot': (curses.COLOR_BLACK, curses.COLOR_WHITE), 'key': (curses.COLOR_YELLOW, curses.COLOR_BLUE),
                     'apps': (curses.COLOR_CYAN, -1), 'games': (curses.COLOR_MAGENTA, -1),
                     'installed': (curses.COLOR_GREEN, -1), 'updates': (curses.COLOR_YELLOW, -1),
                     'other': (curses.COLOR_BLUE, -1), 'side': (curses.COLOR_WHITE, curses.COLOR_BLACK),
                     'footkey': (curses.COLOR_WHITE, curses.COLOR_BLUE), 'chip': (curses.COLOR_BLACK, curses.COLOR_YELLOW),
                     'pop': (curses.COLOR_WHITE, curses.COLOR_BLUE), 'headdim': (curses.COLOR_WHITE, curses.COLOR_BLUE),
                     'logo0': (curses.COLOR_CYAN, curses.COLOR_BLUE), 'logo1': (curses.COLOR_MAGENTA, curses.COLOR_BLUE),
                     'logo2': (curses.COLOR_GREEN, curses.COLOR_BLUE), 'logo3': (curses.COLOR_YELLOW, curses.COLOR_BLUE)}
            for number, (name, (fg, bg)) in enumerate(pairs.items(), 1):
                try:
                    curses.init_pair(number, fg, bg)
                    attr[name] = curses.color_pair(number)
                except curses.error:
                    attr[name] = 0
            attr['head'] |= curses.A_BOLD
            attr['sel'] |= curses.A_BOLD
        else:
            for name in ('head', 'sel', 'foot', 'key', 'chip', 'footkey', 'headdim'):
                attr[name] = curses.A_REVERSE
            for name in ('logo0', 'logo1', 'logo2', 'logo3'):
                attr[name] = curses.A_REVERSE | curses.A_BOLD
            attr['pop'] = curses.A_REVERSE
            for name in ('ok', 'warn', 'bad', 'apps', 'games', 'installed', 'updates', 'other', 'side'):
                attr[name] = curses.A_BOLD if name in ('ok', 'warn', 'bad') else 0
        dim = curses.A_DIM

        def put(y, x, text, a=0):
            height, width = stdscr.getmaxyx()
            if y < 0 or y >= height or x >= width:
                return
            text = plain(text)[:max(0, width - x - (1 if y == height - 1 else 0))]
            try:
                stdscr.addstr(y, x, text, a)
            except curses.error:
                pass

        def fill_row(y, a):
            put(y, 0, ' ' * (stdscr.getmaxyx()[1] - (1 if y == stdscr.getmaxyx()[0] - 1 else 0)), a)

        def rows():
            key = SECTIONS[ui['view']][0]
            needle = ui['search'].strip().lower()
            found = build_rows(key, data['apps'], load_state(), data['pending'],
                               data['software'] if key == 'other' else None)
            found = [r for r in found if needle in (r['name'] + ' ' + r['desc']).lower()]
            if key in ('apps', 'games'):
                found = sort_apps(found, SORTS[ui['sort']][0])
            return found

        def badge(status):
            if 'update' in status:
                return attr['warn']
            if status.startswith(('installed', 'ready')):
                return attr['ok']
            if 'missing' in status:
                return attr['bad']
            return dim

        spin = '|/-\\'
        if utf8:
            spin = '\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f'
        tick = [0]

        def chips(y, x, items, key_attr, label_attr, gap=2):
            for key_text, label in items:
                put(y, x, ' ' + key_text + ' ', key_attr)
                put(y, x + len(key_text) + 2, ' ' + label, label_attr)
                x += len(key_text) + len(label) + 3 + gap

        def counts():
            state = load_state()
            apps_n = sum(1 for r in data['apps'] if r.get('category') != 'games')
            games_n = sum(1 for r in data['apps'] if r.get('category') == 'games')
            return {'apps': apps_n if data['loaded'] else None, 'games': games_n if data['loaded'] else None,
                    'installed': len(state), 'updates': len(data['pending']), 'other': len(SOFTWARE)}

        def draw():
            height, width = stdscr.getmaxyx()
            stdscr.erase()
            tick[0] += 1
            if height < 10 or width < 40:
                put(0, 0, 'Too small.', 0)
                put(1, 0, 'Try: appstore --plain', 0)
                stdscr.refresh()
                return
            key, title = SECTIONS[ui['view']]
            # Title bar with a strip of color blocks
            fill_row(0, attr['head'])
            for n, name in enumerate(('apps', 'games', 'installed', 'updates')):
                put(0, 2 + n * 2, BLOCK * 2, attr['logo' + str(n)])
            put(0, 11, 'PI APP STORE', attr['head'])
            put(0, 24, 'v' + VERSION, attr['headdim'])
            if OFFLINE:
                tag = 'OFFLINE'
            elif data['busy']:
                tag = spin[(tick[0] // 1) % len(spin)] + ' ' + data['busy']
            else:
                tag = DOT + ' online'
            put(0, max(26, width - len(tag) - 2), tag, attr['head'])
            wide = width >= 72
            left = 24 if wide else 0
            found = rows()
            data['rows'] = found
            ui['sel'] = max(0, min(ui['sel'], len(found) - 1))
            number = counts()
            if wide:
                put(2, 3, 'BROWSE', dim | curses.A_BOLD)
                for index, (k, name) in enumerate(SECTIONS):
                    y = 4 + index * 2
                    selected = index == ui['view']
                    if selected:
                        fill_row_part(y, 1, left - 3, attr['sel'])
                        put(y, 0, HALF, attr[k] | curses.A_BOLD)
                    else:
                        put(y, 1, BLOCK, attr[k])
                    put(y, 3, name, attr['sel'] if selected else 0)
                    n = number[k]
                    if n:
                        badge_text = str(n)
                        put(y, left - 4 - len(badge_text), badge_text,
                            attr['sel'] if selected else (attr['warn'] if k == 'updates' else dim))
                if height >= 24:
                    put(height - 4, 3, 'Tab: next section', dim)
                    put(height - 3, 3, '? for help', dim)
                for y in range(1, height - 2):
                    put(y, left - 1, V, dim)
                x0 = left + 1
                head_y = 2
            else:
                x = 1
                for index, (k, name) in enumerate(SECTIONS):
                    label = ' ' + name.split()[0] + ' '
                    put(1, x, label, attr['sel'] if index == ui['view'] else attr[k])
                    x += len(label) + 1
                x0 = 1
                head_y = 2
            span = width - x0 - 1
            put(head_y, x0 + 1, title.upper(), curses.A_BOLD)
            total = f'{len(found)}' if found else ''
            put(head_y, x0 + 2 + len(title), total, dim)
            sort_label = 'Sort: ' + SORTS[ui['sort']][1] + ' (s)' if key in ('apps', 'games') else ''
            hint = ('/ ' + ui['search'] + ('_' if ui['typing'] else '')) if (ui['search'] or ui['typing']) else 'press / to search'
            if sort_label:
                put(head_y, x0 + len(title) + len(total) + 5, sort_label, attr['warn'])
            put(head_y, max(x0 + len(title) + len(total) + 7 + len(sort_label), width - len(hint) - 2), hint, attr['warn'] if ui['typing'] or ui['search'] else dim)
            put(head_y + 1, x0 + 1, H * max(0, span - 2), dim)
            col_y = head_y + 2
            name_w = max(14, min(30, span // 3))
            stat_w = max(12, min(20, span // 4))
            put(col_y, x0 + 3, 'NAME'.ljust(name_w + 2) + 'STATUS'.ljust(stat_w + 2) + 'DESCRIPTION', dim | curses.A_BOLD)
            body_top = col_y + 1
            cur0 = found[ui['sel']] if found else None
            wanted = len(textwrap.wrap(plain(cur0['desc'] or 'No description.'), max(10, span - 6)) or ['']) if cur0 else 1
            cap = 6 if height >= 36 else 4 if height >= 30 else 3 if height >= 26 else 2 if height >= 24 else 1
            desc_lines = min(wanted, cap)
            panel_h = 4 + desc_lines
            if ui.get('ph') != panel_h:
                ui['ph'] = panel_h
                stdscr.clearok(True)
            body_h = height - body_top - panel_h - 2
            if ui['sel'] < ui['top']:
                ui['top'] = ui['sel']
            if ui['sel'] >= ui['top'] + body_h:
                ui['top'] = max(0, ui['sel'] - body_h + 1)
            if not found:
                empty = {'apps': 'No apps found yet.', 'games': 'No games yet.', 'installed': 'Nothing installed yet.',
                         'updates': 'Everything is up to date.', 'other': 'No recorded checks yet.'}[key]
                tip = {'apps': 'Press F5 to look again.', 'games': 'New games appear here automatically.',
                       'installed': 'Open Apps or Games and press Enter on one.', 'updates': 'Updates show up here.',
                       'other': 'Needs internet for the first check.'}[key]
                if data['busy'] and key in ('apps', 'games'):
                    empty, tip = 'Looking for apps...', 'Checking GitHub.'
                put(body_top + 1, x0 + 3, empty, curses.A_BOLD)
                put(body_top + 2, x0 + 3, tip, dim)
            for line in range(max(0, body_h)):
                index = ui['top'] + line
                if index >= len(found):
                    break
                row = found[index]
                y = body_top + line
                selected = index == ui['sel']
                if selected:
                    fill_row_part(y, x0, width - 2, attr['sel'])
                    put(y, x0, HALF, attr[key] | curses.A_BOLD)
                base = attr['sel'] if selected else 0
                put(y, x0 + 2, ellipsize(row['name'], name_w).ljust(name_w), base | (curses.A_BOLD if selected else 0))
                dot = DOT + ' ' + ellipsize(row['status'], stat_w - 2)
                put(y, x0 + name_w + 4, dot.ljust(stat_w), base if selected else badge(row['status']))
                put(y, x0 + name_w + stat_w + 6, ellipsize(row['desc'], span - name_w - stat_w - 8), base if selected else dim)
            if body_h > 0 and ui['top'] > 0:
                put(body_top, width - 2, UP, dim)
            if body_h > 0 and ui['top'] + body_h < len(found):
                put(body_top + body_h - 1, width - 2, DOWN, dim)
            # Detail panel with rounded corners and a title
            box_y = height - panel_h - 2
            cur = found[ui['sel']] if found else None
            label = ' ' + ellipsize(cur['name'], span - 8) + ' ' if cur else ' Details '
            put(box_y, x0 + 1, TLR + H + label + H * max(0, span - 4 - len(label)) + TRR, dim)
            put(box_y, x0 + 3, label, curses.A_BOLD)
            for yy in range(box_y + 1, box_y + panel_h - 1):
                put(yy, x0 + 1, V, dim)
                put(yy, x0 + span - 1, V, dim)
            put(box_y + panel_h - 1, x0 + 1, BLR + H * max(0, span - 3) + BRR, dim)
            if cur:
                inner = span - 6
                put(box_y + 1, x0 + 3, DOT + ' ' + ellipsize(cur['status'], inner - 2), badge(cur['status']) | curses.A_BOLD)
                text_rows = textwrap.wrap(plain(cur['desc'] or 'No description.'), max(10, inner)) or ['']
                if cap:
                    for n, part in enumerate(text_rows[:desc_lines]):
                        last = n == desc_lines - 1 and len(text_rows) > desc_lines
                        put(box_y + 2 + n, x0 + 3, ellipsize(part + ' ...' if last else part, inner), 0)
                    action_y = box_y + 2 + desc_lines
                else:
                    action_y = box_y + 2
                installed_now = cur['name'] in load_state()
                if key == 'updates':
                    acts = [('Enter', 'Update')]
                elif key == 'other':
                    acts = [('Enter', 'Install')]
                elif installed_now:
                    acts = [('Enter', 'Run')] + ([('u', 'Update')] if 'update' in cur['status'] else [])
                else:
                    acts = [('Enter', 'Install')]
                chips(action_y, x0 + 3, acts, attr['chip'], 0)
            put(height - 2, 1, (' ' + ellipsize(ui['msg'], width - 4)) if ui['msg'] else ' ', attr['warn'] if ui['msg'] else dim)
            fill_row(height - 1, attr['foot'])
            full = [('\u2191\u2193' if utf8 else 'Up/Dn', 'move'), ('\u2190\u2192' if utf8 else 'Lt/Rt', 'section'),
                    ('Enter', 'open'), ('i', 'install'), ('r', 'run'), ('u', 'update'), ('/', 'search'), ('s', 'sort'),
                    ('F5', 'refresh'), ('?', 'help'), ('q', 'quit')]
            priority = ['Enter', 'q', '?', 'i', 'r', 'u', '/', 's', full[0][0], full[1][0], 'F5']
            keep, used = set(), 0
            for name in priority:
                label = next(x for x in full if x[0] == name)
                need = len(label[0]) + len(label[1]) + 4
                if used + need <= width - 1:
                    keep.add(name)
                    used += need
            items = [x for x in full if x[0] in keep]
            chips(height - 1, 0, items, attr['footkey'], attr['foot'], gap=1)
            if ui['help']:
                lines = [('Up Down', 'move in the list (or j / k)'), ('Left Right', 'switch section (or Tab, or 1 to 5)'),
                         ('Enter', 'run if installed, install if not'), ('i', 'install'), ('r', 'run an installed app'),
                         ('u', 'update the selected item'), ('/', 'search (Enter or Esc to finish)'),
                         ('s', 'change sort order (Apps and Games)'), ('F5', 'look for apps and updates again'), ('q', 'quit')]
                bw = min(width - 4, 64)
                bh = len(lines) + 6
                by = max(1, (height - bh) // 2)
                bx = max(1, (width - bw) // 2)
                for n in range(bh):
                    put(by + n, bx, ' ' * bw, attr['pop'])
                put(by, bx, TLR + H * (bw - 2) + TRR, attr['pop'])
                put(by + bh - 1, bx, BLR + H * (bw - 2) + BRR, attr['pop'])
                for n in range(1, bh - 1):
                    put(by + n, bx, V, attr['pop'])
                    put(by + n, bx + bw - 1, V, attr['pop'])
                put(by + 1, bx + 3, 'KEYS', attr['pop'] | curses.A_BOLD)
                for n, (k, text) in enumerate(lines):
                    put(by + 3 + n, bx + 3, ' ' + k.ljust(max(len(x) for x, _ in lines)) + ' ', attr['chip'])
                    put(by + 3 + n, bx + 5 + max(len(x) for x, _ in lines) + 2, text, attr['pop'])
                put(by + bh - 2, bx + 3, 'Plain menu: appstore --plain    Window: appstore --gui', attr['pop'] | dim)
            stdscr.refresh()

        def fill_row_part(y, x1, x2, a):
            put(y, x1, ' ' * max(0, x2 - x1 + 1), a)

        def start(task, finish, message):
            if data['busy']:
                ui['msg'] = 'Still working: ' + data['busy']
                return
            data['busy'] = message
            ui['msg'] = message
            def target():
                try:
                    result, error = task(), None
                except Exception as exc:  # worker must report back
                    result, error = None, str(exc)
                jobs.put(lambda: (data.__setitem__('busy', None), finish(result, error)))
            threading.Thread(target=target, daemon=True).start()

        def load_apps(force=False):
            if OFFLINE:
                ui['msg'] = 'Offline: browsing needs internet. Run apps still works.'
                return
            if data['loaded'] and not force:
                return
            def finish(result, error):
                if error:
                    ui['msg'] = 'Could not reach GitHub: ' + error
                else:
                    data['apps'], data['loaded'] = result, True
                    ui['msg'] = f'{len(result)} app(s) found.'
            start(discover, finish, 'Looking for apps...')

        def check_now():
            if OFFLINE:
                return
            def finish(result, error):
                if error:
                    ui['msg'] = 'Update check failed: ' + error
                else:
                    data['pending'] = result
                    data['software'] = read_software_records()
                    ui['msg'] = f'{len(result)} update(s) available.' if result else 'Everything is up to date.'
            start(lambda: (check_updates(report=False), check_software_changes())[0], finish, 'Checking updates...')

        def outside(task):
            """Leave the rich view so prompts, installers and apps use the real terminal."""
            curses.def_prog_mode()
            curses.endwin()
            try:
                task()
            except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as exc:
                print('Could not finish: ' + str(exc))
            except KeyboardInterrupt:
                print('\nInterrupted. Back in the App Store.')
            try:
                input('\nPress Enter to return to the App Store...')
            except (EOFError, KeyboardInterrupt):
                pass
            curses.reset_prog_mode()
            stdscr.clear()
            stdscr.refresh()
            data['software'] = read_software_records()

        def selected_row():
            return data['rows'][ui['sel']] if data['rows'] else None

        def do_run():
            row = selected_row()
            state = load_state()
            if not row or row['name'] not in state:
                ui['msg'] = 'Run works on installed apps.'
                return
            def task():
                directory = installed_directory(state[row['name']])
                print('Running ' + row['name'] + '. Exit the app to return.\n')
                result = subprocess.run(['bash', MARKER, 'run'], cwd=directory)
                if result.returncode:
                    print(f'\n{row["name"]} exited with code {result.returncode}.')
            outside(task)

        def do_install():
            row = selected_row()
            if not row:
                return
            if row.get('software'):
                if OFFLINE:
                    ui['msg'] = 'Installing software needs internet.'
                    return
                name, recipe = row['software']
                outside(lambda: install_software(name, recipe, lambda text, question: ask(question)))
                return
            if not row.get('repo') or OFFLINE:
                ui['msg'] = 'Open Apps or Games and pick an app to install.' if not OFFLINE else 'Installing needs internet.'
                return
            outside(lambda: install(row['repo']))
            ui['msg'] = 'Back from install.'

        def do_update():
            row = selected_row()
            if not row:
                return
            pend = row.get('pending') or next((p for p in data['pending'] if p[1] == row['name']), None)
            if not pend:
                ui['msg'] = 'No update waiting for that item.'
                return
            def task():
                def confirm(text):
                    print(text)
                    return ask('Trust this and update?')
                if apply_update(pend, confirm):
                    data['pending'] = [p for p in data['pending'] if p[1] != pend[1]]
                    print('Updated.' + (' Quit and run appstore again.' if pend[3] is not None else ''))
            outside(task)

        def act():
            row = selected_row()
            if not row:
                return
            view = SECTIONS[ui['view']][0]
            if view == 'updates':
                do_update()
            elif view == 'other':
                do_install()
            elif row['name'] in load_state():
                do_run()
            else:
                do_install()

        def switch(step=None, index=None):
            ui['view'] = index if index is not None else (ui['view'] + step) % len(SECTIONS)
            ui['sel'] = ui['top'] = 0
            ui['search'] = ''
            if SECTIONS[ui['view']][0] in ('apps', 'games'):
                load_apps()

        load_apps()
        check_now_started = False
        while True:
            while True:
                try:
                    jobs.get_nowait()()
                except queue.Empty:
                    break
            if not check_now_started and data['loaded'] is not None and not data['busy']:
                check_now_started = True
                check_now()
            draw()
            key = stdscr.getch()
            if key == -1:
                continue
            if ui['help']:
                ui['help'] = False
                continue
            if ui['typing']:
                if key in (10, 13, curses.KEY_ENTER, 27):
                    ui['typing'] = False
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    ui['search'] = ui['search'][:-1]
                elif 32 <= key < 127:
                    ui['search'] += chr(key)
                ui['sel'] = ui['top'] = 0
                continue
            count = len(data['rows'])
            if key in (ord('q'), ord('Q')):
                return
            elif key in (curses.KEY_DOWN, ord('j')):
                ui['sel'] = min(ui['sel'] + 1, max(0, count - 1))
            elif key in (curses.KEY_UP, ord('k')):
                ui['sel'] = max(ui['sel'] - 1, 0)
            elif key == curses.KEY_NPAGE:
                ui['sel'] = min(ui['sel'] + 8, max(0, count - 1))
            elif key == curses.KEY_PPAGE:
                ui['sel'] = max(ui['sel'] - 8, 0)
            elif key == curses.KEY_HOME:
                ui['sel'] = 0
            elif key == curses.KEY_END:
                ui['sel'] = max(0, count - 1)
            elif key in (curses.KEY_RIGHT, 9, ord('l')):
                switch(1)
            elif key in (curses.KEY_LEFT, curses.KEY_BTAB, ord('h')):
                switch(-1)
            elif ord('1') <= key <= ord('5'):
                switch(index=key - ord('1'))
            elif key in (10, 13, curses.KEY_ENTER):
                act()
            elif key == ord('i'):
                do_install()
            elif key == ord('r'):
                do_run()
            elif key == ord('u'):
                do_update()
            elif key == ord('s') and SECTIONS[ui['view']][0] in ('apps', 'games'):
                ui['sort'] = (ui['sort'] + 1) % len(SORTS)
                ui['sel'] = ui['top'] = 0
                ui['msg'] = 'Sorted: ' + SORTS[ui['sort']][1]
            elif key == ord('/'):
                ui['typing'] = True
                ui['search'] = ''
            elif key in (curses.KEY_F5, ord('R')):
                load_apps(force=True)
                check_now()
            elif key == ord('?'):
                ui['help'] = True

    curses.wrapper(run)


def main(argv=None):
    global OFFLINE, UI
    parser = argparse.ArgumentParser(description='Pi App Store - install and run your GitHub apps')
    parser.add_argument('--offline', action='store_true', help='run installed apps without network checks')
    parser.add_argument('--no-color', action='store_true', help='disable terminal colors')
    parser.add_argument('--plain', action='store_true', help='use the plain numbered menu')
    parser.add_argument('--gui', action='store_true', help='open the window (needs python3-tk and a desktop)')
    parser.add_argument('--version', action='version', version='Pi App Store ' + VERSION)
    args = parser.parse_args(argv)
    OFFLINE = args.offline
    if args.gui:
        return gui()
    if use_rich(args.plain, os.environ, sys.stdin.isatty(), sys.stdout.isatty()):
        try:
            tui(no_color=args.no_color)
            return 0
        except Exception as exc:  # unusual terminal: fall back instead of failing
            print('Rich view unavailable (' + str(exc) + '). Using the plain menu.')
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
    sys.exit(main())
