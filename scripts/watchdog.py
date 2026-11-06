#!/usr/bin/env python3
"""One-shot publication watchdog. Standard library; designed for private cron use."""
import argparse
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

UTC = timezone.utc
SITE = 'https://crombie-lab.github.io/IRL-dashboard/update.json'
WORKFLOW = 'https://api.github.com/repos/Crombie-Lab/IRL-dashboard/actions/workflows/pages.yml'
RUNS = WORKFLOW + '/runs?branch=main&per_page=100'
DISPATCH = WORKFLOW + '/dispatches'
MAX_RESPONSE = 1024 * 1024
MAX_AGE = timedelta(minutes=90)
COOLDOWN = timedelta(hours=1)
GRACE = timedelta(minutes=15)
FUTURE_TOLERANCE = timedelta(minutes=5)


class WatchdogError(Exception):
    """Safe-to-log diagnostic, without response bodies, tokens or request headers."""


class HTTPFailure(WatchdogError):
    def __init__(self, code, retry_after=0):
        super().__init__(f'HTTP {code}; no immediate retry')
        self.retry_after = retry_after


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward GitHub authorization to a redirected URL.


def timestamp(value):
    try:
        if not isinstance(value, str):
            raise ValueError
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(UTC)
    except (ValueError, TypeError, OverflowError):
        raise WatchdogError('Invalid timezone-aware timestamp') from None


def parse_marker(body, now):
    if not isinstance(body, dict):
        raise WatchdogError('Invalid publication marker')
    built = timestamp(body.get('built_utc'))
    if built > now + FUTURE_TOLERANCE:
        raise WatchdogError('Publication timestamp is unexpectedly in the future')
    return built


def workflow_busy(body, now):
    if not isinstance(body, dict) or not isinstance(body.get('workflow_runs'), list):
        raise WatchdogError('Invalid GitHub workflow run list')
    for row in body['workflow_runs']:
        if not isinstance(row, dict) or row.get('head_branch') != 'main':
            raise WatchdogError('Unexpected GitHub workflow run schema/branch')
        status = row.get('status')
        if status not in ('completed', 'queued', 'in_progress', 'waiting', 'pending', 'requested'):
            raise WatchdogError('Unknown GitHub workflow run status')
        updated = timestamp(row.get('updated_at'))
        if updated > now + FUTURE_TOLERANCE:
            raise WatchdogError('GitHub workflow timestamp is unexpectedly in the future')
        if status != 'completed':
            return 'workflow already queued or running'
        if now - updated < GRACE:
            return 'recent workflow; allowing publication to settle'
    return None


def request_json(url, *, token=None, data=None, now=None):
    # Fixed destinations: CLI arguments and response URLs never control requests.
    if url not in (SITE, RUNS, DISPATCH) or (token and url not in (RUNS, DISPATCH)) or (data is not None and url != DISPATCH):
        raise WatchdogError('Request destination rejected')
    headers = {'User-Agent': 'IRL-dashboard-watchdog/1.0', 'Cache-Control': 'no-cache',
               'Accept': 'application/vnd.github+json' if url != SITE else 'application/json'}
    if token:
        headers.update({'Authorization': 'Bearer ' + token, 'X-GitHub-Api-Version': '2022-11-28'})
    if data is not None:
        headers['Content-Type'] = 'application/json'
    try:
        with build_opener(NoRedirect).open(Request(url, data=data, headers=headers), timeout=20) as response:
            raw = response.read(MAX_RESPONSE + 1)
            code = response.status
    except HTTPError as exc:
        retry_after = 0
        value = exc.headers.get('Retry-After', '')
        try:
            retry_after = float(value) if value.isdigit() else (parsedate_to_datetime(value) - (now or datetime.now(UTC))).total_seconds()
        except (ValueError, TypeError, OverflowError):
            pass
        # Do not include exception text: URLs, bodies and headers can contain secrets.
        raise HTTPFailure(exc.code, max(0, retry_after)) from None
    except (URLError, TimeoutError, OSError):
        raise WatchdogError('Network request failed; no immediate retry') from None
    if len(raw) > MAX_RESPONSE:
        raise WatchdogError('HTTP response exceeds size limit')
    if data is not None:
        if code != 204:
            raise WatchdogError('Unexpected dispatch response')
        return None
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise WatchdogError('Invalid JSON response') from None


def private_directory(path):
    path = Path(path).absolute()
    # Check ancestors too: another account must not be able to replace private files.
    for parent in (path, *path.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise WatchdogError('Private directory ancestry includes a link/non-directory')
        if info.st_mode & 0o022 and not (parent == Path('/tmp') and info.st_mode & stat.S_ISVTX):
            raise WatchdogError('Private directory ancestry is group/world writable')
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise WatchdogError('Private directory must be owned by this account with mode 700')
    return path


def private_file(path, *, create=False):
    flags = os.O_RDWR if create else os.O_RDONLY
    if create:
        flags |= os.O_CREAT
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
        os.close(fd)
        raise WatchdogError('Private file must be a single regular file owned by this account, mode 600')
    return fd


def load_state(path):
    if not path.exists() and not path.is_symlink():
        return {'attempts': []}
    with os.fdopen(private_file(path), 'r') as stream:
        try:
            value = json.loads(stream.read(16385))
            if not isinstance(value, dict) or not isinstance(value.get('attempts'), list):
                raise ValueError
            for item in value['attempts']:
                timestamp(item)
            if value.get('not_before'):
                timestamp(value['not_before'])
            return value
        except (ValueError, TypeError):
            raise WatchdogError('Invalid private state; refusing to dispatch') from None


def load_token(path):
    with os.fdopen(private_file(path), 'r') as stream:
        token = stream.read(4097).strip()
    if not re.fullmatch(r'github_pat_[A-Za-z0-9_]{20,4000}', token):
        raise WatchdogError('Expected a dedicated fine-grained GitHub token in the private token file')
    return token


def save_state(path, state):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.state-', delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(state, stream)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def check(root, *, dry_run=False, now=None, fetch=request_json):
    now = now or datetime.now(UTC)
    state_path = root / 'state.json'
    state = load_state(state_path)
    if state.get('not_before') and timestamp(state['not_before']) > now:
        return 'Cooldown active; no dispatch'
    try:
        built = parse_marker(fetch(SITE, now=now), now)
        if now - built < MAX_AGE:
            return 'Publication fresh; no dispatch'
        # Authenticate API reads too: cluster accounts can share the anonymous IP quota.
        token = None if dry_run else load_token(root / 'token')
        reason = workflow_busy(fetch(RUNS, now=now, **({'token': token} if token else {})), now)
        if reason:
            return reason + '; no dispatch'
        attempts = [t for t in state['attempts'] if now - timestamp(t) < timedelta(hours=6)]
        if len(attempts) >= 6:
            return 'Six-hour dispatch limit reached; no dispatch'
        if dry_run:
            return 'DRY RUN: publication overdue; would dispatch pages.yml on main'
        # Reserve before POST: an ambiguous timeout must not cause duplicate dispatches.
        state = {'attempts': attempts + [now.isoformat()], 'not_before': (now + COOLDOWN).isoformat()}
        save_state(state_path, state)
        fetch(DISPATCH, token=token, data=b'{"ref":"main"}', now=now)
        return 'Dispatched pages.yml on main; one-hour cooldown started'
    except HTTPFailure as exc:
        if not dry_run and exc.retry_after:
            until = now + timedelta(seconds=exc.retry_after)
            if state.get('not_before'):
                until = max(until, timestamp(state['not_before']))
            state['not_before'] = until.isoformat()
            save_state(state_path, state)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True, help='Private installed directory containing token/state/logs')
    parser.add_argument('--dry-run', action='store_true', help='Read public status only; never read token or dispatch')
    args = parser.parse_args(argv)
    os.umask(0o077)
    logger = None
    try:
        root = private_directory(args.directory)
        os.close(private_file(root / 'watchdog.log', create=True))
        logger = logging.getLogger('irl-watchdog')
        handler = RotatingFileHandler(root / 'watchdog.log', maxBytes=131072, backupCount=2)
        handler.setFormatter(logging.Formatter('%(asctime)sZ %(levelname)s %(message)s'))
        handler.formatter.converter = time.gmtime
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        with os.fdopen(private_file(root / 'watchdog.lock', create=True), 'r+') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                logger.info('Another watchdog process is running; no dispatch')
                return 0
            result = check(root, dry_run=args.dry_run)
            logger.info(result)
            print(result)
        return 0
    except (WatchdogError, OSError) as exc:
        message = str(exc) if isinstance(exc, WatchdogError) else 'Private file/directory unavailable; check permissions and setup'
        if logger:
            logger.error(message)
        print('Watchdog error: ' + message)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
