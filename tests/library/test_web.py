from importlib import import_module
from pathlib import Path

import pytest
from fastapi import HTTPException


class FakeService:
    def __init__(self):
        self.calls = 0

    def get(self, day):
        self.calls += 1
        if day == 'bad':
            raise ValueError('bad date')
        return {'date': day, 'rooms': []}


def endpoint(app, path):
    return next(route.endpoint for route in app.routes if route.path == path)


def test_app_boot_health_and_shell_do_not_fetch_but_schedule_does():
    mod = import_module('apps.library.web')
    service = FakeService()
    app = mod.create_app(service)
    assert endpoint(app, '/healthz')()['ok'] is True
    assert Path(endpoint(app, '/')().path).is_file()
    assert service.calls == 0
    assert endpoint(app, '/api/schedule')('2026-09-07')['date'] == '2026-09-07'
    assert service.calls == 1
    assert not any('reserve' in route.path or 'cancel' in route.path for route in app.routes)
    with pytest.raises(HTTPException) as exc:
        endpoint(app, '/api/schedule')('bad')
    assert exc.value.status_code == 422
