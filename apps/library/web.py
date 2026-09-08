"""Private loopback web app. Run behind the HTTPS proxy with exactly one worker."""

import hmac
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import (
    InvalidCredentials,
    LibraryAuthenticator,
    LoginAttemptLimiter,
    LoginRateLimited,
)
from .parser import SessionExpired, SourceError
from .service import Cooldown
from .sessions import (
    IDLE_TTL_SECONDS,
    SESSION_COOKIE,
    SessionLimit,
    SessionStore,
)
from .source import KST, ORIGIN

STATIC = Path(__file__).parent / "static"
LOGIN_CSRF_COOKIE = "daejin_library_login_csrf"
PEER_LOGIN_ATTEMPTS = 60
ACCOUNT_LOGIN_ATTEMPTS = 10
_LOGIN_ACCOUNT_KEY = secrets.token_bytes(32)
PUBLIC_ASSETS = frozenset(
    {"app.js", "booking-ui.js", "login.js", "model.js", "style.css", "booking.css"}
)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)


class PrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    room_code: str = Field(pattern=r"^[CSZ]\d{2}$")
    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: str = Field(min_length=20, max_length=100)
    end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    purpose: str = Field(default="", min_length=0, max_length=300)
    confirmed: Literal[True]

    @field_validator("purpose", mode="before")
    @classmethod
    def trim_purpose(cls, value):
        return value.strip() if isinstance(value, str) else value


def new_upstream_client():
    return httpx.Client(
        timeout=httpx.Timeout(12, connect=5),
        follow_redirects=False,
        trust_env=False,
        headers={
            "User-Agent": "DaejinTools/0.1 (signed-in room availability)",
            "Referer": ORIGIN + "/seminar_seminar_list.mir",
        },
    )


def check_csrf(request, token, expected_origin=None):
    origin = expected_origin or str(request.base_url).rstrip("/")
    supplied = request.headers.get("x-library-csrf", "")
    if (
        not token
        or not supplied
        or request.headers.get("origin") != origin
        or not hmac.compare_digest(supplied.encode(), token.encode())
    ):
        raise HTTPException(403, "이 페이지에서 다시 시도해 줘.")


def _public_origin(required=False):
    value = os.environ.get("DAEJIN_LIBRARY_PUBLIC_ORIGIN")
    if not value:
        if required:
            raise ValueError("DAEJIN_LIBRARY_PUBLIC_ORIGIN is required")
        return None
    try:
        origin = urlsplit(value)
        hostname = origin.hostname
    except ValueError as exc:
        raise ValueError(
            "DAEJIN_LIBRARY_PUBLIC_ORIGIN must be one exact HTTPS origin"
        ) from exc
    if (
        origin.scheme != "https"
        or not hostname
        or "*" in origin.netloc
        or origin.username is not None
        or origin.password is not None
        or origin.path
        or origin.query
        or origin.fragment
        or value != f"https://{hostname}"
    ):
        raise ValueError("DAEJIN_LIBRARY_PUBLIC_ORIGIN must be one exact HTTPS origin")
    return value


def create_app(authenticator=None, session_store=None, login_limiter=None, account_limiter=None):
    using_default_services = authenticator is None and session_store is None
    public_origin = _public_origin(required=using_default_services)
    authenticator = authenticator or LibraryAuthenticator(new_upstream_client)
    login_limiter = login_limiter or LoginAttemptLimiter(max_attempts=PEER_LOGIN_ATTEMPTS)
    account_limiter = account_limiter or LoginAttemptLimiter(
        max_attempts=ACCOUNT_LOGIN_ATTEMPTS
    )
    session_store = session_store or SessionStore(
        state_dir=os.environ.get("DAEJIN_LIBRARY_STATE_DIR")
    )

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            session_store.close()

    app = FastAPI(
        title="Daejin Tools · 도서관 빈자리",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.session_store = session_store

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path == "/api/login":
            return JSONResponse({"detail": "로그인 정보를 확인해 줘."}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    allowed_hosts = ["127.0.0.1", "localhost", "[::1]"]
    if public_origin:
        allowed_hosts.append(urlsplit(public_origin).hostname)
    else:
        allowed_hosts.append("testserver")

    def expected_origin(request):
        if public_origin:
            return public_origin
        if request.url.hostname == "testserver":
            return "https://testserver"
        return str(request.base_url).rstrip("/")

    def set_session_cookie(response, token):
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=IDLE_TTL_SECONDS,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )

    def clear_session_cookie(response):
        response.delete_cookie(
            SESSION_COOKIE,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )

    @app.middleware("http")
    async def session_and_private_headers(request, call_next):
        token = request.cookies.get(SESSION_COOKIE, "")
        browser_session = session_store.get(token) if token else None
        request.state.library_session = browser_session
        request.state.clear_library_session = bool(token and not browser_session)
        preflight_error = None
        if request.method == "POST" and request.url.path == "/api/login":
            try:
                check_csrf(
                    request,
                    request.cookies.get(LOGIN_CSRF_COOKIE, ""),
                    expected_origin(request),
                )
            except HTTPException as exc:
                preflight_error = exc
        elif request.method == "POST" and request.url.path in {
            "/api/logout",
            "/api/booking/prepare",
            "/api/booking/confirm",
        }:
            if not browser_session:
                preflight_error = HTTPException(401, "로그인이 필요해.")
            else:
                try:
                    check_csrf(request, browser_session.csrf_token, expected_origin(request))
                except HTTPException as exc:
                    preflight_error = exc
        response = (
            JSONResponse(
                {"detail": preflight_error.detail},
                status_code=preflight_error.status_code,
                headers=preflight_error.headers,
            )
            if preflight_error
            else await call_next(request)
        )
        current_session = request.state.library_session
        if request.state.clear_library_session:
            clear_session_cookie(response)
        elif current_session and session_store.get(current_session.token, touch=False) is current_session:
            set_session_cookie(response, current_session.token)
        elif token:
            clear_session_cookie(response)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
        return response

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    def require_session(request):
        browser_session = request.state.library_session
        if not browser_session:
            raise HTTPException(401, "로그인이 필요해.")
        return browser_session

    def expire_session(request, browser_session):
        session_store.remove(browser_session.token)
        request.state.library_session = None
        request.state.clear_library_session = True

    @app.get("/healthz")
    def health():
        return {"ok": True}

    @app.get("/login")
    def login_page(request: Request):
        if request.state.library_session:
            return RedirectResponse("/", status_code=303)
        token = secrets.token_urlsafe(32)
        response = FileResponse(STATIC / "login.html")
        response.set_cookie(
            LOGIN_CSRF_COOKIE,
            token,
            max_age=600,
            httponly=False,
            secure=True,
            samesite="lax",
            path="/",
        )
        return response

    @app.post("/api/login")
    def login(body: LoginRequest, request: Request):
        csrf_token = request.cookies.get(LOGIN_CSRF_COOKIE, "")
        check_csrf(request, csrf_token, expected_origin(request))
        account_id = body.account_id.strip()
        if not account_id:
            raise HTTPException(401, "아이디 또는 비밀번호를 확인해 줘.")
        peer = request.client.host if request.client else "unknown"
        try:
            login_limiter.check(peer)
            account_key = hmac.digest(
                _LOGIN_ACCOUNT_KEY,
                account_id.encode("utf-8"),
                "sha256",
            ).hex()
            account_limiter.check(account_key)
        except LoginRateLimited as exc:
            raise HTTPException(
                429,
                str(exc),
                headers={"Retry-After": str(exc.seconds)},
            ) from exc
        try:
            client = authenticator.login(account_id, body.password.get_secret_value())
        except InvalidCredentials as exc:
            raise HTTPException(401, str(exc)) from exc
        except (httpx.HTTPError, SourceError) as exc:
            raise HTTPException(502, "로그인할 수 없어. 잠시 후 다시 시도해 줘.") from exc
        if request.state.library_session:
            session_store.remove(request.state.library_session.token)
        try:
            browser_session = session_store.create(account_id, client)
        except SessionLimit as exc:
            raise HTTPException(503, "현재 로그인 사용자가 많아. 잠시 후 다시 시도해 줘.") from exc
        request.state.library_session = browser_session
        request.state.clear_library_session = False
        response = JSONResponse(
            {"ok": True, "account_label": browser_session.account_label}
        )
        response.delete_cookie(
            LOGIN_CSRF_COOKIE,
            secure=True,
            samesite="lax",
            path="/",
        )
        return response

    @app.get("/api/config")
    def config(request: Request):
        browser_session = require_session(request)
        today = datetime.now(KST).date()
        return {
            "today": today.isoformat(),
            "last_date": (today + timedelta(days=6)).isoformat(),
            "timezone": "Asia/Seoul",
            "cache_seconds": browser_session.schedule.TTL,
            "csrf_token": browser_session.csrf_token,
            "booking_enabled": browser_session.bookings is not None,
            "account_label": browser_session.account_label,
        }

    @app.post("/api/logout")
    def logout(request: Request):
        browser_session = require_session(request)
        check_csrf(request, browser_session.csrf_token, expected_origin(request))
        session_store.remove(browser_session.token)
        request.state.library_session = None
        request.state.clear_library_session = True
        return {"ok": True}

    @app.get("/api/schedule")
    def schedule(request: Request, date: str | None = None):
        browser_session = require_session(request)
        if date is None:
            raise HTTPException(422, "날짜 형식은 YYYY-MM-DD여야 해.")
        try:
            return browser_session.run(browser_session.schedule.get, date)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Cooldown as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": str(exc.seconds)}) from exc
        except SessionExpired as exc:
            expire_session(request, browser_session)
            raise HTTPException(401, "도서관 로그인이 만료됐어. 다시 로그인해 줘.") from exc
        except SourceError as exc:
            raise HTTPException(502, str(exc)) from exc

    def booking_call(request, method, values):
        browser_session = require_session(request)
        check_csrf(request, browser_session.csrf_token, expected_origin(request))
        if browser_session.bookings is None:
            raise HTTPException(503, "예약 기능을 사용할 수 없어.")
        try:
            return browser_session.run(getattr(browser_session.bookings, method), **values)
        except SessionExpired as exc:
            expire_session(request, browser_session)
            raise HTTPException(401, "도서관 로그인이 만료됐어. 다시 로그인해 줘.") from exc
        except SourceError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/booking/prepare")
    def prepare_booking(body: PrepareRequest, request: Request):
        return booking_call(
            request,
            "prepare",
            {"day": body.date, "code": body.room_code, "start": body.start},
        )

    @app.post("/api/booking/confirm")
    def confirm_booking(body: ConfirmRequest, request: Request):
        return booking_call(request, "confirm", body.model_dump())

    @app.get("/")
    def index(request: Request):
        if not request.state.library_session:
            return RedirectResponse("/login", status_code=303)
        return FileResponse(STATIC / "index.html")

    @app.get("/static/{asset_name}")
    def static_asset(asset_name: str):
        if asset_name not in PUBLIC_ASSETS:
            raise HTTPException(404)
        return FileResponse(STATIC / asset_name)

    return app
