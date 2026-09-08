"""Server-side browser sessions with isolated upstream state."""

import secrets
import tempfile
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, RLock

from .booking import BookingService
from .parser import SessionExpired
from .service import ScheduleService
from .source import LibrarySource

SESSION_COOKIE = "daejin_library_session"
IDLE_TTL_SECONDS = 8 * 60 * 60
MAX_SESSIONS = 100


def mask_account(account_id):
    if len(account_id) <= 2:
        return "*" * len(account_id)
    if len(account_id) <= 4:
        return account_id[0] + "*" * (len(account_id) - 1)
    return account_id[:2] + "*" * (len(account_id) - 4) + account_id[-2:]


def build_resources(client, operation_lock, journal_path, account_label):
    def client_factory():
        return nullcontext(client)

    schedule = ScheduleService(LibrarySource(client_factory))
    schedule.lock = operation_lock
    bookings = BookingService(
        client_factory,
        schedule,
        lambda: journal_path,
        account_label=account_label,
    )
    return schedule, bookings


@dataclass
class BrowserSession:
    token: str = field(repr=False)
    account_label: str
    client: object = field(repr=False)
    csrf_token: str = field(repr=False)
    journal_path: Path = field(repr=False)
    operation_lock: RLock = field(repr=False)
    schedule: ScheduleService = field(repr=False)
    bookings: BookingService = field(repr=False)
    last_seen: float
    _closed: bool = field(default=False, init=False, repr=False)

    def run(self, operation, *args, **kwargs):
        with self.operation_lock:
            if self._closed:
                raise SessionExpired("로그인 세션이 종료됐어. 다시 로그인해 줘.")
            return operation(*args, **kwargs)

    def close(self):
        with self.operation_lock:
            if self._closed:
                return
            self._closed = True
            try:
                self.client.close()
            except Exception:
                pass
            try:
                self.journal_path.unlink(missing_ok=True)
            except OSError:
                pass


class SessionLimit(Exception):
    pass


class SessionStore:
    def __init__(
        self,
        state_dir=None,
        clock=time.monotonic,
        idle_ttl=IDLE_TTL_SECONDS,
        max_sessions=MAX_SESSIONS,
        resource_factory=build_resources,
    ):
        self.state_dir = Path(
            state_dir or Path(tempfile.gettempdir()) / "daejin-library-sessions"
        )
        self.clock = clock
        self.idle_ttl = idle_ttl
        self.max_sessions = max_sessions
        self.resource_factory = resource_factory
        self._lock = Lock()
        self._sessions = {}
        self._closed = False

    @staticmethod
    def _close_sessions(sessions):
        for session in sessions:
            try:
                session.close()
            except Exception:
                pass

    @staticmethod
    def _close_client(client):
        try:
            client.close()
        except Exception:
            pass

    def create(self, account_id, client):
        self.cleanup()
        now = self.clock()
        journal_path = None
        try:
            with self._lock:
                if self._closed:
                    accepted = None
                elif len(self._sessions) >= self.max_sessions:
                    accepted = False
                else:
                    accepted = True
                    token = secrets.token_urlsafe(32)
                    while token in self._sessions:
                        token = secrets.token_urlsafe(32)
                    csrf_token = secrets.token_urlsafe(32)
                    journal_path = self.state_dir / f"booking-{secrets.token_hex(16)}.json"
                    operation_lock = RLock()
                    account_label = mask_account(account_id)
                    schedule, bookings = self.resource_factory(
                        client,
                        operation_lock,
                        journal_path,
                        account_label,
                    )
                    session = BrowserSession(
                        token=token,
                        account_label=account_label,
                        client=client,
                        csrf_token=csrf_token,
                        journal_path=journal_path,
                        operation_lock=operation_lock,
                        schedule=schedule,
                        bookings=bookings,
                        last_seen=now,
                    )
                    self._sessions[token] = session
        except Exception:
            self._close_client(client)
            if journal_path:
                journal_path.unlink(missing_ok=True)
            raise
        if accepted is None:
            self._close_client(client)
            raise RuntimeError("SessionStore is closed")
        if not accepted:
            self._close_client(client)
            raise SessionLimit
        return session

    def get(self, token, touch=True):
        expired = None
        now = self.clock()
        with self._lock:
            session = self._sessions.get(token)
            if session and now - session.last_seen >= self.idle_ttl:
                expired = self._sessions.pop(token)
                session = None
            elif session and touch:
                session.last_seen = now
        if expired:
            self._close_sessions([expired])
        return session

    def cleanup(self):
        now = self.clock()
        with self._lock:
            expired = [
                self._sessions.pop(token)
                for token, session in list(self._sessions.items())
                if now - session.last_seen >= self.idle_ttl
            ]
        self._close_sessions(expired)
        return len(expired)

    def remove(self, token):
        with self._lock:
            session = self._sessions.pop(token, None)
        if not session:
            return False
        self._close_sessions([session])
        return True

    def close(self):
        with self._lock:
            self._closed = True
            sessions = list(self._sessions.values())
            self._sessions.clear()
        self._close_sessions(sessions)
