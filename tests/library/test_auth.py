from importlib import import_module
from urllib.parse import parse_qs

import httpx
import pytest

ROOM_LIST = """
<a onclick="seminar_resv('/seminar_resv.mir','DJUL','S','S01','테스트실','1','8'); return false;">
  테스트실
</a>
"""


def test_authenticator_performs_exact_login_flow_and_returns_isolated_cookie_client():
    auth = import_module("apps.library.auth")
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/home_login_write.mir":
            return httpx.Response(200, text='<input type="password">')
        if request.url.path == "/home_security_login_write_prss.mir":
            return httpx.Response(
                302,
                headers={
                    "Location": "/",
                    "Set-Cookie": "JSESSIONID=browser-one; Path=/; HttpOnly",
                },
            )
        assert request.headers["cookie"] == "JSESSIONID=browser-one"
        return httpx.Response(200, text=ROOM_LIST)

    authenticator = auth.LibraryAuthenticator(
        lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    )
    client = authenticator.login("20261234", "synthetic-password")

    assert [(request.method, request.url.path) for request in seen] == [
        ("GET", "/home_login_write.mir"),
        ("POST", "/home_security_login_write_prss.mir"),
        ("POST", "/seminar_seminar_list.mir"),
    ]
    assert parse_qs(seen[1].content.decode()) == {
        "home_login_mloc_code": ["DJUL"],
        "home_login_id": ["20261234"],
        "home_login_password": ["synthetic-password"],
        "home_login_id_save_yn": ["N"],
        "login_type": ["portal_member"],
    }
    assert client.cookies.get("JSESSIONID") == "browser-one"
    assert client.follow_redirects is False
    assert "synthetic-password" not in repr(authenticator.__dict__)
    client.close()


def test_login_page_verification_is_a_generic_invalid_credential_failure_and_closes_client():
    auth = import_module("apps.library.auth")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text='<form><input type="password"></form>')
        ),
        follow_redirects=False,
    )

    with pytest.raises(auth.InvalidCredentials, match="아이디 또는 비밀번호를 확인해 줘"):
        auth.LibraryAuthenticator(lambda: client).login("20261234", "wrong-password")

    assert client.is_closed is True


def test_non_login_html_without_a_valid_room_list_is_generic_invalid_credentials():
    auth = import_module("apps.library.auth")

    def handler(request):
        if request.url.path == "/home_login_write.mir":
            return httpx.Response(200, text='<input type="password">')
        if request.url.path == "/home_security_login_write_prss.mir":
            return httpx.Response(302, headers={"Location": "/"})
        return httpx.Response(200, text="<html><body>unexpected page</body></html>")

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )

    with pytest.raises(auth.InvalidCredentials, match="아이디 또는 비밀번호를 확인해 줘"):
        auth.LibraryAuthenticator(lambda: client).login("20261234", "wrong-password")

    assert client.is_closed is True


def test_malformed_seminar_list_and_network_failures_are_generic_source_errors():
    auth = import_module("apps.library.auth")

    malformed = """
    <a onclick="seminar_resv('/seminar_resv.mir','DJUL','S','S01','테스트실','0','8')">
      테스트실
    </a>
    """

    def malformed_handler(request):
        if request.url.path == "/home_login_write.mir":
            return httpx.Response(200, text='<input type="password">')
        if request.url.path == "/home_security_login_write_prss.mir":
            return httpx.Response(302, headers={"Location": "/"})
        return httpx.Response(200, text=malformed)

    malformed_client = httpx.Client(
        transport=httpx.MockTransport(malformed_handler),
        follow_redirects=False,
    )
    with pytest.raises(auth.SourceError) as malformed_exc:
        auth.LibraryAuthenticator(lambda: malformed_client).login(
            "20261234", "synthetic-password"
        )
    assert "20261234" not in str(malformed_exc.value)
    assert "synthetic-password" not in str(malformed_exc.value)
    assert malformed_client.is_closed is True

    def network_failure(request):
        raise httpx.ConnectError("synthetic connection failure", request=request)

    network_client = httpx.Client(
        transport=httpx.MockTransport(network_failure),
        follow_redirects=False,
    )
    with pytest.raises(auth.SourceError) as network_exc:
        auth.LibraryAuthenticator(lambda: network_client).login(
            "20261234", "synthetic-password"
        )
    assert "20261234" not in str(network_exc.value)
    assert "synthetic-password" not in str(network_exc.value)
    assert network_client.is_closed is True


def test_login_attempt_limiter_has_a_bounded_window_and_retry_after():
    auth = import_module("apps.library.auth")
    clock = [0.0]
    limiter = auth.LoginAttemptLimiter(
        max_attempts=2,
        window_seconds=60,
        clock=lambda: clock[0],
    )

    limiter.check("direct-peer")
    limiter.check("direct-peer")
    with pytest.raises(auth.LoginRateLimited) as exc:
        limiter.check("direct-peer")

    assert exc.value.seconds == 60
    clock[0] = 60
    limiter.check("direct-peer")


def test_unexpected_authentication_failure_still_closes_the_temporary_client():
    auth = import_module("apps.library.auth")

    def fail(_request):
        raise RuntimeError("synthetic unexpected failure")

    client = httpx.Client(
        transport=httpx.MockTransport(fail),
        follow_redirects=False,
    )

    with pytest.raises(RuntimeError, match="synthetic unexpected failure"):
        auth.LibraryAuthenticator(lambda: client).login(
            "20261234",
            "synthetic-password",
        )

    assert client.is_closed is True
