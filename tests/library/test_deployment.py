"""Public-origin configuration behind an authenticated loopback proxy."""

import warnings
from pathlib import Path

import pytest
from starlette.exceptions import StarletteDeprecationWarning
from starlette.middleware.trustedhost import TrustedHostMiddleware

from apps.library.web import create_app

with warnings.catch_warnings():
    warnings.simplefilter("ignore", StarletteDeprecationWarning)
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        message=r"The anyio\.abc\.BlockingPortal alias is deprecated.*",
    )
    from fastapi.testclient import TestClient


def test_configured_https_origin_adds_only_the_exact_public_host(monkeypatch):
    monkeypatch.setenv("DAEJIN_LIBRARY_PUBLIC_ORIGIN", "https://library-daejin.qucord.com")
    app = create_app()
    hosts = next(
        m.kwargs["allowed_hosts"] for m in app.user_middleware if m.cls is TrustedHostMiddleware
    )
    assert "library-daejin.qucord.com" in hosts
    assert "*" not in hosts
    assert "other.invalid" not in hosts


def test_default_app_requires_an_explicit_public_origin(monkeypatch):
    monkeypatch.delenv("DAEJIN_LIBRARY_PUBLIC_ORIGIN", raising=False)

    with pytest.raises(ValueError, match="PUBLIC_ORIGIN"):
        create_app()


def test_public_origin_must_be_a_single_https_origin(monkeypatch):
    for value in (
        "*",
        "http://library-daejin.qucord.com",
        "https://*.qucord.com",
        "https://Library-Daejin.qucord.com",
        "https://library-daejin.qucord.com:443",
        "https://library-daejin.qucord.com/",
        "https://user:pass@example.com",
        "https://example.com/path",
        "https://example.com?x=1",
        "https://example.com#x",
    ):
        monkeypatch.setenv("DAEJIN_LIBRARY_PUBLIC_ORIGIN", value)
        with pytest.raises(ValueError, match="PUBLIC_ORIGIN"):
            create_app()


def test_trusted_host_middleware_is_outermost(monkeypatch):
    monkeypatch.setenv("DAEJIN_LIBRARY_PUBLIC_ORIGIN", "https://library-daejin.qucord.com")

    app = create_app()

    assert app.user_middleware[0].cls is TrustedHostMiddleware


def test_visible_runtime_copy_has_no_operator_or_retry_alarm_language():
    paths = [
        Path("apps/library/auth.py"),
        Path("apps/library/booking.py"),
        Path("apps/library/parser.py"),
        Path("apps/library/service.py"),
        Path("apps/library/source.py"),
        Path("apps/library/web.py"),
        Path("apps/library/static/index.html"),
        Path("apps/library/static/app.js"),
        Path("apps/library/static/booking-ui.js"),
        Path("apps/library/static/login.html"),
        Path("apps/library/static/login.js"),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "운영자" not in text
    assert "자동 재시도" not in text
    assert "자동 갱신 없음" not in text


def test_library_docs_describe_individual_sessions_and_current_limits():
    text = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in ("apps/library/README.md", "apps/library/USER_GUIDE.md")
    )
    assert "DAEJIN_LIBRARY_SESSION_FILE" not in text
    assert "/manual" not in text
    assert "개별" in text
    assert "8시간" in text
    assert "60초" in text
    assert "5분" in text
    assert "시간당 60" in text
    assert "--workers 1" in text


@pytest.mark.enable_socket
def test_public_origin_binds_csrf_and_private_headers_to_the_exact_host(monkeypatch):
    origin = "https://library-daejin.qucord.com"
    monkeypatch.setenv("DAEJIN_LIBRARY_PUBLIC_ORIGIN", origin)
    app = create_app()
    client = TestClient(app, base_url=origin)
    try:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.headers["cache-control"] == "no-store"
        assert health.headers["x-robots-tag"] == "noindex, nofollow"
        assert "frame-ancestors 'none'" in health.headers["content-security-policy"]
        assert client.get("/healthz", headers={"Host": "other.invalid"}).status_code == 400

        client.get("/login")
        token = client.cookies.get("daejin_library_login_csrf")
        wrong = client.post(
            "/api/login",
            headers={"Origin": "https://other.invalid", "X-Library-CSRF": token},
            json={"account_id": "x" * 65, "password": "p" * 129},
        )
        assert wrong.status_code == 403
        exact = client.post(
            "/api/login",
            headers={"Origin": origin, "X-Library-CSRF": token},
            json={"account_id": "x" * 65, "password": "p" * 129},
        )
        assert exact.status_code == 422
    finally:
        client.close()
