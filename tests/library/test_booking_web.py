import importlib
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def test_mutation_requires_same_origin_and_page_csrf_token():
    web = importlib.import_module("apps.library.web")

    def req(origin, token):
        return Request(
            {
                "type": "http",
                "method": "POST",
                "scheme": "http",
                "path": "/api/booking/confirm",
                "headers": [
                    (b"host", b"localhost:18764"),
                    (b"origin", origin.encode()),
                    (b"x-library-csrf", token.encode()),
                ],
                "server": ("localhost", 18764),
            }
        )

    with pytest.raises(HTTPException):
        web.check_csrf(req("https://elsewhere.invalid", "synthetic"), "synthetic")
    with pytest.raises(HTTPException):
        web.check_csrf(req("http://localhost:18764", "wrong"), "synthetic")
    web.check_csrf(req("http://localhost:18764", "synthetic"), "synthetic")


def test_booking_routes_remain_but_the_site_manual_is_removed():
    web = importlib.import_module("apps.library.web")
    app = web.create_app(authenticator=object(), session_store=object())
    paths = {r.path for r in app.routes}
    assert {"/api/booking/prepare", "/api/booking/confirm", "/api/logout"} <= paths
    assert "/manual" not in paths
    assert not Path("apps/library/static/manual.html").exists()


def test_booking_confirmation_treats_an_omitted_optional_purpose_as_blank():
    web = importlib.import_module("apps.library.web")

    request = web.ConfirmRequest(
        ticket="synthetic-ticket-123456789",
        end="17:30",
        confirmed=True,
    )

    assert request.purpose == ""


def test_booking_confirmation_trims_purpose_before_validating_length():
    web = importlib.import_module("apps.library.web")

    request = web.ConfirmRequest(
        ticket="synthetic-ticket-123456789",
        end="17:30",
        purpose="학" * 300 + "   ",
        confirmed=True,
    )

    assert request.purpose == "학" * 300
