#!/usr/bin/env python3
"""Install a reviewed private watchdog copy; changing cron requires --install-cron."""
import argparse
import getpass
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import warnings

import watchdog

BEGIN = '# BEGIN IRL-dashboard watchdog'
END = '# END IRL-dashboard watchdog'


def atomic_write(path, content):
    if path.exists() or path.is_symlink():
        os.close(watchdog.private_file(path))
    with tempfile.NamedTemporaryFile(dir=path.parent, mode='wb', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    try:
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass  # Successful replacement already removed the temporary path.


def cron_entry(directory, python):
    if any(c in str(directory) + str(python) for c in '\n\r%'):
        raise watchdog.WatchdogError('Cron paths must not contain newlines or percent signs')
    return '7,22,37,52 * * * * ' + ' '.join(shlex.quote(str(p)) for p in
        (python, '-I', directory / 'watchdog.py', '--directory', directory)) + ' >/dev/null 2>&1'


def merge_cron(existing, entry):
    lines = existing.splitlines()
    if lines.count(BEGIN) != lines.count(END) or lines.count(BEGIN) > 1:
        raise watchdog.WatchdogError('Ambiguous existing watchdog block; cron was not changed')
    if BEGIN in lines:
        start, end = lines.index(BEGIN), lines.index(END)
        if end <= start:
            raise watchdog.WatchdogError('Invalid existing watchdog block; cron was not changed')
        lines[start:end + 1] = [BEGIN, entry, END]
    else:
        lines.extend([BEGIN, entry, END])
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path.home() / '.local/share/irl-dashboard-watchdog')
    parser.add_argument('--set-token', action='store_true', help='Prompt privately for a dedicated fine-grained token')
    parser.add_argument('--install-cron', action='store_true', help='Back up and update only the managed watchdog cron block')
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        destination = args.directory.absolute()
        if any((parent / '.git').exists() for parent in (destination, *destination.parents)):
            raise watchdog.WatchdogError('Installation must be outside all Git working trees')
        args.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        root = watchdog.private_directory(args.directory)
        atomic_write(root / 'watchdog.py', Path(__file__).with_name('watchdog.py').read_bytes())
        if args.set_token:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', getpass.GetPassWarning)
                    token = getpass.getpass('Dedicated fine-grained GitHub token (hidden): ').strip()
            except getpass.GetPassWarning:
                raise watchdog.WatchdogError('Use an interactive terminal with hidden input; token was not saved') from None
            if not re.fullmatch(r'github_pat_[A-Za-z0-9_]{20,4000}', token):
                raise watchdog.WatchdogError('Token format rejected; nothing saved')
            atomic_write(root / 'token', (token + '\n').encode())
            print('Token saved privately; never included in cron or logs.')
        entry = cron_entry(root, Path(sys.executable).absolute())
        if args.install_cron:
            watchdog.load_token(root / 'token')
            result = subprocess.run(['crontab', '-l'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                                    env={**os.environ, 'LC_ALL': 'C'}, timeout=15)
            if result.returncode != 0 and not (result.returncode == 1 and 'no crontab for' in result.stderr.lower()):
                raise watchdog.WatchdogError('Cannot read current crontab; no changes made')
            existing = result.stdout if result.returncode == 0 else ''
            merged = merge_cron(existing, entry)
            atomic_write(root / 'crontab.before-watchdog', existing.encode())
            result = subprocess.run(['crontab', '-'], input=merged, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=15)
            if result.returncode:
                raise watchdog.WatchdogError('Cron install failed; private backup retained')
            result = subprocess.run(['crontab', '-l'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=15)
            if result.returncode or entry not in result.stdout.splitlines():
                raise watchdog.WatchdogError('Cron verification failed; inspect crontab manually')
            print('Managed cron entry installed and verified; existing entries preserved.')
        else:
            print('Private code installed. Cron has not been changed.')
            print('Proposed entry:', entry)
        print('Private directory:', root)
        return 0
    except (watchdog.WatchdogError, OSError, subprocess.TimeoutExpired) as exc:
        print('Setup error:', str(exc) if isinstance(exc, watchdog.WatchdogError) else 'Private file or cron operation failed; no credentials printed')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
