#!/usr/bin/env python3
"""Small, opt-in GitHub app store for Debian-based Raspberry Pi systems."""
import concurrent.futures
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
import urllib.error
import urllib.parse
import urllib.request

OWNER = 'Greenisus1'
MARKER = 'app-store.sh'
SIGNATURE = '# pi-app-store: 1'
HOME = Path.home() / '.local' / 'share' / 'pi-app-store'
# Add another apt entry here: ('Display name', ['apt', 'package', ...]).
SOFTWARE = [('Python 3', ['apt', 'python3', 'python3-pip', 'python3-venv']),
            ('Ollama', ['script', 'https://ollama.com/install.sh'])]


def fetch(url, limit=2_000_000):
    req = urllib.request.Request(url, headers={'User-Agent': 'pi-app-store/1',
                                               'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Download exceeds size limit')
    return data


def api(path):
    return json.loads(fetch('https://api.github.com/' + path))


def raw(repo, ref, path=MARKER):
    return 'https://raw.githubusercontent.com/{}/{}/{}/{}'.format(
        OWNER, repo, urllib.parse.quote(ref, safe=''), path)


def valid_marker(data):
    text = data.decode('utf-8')
    return SIGNATURE in text.splitlines()[:5]


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
            if valid_marker(fetch(raw(repo['name'], repo['default_branch']), 16_384)):
                return repo
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


def install(repo):
    name = repo['name']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..'):
        raise ValueError('Invalid repository name')
    branch = urllib.parse.quote(repo['default_branch'], safe='')
    commit = api(f'repos/{OWNER}/{name}/commits/{branch}')['sha']
    previous = load_state().get(name)
    if previous and previous.get('commit') == commit and Path(previous['directory']).is_dir():
        print('This commit is already installed. Open Installed apps to launch it.')
        return
    marker = fetch(raw(name, commit), 16_384)
    if not valid_marker(marker):
        raise ValueError('Missing valid app marker at chosen commit')
    print(f'\nInstall {OWNER}/{name} at {commit[:12]}')
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
    state[name] = {'commit': commit, 'directory': str(final)}
    save_state(state)
    print('Installed. Open Installed apps to launch it.')


def choose(title, rows):
    print('\n' + title + '\n' + '=' * len(title))
    for index, text in enumerate(rows, 1):
        print(f'{index}. {text}')
    print('0. Back')
    value = input('Choose: ').strip()
    if value == '0':
        return None
    if not value.isdigit() or not 1 <= int(value) <= len(rows):
        print('Choose a number from the list.')
        return None
    return int(value) - 1


def installed():
    state = load_state()
    names = sorted(state)
    if not names:
        print('No apps installed yet.')
        return
    choice = choose('Installed apps - launch', names)
    if choice is not None:
        item = state[names[choice]]
        directory = Path(item['directory']).resolve()
        if not directory.is_relative_to((HOME / 'apps').resolve()):
            raise ValueError('Invalid installed directory')
        marker = directory / MARKER
        if not marker.is_file() or not valid_marker(marker.read_bytes()):
            raise ValueError('Installed marker is missing or invalid')
        subprocess.run(['bash', MARKER, 'run'], cwd=directory, check=True)


def other():
    choice = choose('Other software', [name for name, _ in SOFTWARE])
    if choice is None:
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


def check_updates():
    """Check only: no downloaded code runs and nothing is replaced here."""
    print('Checking for updates...')
    pending = []
    try:
        latest = api(f'repos/{OWNER}/pi-app-store/commits?path=appstore.py&per_page=1')[0]['sha']
        source = fetch(raw('pi-app-store', latest, 'appstore.py'))
        if source != Path(__file__).read_bytes():
            pending.append(('App Store itself', 'pi-app-store', latest, source))
    except (OSError, ValueError, IndexError, KeyError) as exc:
        print('App Store update check unavailable: ' + str(exc))
    try:
        installed_state = load_state()
    except (OSError, ValueError) as exc:
        print('Installed update check unavailable: ' + str(exc))
        installed_state = {}
    for name, item in installed_state.items():
        if name == 'pi-app-store':
            continue
        try:
            latest = api(f'repos/{OWNER}/{name}/commits?per_page=1')[0]['sha']
            if latest != item['commit']:
                pending.append((name, name, latest, None))
        except (OSError, ValueError, IndexError, KeyError) as exc:
            print(f'{name}: update check unavailable: {exc}')
    if pending:
        print('Updates available: ' + ', '.join(row[0] for row in pending))
        print('Choose Updates to review and install. Nothing updated automatically.')
    else:
        print('No updates found in the checks that completed.')
    return pending


def updates(pending):
    if not pending:
        pending.extend(check_updates())
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
        install(repo)
        if load_state().get(name, {}).get('commit') == commit:
            pending.pop(choice)


def main():
    print('PI APP STORE\nGitHub apps + installed apps + other software')
    pending = check_updates()
    while True:
        print('\n1. GitHub apps\n2. Installed apps\n3. Other software\n4. Updates\n0. Quit')
        try:
            choice = input('Choose: ').strip()
            if choice == '0':
                return
            if choice == '1':
                print('Checking opt-in repositories...')
                apps = discover()
                if not apps:
                    print('No marked apps found. Add app-store.sh to an app repo first.')
                    continue
                selected = choose('GitHub apps', [r['name'] + ' - ' + (r.get('description') or '') for r in apps])
                if selected is not None:
                    install(apps[selected])
            elif choice == '2':
                installed()
            elif choice == '3':
                other()
            elif choice == '4':
                updates(pending)
        except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as exc:
            print('Could not finish: ' + str(exc))
        except (EOFError, KeyboardInterrupt):
            print('\nGoodbye.')
            return


if __name__ == '__main__':
    main()
