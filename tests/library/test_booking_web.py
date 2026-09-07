import importlib

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


def test_booking_routes_and_manual_are_exposed_without_school_requests():
    web = importlib.import_module("apps.library.web")
    app = web.create_app(service=object(), bookings=object())
    paths = {r.path for r in app.routes}
    assert {"/api/booking/prepare", "/api/booking/confirm", "/manual"} <= paths
