"""Bounded transport retries and private, atomic restart state. No policy fallback."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import time
import urllib.error


def transient(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in {408, 429, 500, 502, 503, 504}
    if isinstance(exc, (TimeoutError, ConnectionError, socket.timeout)):
        return True
    if isinstance(exc, urllib.error.URLError):
        return transient(exc.reason) or isinstance(exc.reason, socket.gaierror)
    # Connector errors retain HTTP status but have no HTTPError type.
    return isinstance(exc, RuntimeError) and bool(re.search(
        r'(?:status=|HTTP(?:Error)?[: ]+)(?:408|429|500|502|503|504)\b|'
        r'\b(?:timed out|connection reset|temporary failure|RemoteDisconnected)\b', str(exc), re.I))


def retry(work, attempts=4, sleep=time.sleep, guard=None):
    for attempt in range(attempts):
        if guard:
            guard()
        try:
            return work()
        except Exception as exc:
            if attempt + 1 == attempts or not transient(exc):
                raise
            sleep(min(2 ** (attempt + 1), 8))
    raise AssertionError('Unreachable retry state')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp-' + str(os.getpid()))
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Journal:
    """Local state must stay in private storage, never in public GitHub."""
    def __init__(self, directory, identity):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', identity):
            raise ValueError('Invalid restart identity')
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / (identity + '.json')
        self.lock = self.directory / (identity + '.lock')

    @contextlib.contextmanager
    def locked(self):
        # OS lock releases on process death; the harmless lock file may remain.
        with self.lock.open('a+b') as stream:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0)
                if not stream.read(1):
                    stream.write(b'0'); stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield self
            finally:
                if os.name == 'nt':
                    stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def save(self, stage, record=None):
        payload = {'stage': stage, 'record': record}
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
        atomic_json(self.path, {'payload': payload, 'sha256': hashlib.sha256(body.encode()).hexdigest()})

    def prepared(self):
        if not self.path.exists():
            return None
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        body = json.dumps(saved['payload'], sort_keys=True, ensure_ascii=False, allow_nan=False)
        if hashlib.sha256(body.encode()).hexdigest() != saved['sha256']:
            raise ValueError('Restart state hash mismatch')
        return saved['payload'].get('record')
