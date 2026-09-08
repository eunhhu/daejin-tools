import asyncio
import warnings
from importlib import import_module

import pytest
from starlette.exceptions import StarletteDeprecationWarning

with warnings.catch_warnings():
    warnings.simplefilter("ignore", StarletteDeprecationWarning)
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        message=r"The anyio\.abc\.BlockingPortal alias is deprecated.*",
    )
    from fastapi.testclient import TestClient


class FakeService:
    TTL = 60

    def __init__(self):
        self.calls = 0

    def get(self, day):
        self.calls += 1
        if day == 'bad':
            raise ValueError('bad date')
        return {'date': day, 'rooms': []}


@pytest.mark.enable_socket
def test_health_and_login_assets_are_public_but_app_work_waits_for_authenticated_schedule(tmp_path):
    web = import_module("apps.library.web")
    sessions = import_module("apps.library.sessions")
    service = FakeService()

    def resources(client, operation_lock, journal_path, account_label):
        return service, object()

    app = web.create_app(
        authenticator=FreshClientAuthenticator(),
        session_store=sessions.SessionStore(state_dir=tmp_path, resource_factory=resources),
    )
    client = TestClient(app, base_url="https://localhost")
    try:
        assert client.get("/healthz").status_code == 200
        assert client.get("/login").status_code == 200
        assert client.get("/static/login.js").status_code == 200
        assert client.get("/static/index.html").status_code == 404
        assert client.get("/", follow_redirects=False).status_code == 303
        assert client.get("/api/config").status_code == 401
        assert client.get("/api/schedule").status_code == 401
        assert service.calls == 0

        assert login_browser(client, web).status_code == 200
        assert client.get("/").status_code == 200
        assert service.calls == 0
        assert client.get("/api/schedule").status_code == 422
        assert service.calls == 0
        assert client.get("/api/schedule?date=2026-09-08").json()["date"] == "2026-09-08"
        assert service.calls == 1
    finally:
        client.close()


class FakeAuthenticatedClient:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


@pytest.mark.enable_socket
def test_exceptional_lifespan_shutdown_still_closes_every_session(tmp_path):
    web = import_module("apps.library.web")
    sessions = import_module("apps.library.sessions")
    upstream = FakeAuthenticatedClient()
    store = sessions.SessionStore(state_dir=tmp_path)
    store.create("20261234", upstream)
    app = web.create_app(authenticator=object(), session_store=store)

    async def fail_during_lifespan():
        with pytest.raises(RuntimeError, match="synthetic lifespan failure"):
            async with app.router.lifespan_context(app):
                raise RuntimeError("synthetic lifespan failure")

    asyncio.run(fail_during_lifespan())

    assert upstream.closed is True
    assert store._closed is True
    assert store._sessions == {}


class FakeAuthenticator:
    def __init__(self):
        self.calls = []
        self.client = FakeAuthenticatedClient()

    def login(self, account_id, password):
        self.calls.append((account_id, password))
        return self.client


class FreshClientAuthenticator:
    def __init__(self):
        self.clients = []

    def login(self, account_id, password):
        client = FakeAuthenticatedClient()
        self.clients.append(client)
        return client


class RejectingAuthenticator:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def login(self, account_id, password):
        self.calls += 1
        raise self.error()


def login_browser(client, web, account_id="20261234"):
    client.get("/login")
    token = client.cookies.get(web.LOGIN_CSRF_COOKIE)
    return client.post(
        "/api/login",
        headers={"Origin": "https://localhost", "X-Library-CSRF": token},
        json={"account_id": account_id, "password": "synthetic-password"},
    )


@pytest.mark.enable_socket
def test_login_is_public_and_success_creates_a_secure_isolated_browser_session(tmp_path):
    web = import_module("apps.library.web")
    sessions = import_module("apps.library.sessions")
    authenticator = FakeAuthenticator()
    store = sessions.SessionStore(state_dir=tmp_path)
    app = web.create_app(authenticator=authenticator, session_store=store)

    with TestClient(app, base_url="https://localhost") as client:
        assert client.get("/healthz").status_code == 200
        login_page = client.get("/login")
        assert login_page.status_code == 200
        assert 'id="school-account"' in login_page.text
        assert client.get("/", follow_redirects=False).headers["location"] == "/login"
        assert client.get("/api/config").status_code == 401

        preauth_token = client.cookies.get(web.LOGIN_CSRF_COOKIE)
        response = client.post(
            "/api/login",
            headers={"Origin": "https://localhost", "X-Library-CSRF": preauth_token},
            json={"account_id": "20261234", "password": "synthetic-password"},
        )

        assert response.status_code == 200
        assert authenticator.calls == [("20261234", "synthetic-password")]
        assert response.json()["account_label"] != "20261234"
        cookie = response.headers["set-cookie"]
        assert web.SESSION_COOKIE in cookie
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=lax" in cookie
        assert "Path=/" in cookie
        assert "Max-Age=28800" in cookie
        assert "synthetic-password" not in response.text

        assert client.get("/").status_code == 200
        config = client.get("/api/config").json()
        assert config["account_label"] == response.json()["account_label"]
        assert len(config["csrf_token"]) >= 43
        stored = next(iter(store._sessions.values()))
        assert not hasattr(stored, "account_id")
        assert not hasattr(stored, "password")
        assert "20261234" not in repr(stored)
        assert "synthetic-password" not in repr(stored)


@pytest.mark.enable_socket
def test_same_account_browsers_are_independent_and_logout_closes_only_one(tmp_path):
    web = import_module("apps.library.web")
    sessions = import_module("apps.library.sessions")
    authenticator = FreshClientAuthenticator()
    store = sessions.SessionStore(state_dir=tmp_path)
    app = web.create_app(authenticator=authenticator, session_store=store)
    first = TestClient(app, base_url="https://localhost")
    second = TestClient(app, base_url="https://localhost")
    try:
        assert login_browser(first, web).status_code == 200
        assert login_browser(second, web).status_code == 200
        first_config = first.get("/api/config").json()
        second_config = second.get("/api/config").json()
        assert first_config["account_label"] == second_config["account_label"]
        assert first_config["csrf_token"] != second_config["csrf_token"]
        assert len(store._sessions) == 2

        response = first.post(
            "/api/logout",
            headers={
                "Origin": "https://localhost",
                "X-Library-CSRF": first_config["csrf_token"],
            },
        )

        assert response.status_code == 200
        assert first.get("/api/config").status_code == 401
        assert second.get("/api/config").status_code == 200
        assert authenticator.clients[0].closed is True
        assert authenticator.clients[1].closed is False
        assert len(store._sessions) == 1
    finally:
        first.close()
        second.close()
        store.close()


@pytest.mark.enable_socket
def test_login_requires_nonempty_same_origin_preauth_csrf(tmp_path):
    web = import_module("apps.library.web")
    sessions = import_module("apps.library.sessions")
    authenticator = FreshClientAuthenticator()
    app = web.create_app(
        authenticator=authenticator,
        session_store=sessions.SessionStore(state_dir=tmp_path),
    )
    client = TestClient(app, base_url="https://localhost")
    try:
        response = client.post(
            "/api/login",
            headers={"Origin": "https://localhost"},
            json={"account_id": "20261234", "password": "synthetic-password"},
        )
        assert response.status_code == 403
        assert authenticator.clients == []

        client.get("/login")
        token = client.cookies.get(web.LOGIN_CSRF_COOKIE)
        response = client.post(
            "/api/login",
            headers={"Origin": "https://evil.invalid", "X-Library-CSRF": token},
            json={"account_id": "20261234", "password": "synthetic-password"},
        )
        assert response.status_code == 403
        assert authenticator.clients == []
    finally:
        client.close()


@pytest.mark.enable_socket
def test_login_attempt_limit_ignores_forwarded_identity_headers(tmp_path):
    web = import_module("apps.library.web")
    auth = import_module("apps.library.auth")
    sessions = import_module("apps.library.sessions")
    authenticator = RejectingAuthenticator(auth.InvalidCredentials)
    limiter = auth.LoginAttemptLimiter(max_attempts=2, window_seconds=60, clock=lambda: 0)
    app = web.create_app(
        authenticator=authenticator,
        session_store=sessions.SessionStore(state_dir=tmp_path),
        login_limiter=limiter,
    )
    client = TestClient(app, base_url="https://localhost")
    try:
        client.get("/login")
        token = client.cookies.get(web.LOGIN_CSRF_COOKIE)
        for forwarded in ("198.51.100.1", "198.51.100.2"):
            response = client.post(
                "/api/login",
                headers={
                    "Origin": "https://localhost",
                    "X-Library-CSRF": token,
                    "X-Forwarded-For": forwarded,
                },
                json={"account_id": "20261234", "password": "wrong-password"},
            )
            assert response.status_code == 401
            assert response.json() == {"detail": "아이디 또는 비밀번호를 확인해 줘."}

        response = client.post(
            "/api/login",
            headers={
                "Origin": "https://localhost",
                "X-Library-CSRF": token,
                "X-Forwarded-For": "203.0.113.9",
            },
            json={"account_id": "20261234", "password": "wrong-password"},
        )
        assert response.status_code == 429
        assert response.headers["retry-after"] == "60"
        assert authenticator.calls == 2
    finally:
        client.close()


@pytest.mark.enable_socket
def test_per_account_limit_does_not_lock_other_accounts_behind_the_same_peer(tmp_path):
    web = import_module("apps.library.web")
    auth = import_module("apps.library.auth")
    sessions = import_module("apps.library.sessions")
    authenticator = RejectingAuthenticator(auth.InvalidCredentials)
    app = web.create_app(
        authenticator=authenticator,
        session_store=sessions.SessionStore(state_dir=tmp_path),
    )
    client = TestClient(app, base_url="https://localhost")
    try:
        client.get("/login")
        token = client.cookies.get(web.LOGIN_CSRF_COOKIE)
        headers = {"Origin": "https://localhost", "X-Library-CSRF": token}
        for _ in range(10):
            assert client.post(
                "/api/login",
                headers=headers,
                json={"account_id": "20261234", "password": "wrong-password"},
            ).status_code == 401

        assert client.post(
            "/api/login",
            headers=headers,
            json={"account_id": "20261234", "password": "wrong-password"},
        ).status_code == 429
        assert client.post(
            "/api/login",
            headers=headers,
            json={"account_id": "20265678", "password": "wrong-password"},
        ).status_code == 401
        assert authenticator.calls == 11
    finally:
        client.close()


@pytest.mark.enable_socket
def test_rotating_accounts_hit_peer_limit_and_account_keys_are_keyed_digests(tmp_path):
    web = import_module("apps.library.web")
    auth = import_module("apps.library.auth")
    sessions = import_module("apps.library.sessions")
    authenticator = RejectingAuthenticator(auth.InvalidCredentials)
    peer_limiter = auth.LoginAttemptLimiter(max_attempts=3, window_seconds=60, clock=lambda: 0)
    account_limiter = auth.LoginAttemptLimiter(
        max_attempts=10,
        window_seconds=60,
        clock=lambda: 0,
    )
    app = web.create_app(
        authenticator=authenticator,
        session_store=sessions.SessionStore(state_dir=tmp_path),
        login_limiter=peer_limiter,
        account_limiter=account_limiter,
    )
    client = TestClient(app, base_url="https://localhost")
    try:
        client.get("/login")
        token = client.cookies.get(web.LOGIN_CSRF_COOKIE)
        headers = {"Origin": "https://localhost", "X-Library-CSRF": token}
        account_ids = ["20261234", "20265678", "20269012"]
        for account_id in account_ids:
            assert client.post(
                "/api/login",
                headers=headers,
                json={"account_id": account_id, "password": "wrong-password"},
            ).status_code == 401

        assert client.post(
            "/api/login",
            headers=headers,
            json={"account_id": "20269999", "password": "wrong-password"},
        ).status_code == 429
        keys = list(account_limiter._attempts)
        assert len(keys) == 3
        assert all(len(key) == 64 for key in keys)
        assert all(account_id not in repr(keys) for account_id in account_ids)
        assert "wrong-password" not in repr(account_limiter.__dict__)
        assert authenticator.calls == 3
    finally:
        client.close()


@pytest.mark.enable_socket
def test_school_session_expiry_invalidates_only_the_calling_browser(tmp_path):
    web = import_module("apps.library.web")
    sessions = import_module("apps.library.sessions")
    from apps.library.parser import SessionExpired

    authenticator = FreshClientAuthenticator()
    store = sessions.SessionStore(state_dir=tmp_path)
    app = web.create_app(authenticator=authenticator, session_store=store)
    first = TestClient(app, base_url="https://localhost")
    second = TestClient(app, base_url="https://localhost")
    try:
        assert login_browser(first, web).status_code == 200
        assert login_browser(second, web).status_code == 200
        first_token = first.cookies.get(web.SESSION_COOKIE)

        class ExpiredSchedule:
            TTL = 60

            def get(self, day):
                raise SessionExpired("synthetic expiry")

        store.get(first_token, touch=False).schedule = ExpiredSchedule()
        response = first.get("/api/schedule?date=2026-09-08")

        assert response.status_code == 401
        assert response.json() == {"detail": "도서관 로그인이 만료됐어. 다시 로그인해 줘."}
        assert first.get("/", follow_redirects=False).headers["location"] == "/login"
        assert second.get("/api/config").status_code == 200
        assert authenticator.clients[0].closed is True
        assert authenticator.clients[1].closed is False
        assert len(store._sessions) == 1
    finally:
        first.close()
        second.close()
        store.close()


@pytest.mark.enable_socket
def test_successful_relogin_replaces_the_old_session_cookie(tmp_path):
    web = import_module("apps.library.web")
    sessions = import_module("apps.library.sessions")
    authenticator = FreshClientAuthenticator()
    store = sessions.SessionStore(state_dir=tmp_path)
    app = web.create_app(authenticator=authenticator, session_store=store)
    client = TestClient(app, base_url="https://localhost")
    try:
        assert login_browser(client, web).status_code == 200
        old_token = client.cookies.get(web.SESSION_COOKIE)
        client.cookies.set(web.LOGIN_CSRF_COOKIE, "replacement-csrf")

        response = client.post(
            "/api/login",
            headers={
                "Origin": "https://localhost",
                "X-Library-CSRF": "replacement-csrf",
            },
            json={"account_id": "20265678", "password": "synthetic-password"},
        )

        assert response.status_code == 200
        assert client.cookies.get(web.SESSION_COOKIE) != old_token
        assert client.get("/api/config").status_code == 200
        assert authenticator.clients[0].closed is True
        assert authenticator.clients[1].closed is False
        assert len(store._sessions) == 1
    finally:
        client.close()
        store.close()


@pytest.mark.enable_socket
def test_login_input_bounds_never_echo_passwords_or_call_upstream(tmp_path):
    web = import_module("apps.library.web")
    sessions = import_module("apps.library.sessions")
    authenticator = FreshClientAuthenticator()
    app = web.create_app(
        authenticator=authenticator,
        session_store=sessions.SessionStore(state_dir=tmp_path),
    )
    client = TestClient(app, base_url="https://localhost")
    try:
        client.get("/login")
        token = client.cookies.get(web.LOGIN_CSRF_COOKIE)
        secret = "p" * 129
        response = client.post(
            "/api/login",
            headers={"Origin": "https://localhost", "X-Library-CSRF": token},
            json={"account_id": "20261234", "password": secret},
        )

        assert response.status_code == 422
        assert secret not in response.text
        assert authenticator.clients == []
    finally:
        client.close()


@pytest.mark.enable_socket
def test_mutation_origin_and_csrf_checks_precede_body_validation(tmp_path):
    web = import_module("apps.library.web")
    sessions = import_module("apps.library.sessions")
    authenticator = FreshClientAuthenticator()
    app = web.create_app(
        authenticator=authenticator,
        session_store=sessions.SessionStore(state_dir=tmp_path),
    )
    client = TestClient(app, base_url="https://localhost")
    try:
        client.get("/login")
        preauth = client.cookies.get(web.LOGIN_CSRF_COOKIE)
        response = client.post(
            "/api/login",
            headers={"Origin": "https://evil.invalid", "X-Library-CSRF": preauth},
            json={"account_id": "x" * 65, "password": "p" * 129},
        )
        assert response.status_code == 403
        assert authenticator.clients == []

        assert login_browser(client, web).status_code == 200
        csrf = client.get("/api/config").json()["csrf_token"]
        response = client.post(
            "/api/booking/confirm",
            headers={"Origin": "https://evil.invalid", "X-Library-CSRF": csrf},
            json={},
        )
        assert response.status_code == 403
        response = client.post(
            "/api/booking/confirm",
            headers={"Origin": "https://localhost", "X-Library-CSRF": "wrong"},
            json={},
        )
        assert response.status_code == 403
    finally:
        client.close()


@pytest.mark.enable_socket
def test_disabled_booking_service_returns_controlled_unavailable(tmp_path):
    web = import_module("apps.library.web")
    sessions = import_module("apps.library.sessions")

    def resources(client, operation_lock, journal_path, account_label):
        return FakeService(), None

    app = web.create_app(
        authenticator=FreshClientAuthenticator(),
        session_store=sessions.SessionStore(state_dir=tmp_path, resource_factory=resources),
    )
    client = TestClient(app, base_url="https://localhost", raise_server_exceptions=False)
    try:
        assert login_browser(client, web).status_code == 200
        csrf = client.get("/api/config").json()["csrf_token"]
        headers = {"Origin": "https://localhost", "X-Library-CSRF": csrf}

        prepare = client.post(
            "/api/booking/prepare",
            headers=headers,
            json={"date": "2026-09-08", "room_code": "S01", "start": "17:00"},
        )
        confirm = client.post(
            "/api/booking/confirm",
            headers=headers,
            json={
                "ticket": "synthetic-ticket-123456789",
                "end": "17:30",
                "purpose": "",
                "confirmed": True,
            },
        )

        for response in (prepare, confirm):
            assert response.status_code == 503
            assert response.json() == {"detail": "예약 기능을 사용할 수 없어."}
    finally:
        client.close()
