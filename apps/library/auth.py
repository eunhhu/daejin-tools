"""In-memory Daejin library authentication with no credential persistence."""

import math
import time
from collections import deque
from datetime import datetime
from threading import Lock

import httpx

from .parser import SessionExpired, SourceError, parse_rooms
from .source import KST, ORIGIN

LOGIN_PAGE = "/home_login_write.mir"
LOGIN_PROCESS = "/home_security_login_write_prss.mir"
SEMINAR_LIST = "/seminar_seminar_list.mir"


class InvalidCredentials(Exception):
    """The supplied school account could not be authenticated."""

    def __init__(self):
        super().__init__("아이디 또는 비밀번호가 올바르지 않습니다.")


class LoginRateLimited(Exception):
    def __init__(self, seconds):
        self.seconds = max(1, math.ceil(seconds))
        super().__init__(
            f"로그인 시도 횟수가 많습니다. {self.seconds}초 후 다시 시도할 수 있습니다."
        )


class LoginAttemptLimiter:
    def __init__(
        self,
        max_attempts=10,
        window_seconds=300,
        max_keys=1024,
        clock=time.monotonic,
    ):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self.clock = clock
        self._attempts = {}
        self._last_seen = {}
        self._lock = Lock()

    def check(self, key):
        now = self.clock()
        with self._lock:
            attempts = self._attempts.setdefault(key, deque())
            while attempts and now - attempts[0] >= self.window_seconds:
                attempts.popleft()
            if len(attempts) >= self.max_attempts:
                raise LoginRateLimited(self.window_seconds - (now - attempts[0]))
            attempts.append(now)
            self._last_seen[key] = now
            if len(self._attempts) > self.max_keys:
                oldest = min(self._last_seen, key=self._last_seen.get)
                if oldest != key:
                    self._attempts.pop(oldest, None)
                    self._last_seen.pop(oldest, None)


class LibraryAuthenticator:
    def __init__(self, client_factory, today=lambda: datetime.now(KST).date()):
        self.client_factory = client_factory
        self.today = today

    def login(self, account_id, password):
        client = self.client_factory()
        try:
            try:
                day = self.today()
                page = client.get(ORIGIN + LOGIN_PAGE, follow_redirects=False)
                if page.status_code != 200 or len(page.content) > 2_000_000:
                    raise SourceError("로그인 페이지를 불러올 수 없습니다.")
                client.post(
                    ORIGIN + LOGIN_PROCESS,
                    data={
                        "home_login_mloc_code": "DJUL",
                        "home_login_id": account_id,
                        "home_login_password": password,
                        "home_login_id_save_yn": "N",
                        "login_type": "portal_member",
                    },
                    follow_redirects=False,
                )
                response = client.post(
                    ORIGIN + SEMINAR_LIST,
                    data={
                        "sloc_code": "DJUL",
                        "resv_use_start_datev": day.isoformat(),
                        "resv_use_start_timev": "",
                        "resv_use_end_timev": "00:00:00",
                        "all_search_yn": "Y",
                    },
                    follow_redirects=False,
                )
            except httpx.HTTPError as exc:
                raise SourceError("도서관 연결에 실패했습니다.") from exc
            if response.is_redirect or response.status_code == 401:
                raise InvalidCredentials
            if response.status_code != 200 or len(response.content) > 2_000_000:
                raise SourceError("로그인 확인 요청을 처리할 수 없습니다.")
            try:
                parse_rooms(response.text)
            except SessionExpired as exc:
                raise InvalidCredentials from exc
            except SourceError as exc:
                if "seminar_resv(" not in response.text:
                    raise InvalidCredentials from exc
                raise
            return client
        except Exception:
            client.close()
            raise
