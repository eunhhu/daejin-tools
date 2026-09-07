"""Private/local deployment entry point. Start with one worker; never auto-refresh."""

import hmac
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .booking import BookingService
from .parser import SessionExpired, SourceError
from .service import Cooldown, ScheduleService
from .source import KST, LibrarySource, session_client

STATIC = Path(__file__).parent / "static"


class PrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    room_code: str = Field(pattern=r"^[CSZ]\d{2}$")
    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: str = Field(min_length=20, max_length=100)
    end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    purpose: str = Field(min_length=1, max_length=300)
    confirmed: Literal[True]


def check_csrf(request, token):
    origin = str(request.base_url).rstrip("/")
    supplied = request.headers.get("x-library-csrf", "")
    if request.headers.get("origin") != origin or not hmac.compare_digest(
        supplied.encode(), token.encode()
    ):
        raise HTTPException(403, "이 페이지에서 예약 내용을 확인한 뒤 다시 진행해 줘.")


def create_app(service=None, bookings=None):
    if service is None:

        def client():
            cookie_file = os.environ.get("DAEJIN_LIBRARY_SESSION_FILE")
            if not cookie_file:
                raise SessionExpired("운영자가 도서관 로그인 세션을 연결해야 해.")
            return session_client(cookie_file)

        service = ScheduleService(LibrarySource(client))

        def state_path():
            session_file = os.environ.get("DAEJIN_LIBRARY_SESSION_FILE")
            if not session_file:
                raise SessionExpired("운영자가 도서관 세션을 연결해야 해.")
            return Path(session_file).with_name("library-booking-state.json")

        bookings = BookingService(client, service, state_path)
    csrf_token = secrets.token_urlsafe(32)
    app = FastAPI(
        title="Daejin Tools · 도서관 빈자리", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.schedule_service = service
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @app.middleware("http")
    async def private_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
        return response

    @app.get("/healthz")
    def health():
        return {"ok": True}

    @app.get("/api/config")
    def config():
        today = datetime.now(KST).date()
        return {
            "today": today.isoformat(),
            "last_date": (today + timedelta(days=6)).isoformat(),
            "timezone": "Asia/Seoul",
            "cache_seconds": 300,
            "csrf_token": csrf_token,
            "booking_enabled": bookings is not None,
        }

    @app.get("/api/schedule")
    def schedule(date: str):
        try:
            return service.get(date)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Cooldown as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": str(exc.seconds)}) from exc
        except SessionExpired as exc:
            raise HTTPException(503, str(exc)) from exc
        except SourceError as exc:
            raise HTTPException(502, str(exc)) from exc

    def booking_call(request, method, values):
        check_csrf(request, csrf_token)
        if bookings is None:
            raise HTTPException(503, "예약 기능이 연결되지 않았어.")
        try:
            return getattr(bookings, method)(**values)
        except SessionExpired as exc:
            raise HTTPException(503, str(exc)) from exc
        except SourceError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/booking/prepare")
    def prepare_booking(body: PrepareRequest, request: Request):
        return booking_call(
            request, "prepare", {"day": body.date, "code": body.room_code, "start": body.start}
        )

    @app.post("/api/booking/confirm")
    def confirm_booking(body: ConfirmRequest, request: Request):
        return booking_call(request, "confirm", body.model_dump())

    @app.get("/manual")
    def manual():
        return FileResponse(STATIC / "manual.html")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
