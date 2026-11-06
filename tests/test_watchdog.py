"""Offline checks using small real publication/API schemas; all credentials are fake."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('watchdog', ROOT / 'scripts/watchdog.py')
mod = importlib.util.module_from_spec(spec)
sys.modules['watchdog'] = mod
spec.loader.exec_module(mod)
spec = importlib.util.spec_from_file_location('watchdog_installer', ROOT / 'scripts/install_watchdog.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class TestWatchdog(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.marker = json.loads((ROOT / 'tests/fixtures/watchdog_update.json').read_text())
        self.runs = json.loads((ROOT / 'tests/fixtures/watchdog_runs.json').read_text())
        self.now = datetime(2026, 11, 6, 19, 30, tzinfo=timezone.utc)
        self.calls = []
        self.private('token', 'github_pat_' + 'x' * 40)

    def private(self, name, text):
        path = self.root / name
        path.write_text(text)
        path.chmod(0o600)
        return path

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url == mod.SITE:
            self.assertNotIn('token', kwargs)
            return self.marker
        if url == mod.RUNS:
            if 'token' in kwargs:
                self.assertTrue(kwargs['token'].startswith('github_pat_'))
            return self.runs
        self.assertEqual(url, mod.DISPATCH)
        self.assertEqual(json.loads(kwargs['data']), {'ref': 'main'})

    def test_fresh_publication_needs_no_token_or_github_request(self):
        now = datetime(2026, 11, 6, 18, tzinfo=timezone.utc)
        (self.root / 'token').unlink()
        self.assertIn('fresh', mod.check(self.root, now=now, fetch=self.fetch))
        self.assertEqual([c[0] for c in self.calls], [mod.SITE])

    def test_dry_run_overdue_never_reads_token_or_writes_state(self):
        (self.root / 'token').unlink()
        self.assertIn('would dispatch', mod.check(self.root, now=self.now, fetch=self.fetch, dry_run=True))
        self.assertEqual(len(self.calls), 2)
        self.assertFalse((self.root / 'state.json').exists())

    def test_dispatch_is_fixed_main_and_persists_cooldown_before_post(self):
        self.private('token', 'github_pat_' + 'x' * 40)
        def fetch(url, **kwargs):
            if url == mod.DISPATCH:
                state = mod.load_state(self.root / 'state.json')
                self.assertEqual(state['attempts'], [self.now.isoformat()])
            return self.fetch(url, **kwargs)
        self.assertIn('Dispatched', mod.check(self.root, now=self.now, fetch=fetch))
        self.assertEqual(len(self.calls), 3)
        self.calls.clear()
        self.assertIn('Cooldown', mod.check(self.root, now=self.now + timedelta(minutes=59), fetch=fetch))
        self.assertEqual(self.calls, [])
        self.assertEqual((self.root / 'state.json').stat().st_mode & 0o777, 0o600)

    def test_ambiguous_dispatch_timeout_does_not_retry_next_poll(self):
        self.private('token', 'github_pat_' + 'x' * 40)
        def fetch(url, **kwargs):
            if url == mod.DISPATCH:
                raise mod.WatchdogError('Simulated network timeout')
            return self.fetch(url, **kwargs)
        with self.assertRaises(mod.WatchdogError):
            mod.check(self.root, now=self.now, fetch=fetch)
        self.assertIn('Cooldown', mod.check(self.root, now=self.now, fetch=fetch))

    def test_queued_running_waiting_and_recent_completed_runs_are_not_duplicated(self):
        for status in ('queued', 'in_progress', 'waiting', 'requested', 'pending'):
            self.runs['workflow_runs'][0]['status'] = status
            self.assertIn('already', mod.check(self.root, now=self.now, fetch=self.fetch))
        self.runs['workflow_runs'][0].update(status='completed', updated_at=self.now.isoformat())
        self.assertIn('settle', mod.check(self.root, now=self.now, fetch=self.fetch))
        self.assertFalse((self.root / 'state.json').exists())

    def test_bad_marker_dates_and_run_schema_fail_closed(self):
        for marker in ([], {}, {'built_utc': None}, {'built_utc': '2026-11-06'},
                       {'built_utc': '2026-11-06T17:00:00'}, {'built_utc': 'not a date'},
                       {'built_utc': (self.now + timedelta(hours=1)).isoformat()}):
            with self.subTest(marker=marker), self.assertRaises(mod.WatchdogError):
                mod.parse_marker(marker, self.now)
        for runs in ([], {}, {'workflow_runs': None}, {'workflow_runs': [None]},
                     {'workflow_runs': [{'head_branch': 'fork', 'status': 'queued'}]}):
            with self.subTest(runs=runs), self.assertRaises(mod.WatchdogError):
                mod.workflow_busy(runs, self.now)
        self.runs['workflow_runs'][0]['status'] = 'unexpected'
        with self.assertRaises(mod.WatchdogError):
            mod.workflow_busy(self.runs, self.now)

    def test_cooldown_and_six_hour_dispatch_limit(self):
        state = {'attempts': [(self.now - timedelta(minutes=i * 45)).isoformat() for i in range(6)]}
        mod.save_state(self.root / 'state.json', state)
        self.assertIn('limit', mod.check(self.root, now=self.now, fetch=self.fetch))
        state['attempts'] = ['2026-11-05T00:00:00+00:00']
        mod.save_state(self.root / 'state.json', state)
        self.assertIn('would dispatch', mod.check(self.root, now=self.now, fetch=self.fetch, dry_run=True))

    def test_http_rate_limit_retry_after_is_preserved(self):
        def fail(url, **kwargs):
            raise mod.HTTPFailure(429, 7200)
        with self.assertRaises(mod.HTTPFailure):
            mod.check(self.root, now=self.now, fetch=fail)
        self.assertEqual(mod.timestamp(mod.load_state(self.root / 'state.json')['not_before']), self.now + timedelta(hours=2))
        self.assertIn('Cooldown', mod.check(self.root, now=self.now, fetch=fail))

    def test_http_requests_never_forward_token_and_limit_response_size(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status, response.read.return_value = 204, b''
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(mod, 'build_opener', return_value=opener):
            mod.request_json(mod.DISPATCH, token='fake-private-value', data=b'{"ref":"main"}')
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, mod.DISPATCH)
            self.assertEqual(request.get_header('Authorization'), 'Bearer fake-private-value')
            response.status, response.read.return_value = 200, b'{}'
            mod.request_json(mod.SITE)
            self.assertIsNone(opener.open.call_args.args[0].get_header('Authorization'))
            response.read.return_value = b'x' * (mod.MAX_RESPONSE + 1)
            with self.assertRaisesRegex(mod.WatchdogError, 'size limit'):
                mod.request_json(mod.SITE)
        for url in ('http://api.github.com', 'https://attacker.invalid', mod.SITE):
            with self.assertRaises(mod.WatchdogError):
                mod.request_json(url, token='fake-private-value')
        self.assertIsNone(mod.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://attacker.invalid'))

    def test_http_errors_are_sanitized_and_not_retried(self):
        for error in (URLError('fake-private-value'), HTTPError(mod.DISPATCH, 403, 'fake-private-value', {}, None),
                      HTTPError(mod.DISPATCH, 302, 'fake-private-value', {'Location': 'https://attacker.invalid'}, None)):
            opener = MagicMock()
            opener.open.side_effect = error
            with patch.object(mod, 'build_opener', return_value=opener), self.assertRaises(mod.WatchdogError) as caught:
                mod.request_json(mod.DISPATCH, token='fake-private-value', data=b'{}')
            self.assertNotIn('fake-private-value', str(caught.exception))
            self.assertEqual(opener.open.call_count, 1)

    def test_http_retry_after_date_and_json_validation(self):
        opener = MagicMock()
        opener.open.side_effect = HTTPError(mod.RUNS, 429, '', {'Retry-After': 'Fri, 06 Nov 2026 21:30:00 GMT'}, None)
        with patch.object(mod, 'build_opener', return_value=opener), self.assertRaises(mod.HTTPFailure) as caught:
            mod.request_json(mod.RUNS, now=self.now)
        self.assertEqual(caught.exception.retry_after, 7200)
        response = MagicMock()
        response.__enter__.return_value = response
        response.status, response.read.return_value = 200, b'not JSON'
        opener.open.side_effect, opener.open.return_value = None, response
        with patch.object(mod, 'build_opener', return_value=opener), self.assertRaisesRegex(mod.WatchdogError, 'JSON'):
            mod.request_json(mod.SITE)

    def test_overlapping_watchdog_process_never_dispatches(self):
        with os.fdopen(mod.private_file(self.root / 'watchdog.lock', create=True), 'r+') as lock:
            mod.fcntl.flock(lock, mod.fcntl.LOCK_EX | mod.fcntl.LOCK_NB)
            with patch.object(mod, 'check') as check:
                self.assertEqual(mod.main(['--directory', str(self.root)]), 0)
                check.assert_not_called()
        logger = mod.logging.getLogger('irl-watchdog')
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    def test_private_files_symlinks_corrupt_state_and_token_format(self):
        path = self.private('token', 'github_pat_' + 'x' * 40)
        path.chmod(0o644)
        with self.assertRaises(mod.WatchdogError):
            mod.check(self.root, now=self.now, fetch=self.fetch)
        path.unlink()
        target = self.private('other', 'private')
        path.symlink_to(target)
        with self.assertRaises(OSError):
            mod.check(self.root, now=self.now, fetch=self.fetch)
        path.unlink()
        self.private('token', 'not a token')
        with self.assertRaises(mod.WatchdogError):
            mod.check(self.root, now=self.now, fetch=self.fetch)
        self.private('state.json', '{bad json')
        with self.assertRaises(mod.WatchdogError):
            mod.check(self.root, now=self.now, fetch=self.fetch)
        self.root.chmod(0o770)
        with self.assertRaises(mod.WatchdogError):
            mod.private_directory(self.root)

    def test_cron_preserves_existing_entries_is_idempotent_and_rejects_injection(self):
        entry = installer.cron_entry(Path('/private/with space'), Path('/usr/bin/python3'))
        self.assertIn('-I', entry)
        self.assertIn("'/private/with space/watchdog.py'", entry)
        existing = '# Existing job\nMAILTO=""\n12 * * * * /private/other-job\n'
        merged = installer.merge_cron(existing, entry)
        self.assertTrue(merged.startswith(existing))
        self.assertEqual(installer.merge_cron(merged, entry), merged)
        self.assertNotIn('token', entry)
        for path in ('/private/new\ncommand', '/private/percent%command'):
            with self.assertRaises(mod.WatchdogError):
                installer.cron_entry(Path(path), Path('/usr/bin/python3'))
        with self.assertRaises(mod.WatchdogError):
            installer.merge_cron(installer.BEGIN + '\n', entry)

    def test_installer_does_not_change_cron_without_explicit_flag(self):
        directory = self.root / 'install'
        with patch.object(installer.subprocess, 'run') as run:
            self.assertEqual(installer.main(['--directory', str(directory)]), 0)
            run.assert_not_called()
        self.assertEqual((directory / 'watchdog.py').stat().st_mode & 0o777, 0o600)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertFalse((directory / 'token').exists())

    def test_installer_refuses_credentials_inside_git_working_tree(self):
        (self.root / '.git').mkdir()
        directory = self.root / 'private'
        self.assertEqual(installer.main(['--directory', str(directory)]), 1)
        self.assertFalse(directory.exists())

    def test_explicit_installer_backs_up_and_verifies_preserved_cron(self):
        directory = self.root / 'install'
        existing = '# Existing unrelated cron\n5 * * * * /private/job\n'
        calls = []
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            result = MagicMock(returncode=0, stdout=existing, stderr='')
            if len(calls) == 3:
                result.stdout = calls[1][1]['input']
            return result
        with patch.object(installer.getpass, 'getpass', return_value='github_pat_' + 'x' * 40), \
                patch.object(installer.subprocess, 'run', side_effect=run):
            self.assertEqual(installer.main(['--directory', str(directory), '--set-token', '--install-cron']), 0)
        self.assertEqual((directory / 'crontab.before-watchdog').read_text(), existing)
        self.assertTrue(calls[1][1]['input'].startswith(existing))
        self.assertNotIn('github_pat_', calls[1][1]['input'])
        self.assertEqual((directory / 'token').stat().st_mode & 0o777, 0o600)
