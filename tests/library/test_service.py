from concurrent.futures import ThreadPoolExecutor
from datetime import date
from importlib import import_module

import pytest

from apps.library.parser import SourceError

DAY = date(2026, 9, 7)


class FakeSource:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def fetch(self, day):
        self.calls += 1
        if self.fail:
            raise SourceError('연결 실패')
        return {'date': day.isoformat(), 'rooms': [], 'checked_at': '2026-09-07T10:00:00+09:00'}


def service(source, clock):
    cls = import_module('apps.library.service').ScheduleService
    return cls(source, clock=lambda: clock[0], today=lambda: DAY)


def test_only_explicit_visits_fetch_and_cache_is_shared_between_concurrent_visits():
    source, clock = FakeSource(), [0]
    cache = service(source, clock)
    assert source.calls == 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: cache.get('2026-09-07'), range(8)))
    assert source.calls == 1
    assert len(results) == 8
    clock[0] = 301
    assert source.calls == 1  # time passing alone must not refresh
    assert cache.get('2026-09-07')['cached'] is False
    assert source.calls == 2


def test_failed_refresh_returns_honestly_stale_data_without_retry_loop():
    source, clock = FakeSource(), [0]
    cache = service(source, clock)
    first = cache.get('2026-09-07')
    clock[0], source.fail = 301, True
    stale = cache.get('2026-09-07')
    assert stale['stale'] is True
    assert stale['warning'] == '연결 실패'
    assert stale['checked_at'] == first['checked_at']
    cache.get('2026-09-07')
    assert source.calls == 2


@pytest.mark.parametrize('value', ['2026-02-30', '2026-9-7', '2026-09-06', '2026-09-14', '../../secret'])
def test_invalid_or_out_of_window_dates_never_reach_library(value):
    source, clock = FakeSource(), [0]
    with pytest.raises(ValueError):
        service(source, clock).get(value)
    assert source.calls == 0


def test_changing_dates_cannot_bypass_global_request_budget():
    source, clock = FakeSource(), [0]
    cache = service(source, clock)
    cache.get('2026-09-07')
    with pytest.raises(SourceError):
        cache.get('2026-09-08')
    assert source.calls == 1
    for index in range(1, 6):
        clock[0] = index * 31
        cache.get(f'2026-09-{7 + index:02d}')
    clock[0] = 301
    with pytest.raises(SourceError):
        cache.get('2026-09-13')
    assert source.calls == 6
