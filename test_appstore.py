import contextlib
import io
import itertools
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

import appstore as app


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.h = patch.object(app, 'HOME', self.home); self.h.start(); self.addCleanup(self.h.stop)
        app.OFFLINE = False
        app.CHECK_ERRORS.clear(); app.SOFTWARE_ERRORS.clear()
        self.output = io.StringIO()
        self.o = contextlib.redirect_stdout(self.output); self.o.__enter__()
        self.addCleanup(self.o.__exit__, None, None, None)
        app.UI = app.Terminal(self.output)

    def seed(self, name='Demo', exitcode=0):
        folder = self.home / 'apps' / name / 'old'
        folder.mkdir(parents=True)
        (folder / app.MARKER).write_text('#!/bin/bash\n# pi-app-store: 1\necho ran-demo\nexit ' + str(exitcode) + '\n')
        state = app.load_state()
        state[name] = {'directory': str(folder), 'commit': 'old', 'version': '1.0', 'branch': 'main'}
        app.save_state(state)
        return folder

    def test_marker(self):
        self.assertTrue(app.valid_marker(b'#!/bin/bash\n# pi-app-store: 1'))
        self.assertFalse(app.valid_marker(b'no'))

    def test_version(self):
        self.assertEqual(app.parse_version(b'{"version":"1.2.3"}'), '1.2.3')
        for value in ('{}', '{"version":2}', '{"version":"bad version"}'):
            with self.assertRaises(ValueError): app.parse_version(value)

    def test_offline_menu(self):
        with patch('builtins.input', side_effect=['x', '0']), patch.object(app, 'fetch') as fetch:
            app.main(['--offline'])
        fetch.assert_not_called()
        self.assertIn('Run apps', self.output.getvalue())
        self.assertNotIn('\x1b', self.output.getvalue())

    def test_menu_retries(self):
        with patch('builtins.input', side_effect=['wrong', '99', '²', '1']):
            self.assertEqual(app.choose('Apps', ['Demo']), 0)

    def test_terminal_sanitizes(self):
        app.UI.heading('Hi\x1b[31m\nthere')
        self.assertNotIn('\x1b', self.output.getvalue())

    def test_no_color_environment(self):
        stream = io.StringIO(); stream.isatty = lambda: True
        with patch.dict(os.environ, {'TERM': 'xterm', 'NO_COLOR': ''}):
            self.assertFalse(app.Terminal(stream).color)

    def test_narrow_layout(self):
        with patch.object(app.shutil, 'get_terminal_size', return_value=os.terminal_size((40, 24))):
            app.UI.heading('PI APP STORE', 'A long description ' * 5)
        self.assertTrue(all(len(line) <= 40 for line in self.output.getvalue().splitlines()))

    def test_state_roundtrip(self):
        self.seed(); self.assertIn('Demo', app.load_state())

    def test_invalid_state(self):
        app.state_path().write_text('{"broken": {}}')
        with self.assertRaises(ValueError): app.load_state()

    def test_launch_real_marker_and_return(self):
        self.seed()
        with patch('builtins.input', side_effect=['1', '0']): app.installed()
        self.assertIn('Back in the App Store', self.output.getvalue())

    def test_app_failure_keeps_menu(self):
        self.seed(exitcode=7)
        with patch('builtins.input', side_effect=['1', '0']): app.installed()
        self.assertIn('code 7', self.output.getvalue())

    def test_missing_app(self):
        folder = self.seed(); (folder / app.MARKER).unlink()
        with patch('builtins.input', side_effect=['1', '0']): app.installed()
        self.assertIn('Cannot run', self.output.getvalue())

    def test_escape_directory(self):
        with self.assertRaises(ValueError): app.installed_directory({'directory': str(self.home)})

    def test_symlink_marker(self):
        folder = self.seed(); marker = folder / app.MARKER
        marker.rename(folder / 'real'); marker.symlink_to('real')
        with self.assertRaises(ValueError): app.installed_directory({'directory': str(folder)})

    def checks(self, version, latest='new'):
        self.seed()
        def api(path):
            if path.endswith('/pi-app-store'): return {'default_branch': 'main'}
            return {'sha': latest}
        def versions(name, commit): return app.VERSION if name == 'pi-app-store' else version
        with patch.object(app, 'api', side_effect=api), patch.object(app, 'remote_version', side_effect=versions):
            return app.check_updates()

    def test_same_version_ignores_edits(self): self.assertEqual(self.checks('1.0'), [])
    def test_changed_version_updates(self): self.assertIn('1.0 -> 2.0', self.checks('2.0')[0][0])
    def test_legacy_commit_fallback(self): self.assertIn('legacy', self.checks(None)[0][0])
    def test_legacy_same_commit(self): self.assertEqual(self.checks(None, 'old'), [])

    def test_failed_checks(self):
        with patch.object(app, 'api', side_effect=OSError('offline')):
            self.assertEqual(app.check_updates(), [])
        self.assertTrue(app.CHECK_ERRORS)

    def test_no_network_offline(self):
        app.OFFLINE = True
        with patch.object(app.urllib.request, 'urlopen') as call:
            with self.assertRaises(OSError): app.fetch('https://example.com')
            app.check_software_changes(); app.check_updates()
        call.assert_not_called()

    def test_background_does_not_block_quit(self):
        event = threading.Event()
        def slow(report=True): event.wait(2); return []
        with patch.object(app, 'check_updates', side_effect=slow), patch.object(app, 'check_software_changes'), patch('builtins.input', return_value='0'):
            app.main([])
            self.assertIn('background', self.output.getvalue())
            event.set()

    def test_software_json_history(self):
        def api(path):
            if '/commits/' not in path: return {'default_branch': 'main'}
            return {'sha': 'abc', 'html_url': 'https://example.com/commit/abc',
                    'commit': {'committer': {'date': '2026-10-01T00:00:00Z'}, 'message': 'Fix one\nbody'}}
        with patch.object(app, 'api', side_effect=api):
            app.check_software_changes(); app.check_software_changes()
        data = json.loads((self.home / 'software-changes.json').read_text())
        self.assertEqual(len(data['software']['Python 3']['history']), 1)
        self.assertEqual(data['software']['Ollama']['latest']['summary'], 'Fix one')

    def test_software_failed_check_preserves_record(self):
        target = self.home / 'software-changes.json'
        target.write_text('{"software":{"Python 3":{"latest":{"commit":"saved"}}}}')
        with patch.object(app, 'api', side_effect=OSError('offline')): app.check_software_changes()
        data = json.loads(target.read_text())
        self.assertEqual(data['software']['Python 3']['latest']['commit'], 'saved')
        self.assertEqual(len(data['last_errors']), 2)

    def test_python_launch(self):
        with patch.object(app.subprocess, 'run') as run: app.run_tool('python3')
        run.assert_called_once_with(['python3'])

    def test_ollama_launch(self):
        listing = subprocess.CompletedProcess([], 0, stdout='NAME ID SIZE\nmodel:tag abc 2GB\n')
        with patch.object(app.subprocess, 'run', side_effect=[listing, subprocess.CompletedProcess([], 0)]) as run, patch('builtins.input', return_value='1'):
            app.run_tool('ollama')
        self.assertEqual(run.call_args_list[-1].args[0], ['ollama', 'run', 'model:tag'])

    def test_update_pinned(self):
        pending = [('Demo', 'Demo', 'reviewed', None)]
        with patch('builtins.input', return_value='1'), patch.object(app, 'api', return_value={'name': 'Demo'}), patch.object(app, 'install') as install:
            app.updates(pending)
        install.assert_called_once_with({'name': 'Demo'}, selected_commit='reviewed')

    def test_archive_traversal(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as archive:
            member = tarfile.TarInfo('repo/../bad'); member.size = 1
            archive.addfile(member, io.BytesIO(b'x'))
        with self.assertRaises(ValueError): app.extract(data.getvalue(), self.home)

    def test_pinned_install_and_version_save(self):
        marker = b'#!/bin/bash\n# pi-app-store: 1\nexit 0\n'
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w:gz') as tar:
            for name, data in [(app.MARKER, marker), (app.VERSION_FILE, b'{"version":"2.0"}')]:
                item = tarfile.TarInfo('repo/' + name); item.size = len(data)
                tar.addfile(item, io.BytesIO(data))
        def fetch(url, limit=2_000_000):
            if '/tarball/' in url: return archive.getvalue()
            if url.endswith(app.VERSION_FILE): return b'{"version":"2.0"}'
            return marker
        with patch.object(app, 'fetch', side_effect=fetch), patch.object(app, 'api', return_value={'sha': 'pinned'}), patch('builtins.input', return_value='y'):
            app.install({'name': 'Demo', 'default_branch': 'main'})
        saved = app.load_state()['Demo']
        self.assertEqual(saved['version'], '2.0')
        self.assertEqual(saved['commit'], 'pinned')
        self.assertTrue(Path(saved['directory']).is_dir())

    def test_declined_install_unchanged(self):
        with patch.object(app, 'api', return_value={'sha': 'pinned'}), patch.object(app, 'remote_version', return_value='2'), patch.object(app, 'fetch', return_value=b'# pi-app-store: 1'), patch('builtins.input', return_value='n'):
            app.install({'name': 'Demo', 'default_branch': 'main'})
        self.assertEqual(app.load_state(), {})

    def test_version_missing_only_404_falls_back(self):
        with patch.object(app, 'fetch', side_effect=urllib.error.HTTPError('url', 404, 'gone', {}, None)):
            self.assertIsNone(app.remote_version('Demo', 'sha'))
        with patch.object(app, 'fetch', side_effect=urllib.error.HTTPError('url', 403, 'blocked', {}, None)):
            with self.assertRaises(urllib.error.HTTPError): app.remote_version('Demo', 'sha')

    def test_installer_all_casings_and_repeat(self):
        fake = self.home / 'fake'; fake.mkdir()
        (fake / 'id').write_text('#!/bin/sh\necho 1000\n'); (fake / 'id').chmod(0o755)
        env = dict(os.environ, HOME=str(self.home), PATH=str(fake) + ':' + os.environ['PATH'])
        installer = Path(app.__file__).with_name('install.sh')
        for _ in range(2): subprocess.run(['bash', str(installer), '--local'], env=env, check=True, capture_output=True)
        bindir = self.home / '.local/bin'
        names = [''.join(chars) for chars in itertools.product(*[(c.lower(), c.upper()) for c in 'appstore'])]
        for name in names:
            result = subprocess.run([str(bindir / name), '--version'], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, name)
            self.assertIn(app.VERSION, result.stdout)
        result = subprocess.run([str(bindir / 'appstore'), '--offline'], input='0\n', env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('Run apps', result.stdout)

    def test_installer_conflict_does_not_replace(self):
        fake = self.home / 'fake'; fake.mkdir()
        (fake / 'id').write_text('#!/bin/sh\necho 1000\n'); (fake / 'id').chmod(0o755)
        bindir = self.home / '.local/bin'; bindir.mkdir(parents=True)
        (bindir / 'appstore').write_text('unrelated')
        env = dict(os.environ, HOME=str(self.home), PATH=str(fake) + ':' + os.environ['PATH'])
        result = subprocess.run(['bash', str(Path(app.__file__).with_name('install.sh')), '--local'], env=env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((bindir / 'appstore').read_text(), 'unrelated')
        self.assertFalse((self.home / '.local/share/pi-app-store/program/appstore.py').exists())

    def test_marker_category(self):
        self.assertEqual(app.marker_category(b'#!/bin/bash\n# pi-app-store: 1\n# pi-app-store-category: games\n'), 'games')
        self.assertEqual(app.marker_category(b'#!/bin/bash\n# pi-app-store: 1\n'), 'apps')
        self.assertEqual(app.marker_category(b'#!/bin/bash\n# pi-app-store: 1\n# pi-app-store-category: Bad Name!\n'), 'apps')
        self.assertEqual(app.marker_category(b'1\n2\n3\n4\n5\n# pi-app-store-category: games\n'), 'apps')

    def test_window_rows_and_software(self):
        apps = [{'name': 'a', 'description': 'x\x1b[31m', 'category': 'apps'},
                {'name': 'g', 'description': 'game', 'category': 'games'}]
        state = {'a': {'version': '1.0.0', 'directory': str(self.home / 'nope')}}
        self.assertEqual([r['name'] for r in app.build_rows('apps', apps, state, [])], ['a'])
        self.assertEqual([r['name'] for r in app.build_rows('games', apps, state, [])], ['g'])
        row = app.build_rows('apps', apps, state, [('lbl', 'a', 'c' * 40, None)])[0]
        self.assertEqual(row['status'], 'update available')
        self.assertNotIn('\x1b', row['desc'])
        self.assertEqual(app.build_rows('installed', apps, state, [])[0]['status'], 'missing - reinstall')
        other = app.build_rows('other', [], {}, [])
        self.assertIn('Python Tk (python3-tk)', [r['name'] for r in other])
        self.assertIn(app.software_status('Python Tk (python3-tk)'), ('installed', 'missing'))
        self.assertIn(('Python Tk (python3-tk)', ['apt', 'python3-tk']), app.SOFTWARE)

    def test_terminal_command_and_gui_fallback(self):
        with patch.object(app.shutil, 'which', return_value=None):
            self.assertIsNone(app.terminal_command(self.home))
        with patch.object(app.shutil, 'which', side_effect=lambda n: '/bin/' + n if n == 'xterm' else None):
            self.assertEqual(app.terminal_command(self.home)[:2], ['/bin/xterm', '-e'])
        import sys
        with patch.dict(sys.modules, {'tkinter': None}), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(app.gui(), 1)
        self.assertIn('python3-tk', out.getvalue())


if __name__ == '__main__': unittest.main()
