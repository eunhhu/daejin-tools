from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
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
    clock[0] = cache.TTL + 1
    assert source.calls == 1  # time passing alone must not refresh
    assert cache.get('2026-09-07')['cached'] is False
    assert source.calls == 2


def test_failed_refresh_returns_honestly_stale_data_without_retry_loop():
    source, clock = FakeSource(), [0]
    cache = service(source, clock)
    first = cache.get('2026-09-07')
    clock[0], source.fail = cache.TTL + 1, True
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


def test_concurrent_date_navigation_serializes_and_reuses_each_date():
    source, clock = FakeSource(), [0]
    cache = service(source, clock)
    days = [(DAY + timedelta(days=index % 7)).isoformat() for index in range(21)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(cache.get, days))
    assert [item['date'] for item in results] == days
    assert sum(not item['cached'] for item in results) == 7
    assert source.calls == 7


def test_source_failure_still_blocks_other_dates_but_keeps_fresh_cache():
    from apps.library.service import Cooldown

    source, clock = FakeSource(), [0]
    cache = service(source, clock)
    cache.get('2026-09-07')
    source.fail = True
    with pytest.raises(SourceError, match='연결 실패'):
        cache.get('2026-09-08')
    assert cache.get('2026-09-07')['cached'] is True
    with pytest.raises(Cooldown, match='연결 실패') as exc:
        cache.get('2026-09-09')
    assert exc.value.seconds == cache.FAILURE_COOLDOWN
    assert source.calls == 2
    source.fail = False
    clock[0] = cache.FAILURE_COOLDOWN
    assert cache.get('2026-09-08')['cached'] is False
    assert source.calls == 3


def test_full_visible_week_can_be_browsed_immediately_and_back_uses_cache():
    source, clock = FakeSource(), [0]
    cache = service(source, clock)
    days = [(DAY + timedelta(days=index)).isoformat() for index in range(7)]
    for day in days:
        result = cache.get(day)
        assert result['date'] == day
        assert result['cached'] is False
        assert result['stale'] is False
    assert source.calls == 7
    for day in reversed(days):
        result = cache.get(day)
        assert result['date'] == day
        assert result['cached'] is True
        assert not result['warning']
    assert source.calls == 7


def test_local_budget_reports_its_own_limit_with_rounded_up_wait():
    from apps.library.service import Cooldown

    source, clock = FakeSource(), [0.0]
    cache = service(source, clock)
    cache.BATCHES_PER_HOUR = 1
    cache.get('2026-09-07')
    clock[0] = 0.25
    with pytest.raises(Cooldown) as exc:
        cache.get('2026-09-08')
    assert '시간표 조회 한도' in str(exc.value)
    assert '3600초' in str(exc.value)
    assert exc.value.seconds == 3600
    assert source.calls == 1


def test_expired_source_error_is_not_used_to_label_a_local_budget_limit():
    from apps.library.service import Cooldown

    source, clock = FakeSource(), [0]
    source.fail = True
    cache = service(source, clock)
    cache.BATCHES_PER_HOUR = 1
    with pytest.raises(SourceError, match='연결 실패'):
        cache.get('2026-09-07')
    clock[0] = cache.FAILURE_COOLDOWN + 1
    with pytest.raises(Cooldown) as exc:
        cache.get('2026-09-08')
    assert '시간표 조회 한도' in str(exc.value)
    assert '연결 실패' not in str(exc.value)
    assert source.calls == 1


def test_changing_dates_cannot_bypass_per_session_request_budget():
    source, clock = FakeSource(), [0]
    cache = service(source, clock)
    days = [(DAY + timedelta(days=index)).isoformat() for index in range(7)]
    for index in range(cache.BATCHES_PER_HOUR):
        clock[0] = (index // len(days)) * cache.TTL
        assert cache.get(days[index % len(days)])['cached'] is False
    assert source.calls == cache.BATCHES_PER_HOUR
    clock[0] += cache.TTL
    for day in days:
        result = cache.get(day)
        assert result['cached'] is True
        assert result['stale'] is True
        assert result['warning']
    assert source.calls == cache.BATCHES_PER_HOUR
    clock[0] = 3600
    assert cache.get(days[0])['cached'] is False
    assert source.calls == cache.BATCHES_PER_HOUR + 1


def test_schedule_policy_uses_short_cache_stale_window_and_failure_cooldown():
    from apps.library.service import Cooldown, ScheduleService

    current_day = date(2026, 9, 8)
    source, clock = FakeSource(), [0.0]
    cache = ScheduleService(
        source,
        clock=lambda: clock[0],
        today=lambda: current_day,
    )

    assert cache.TTL == 60
    assert cache.STALE_LIMIT == 300
    assert cache.BATCHES_PER_HOUR == 60
    assert cache.FAILURE_COOLDOWN == 15

    cache.get("2026-09-08")
    clock[0] = 60
    source.fail = True
    stale = cache.get("2026-09-08")
    assert stale["stale"] is True
    assert source.calls == 2
    clock[0] = 70
    with pytest.raises(Cooldown) as exc:
        cache.get("2026-09-09")
    assert exc.value.seconds == 5
    assert source.calls == 2
    clock[0] = 75
    source.fail = False
    assert cache.get("2026-09-09")["cached"] is False
    assert source.calls == 3


def test_school_session_expiry_bypasses_stale_cache_and_failure_cooldown():
    from apps.library.parser import SessionExpired
    from apps.library.service import ScheduleService

    class ExpiringSource:
        def __init__(self):
            self.expired = False

        def fetch(self, day):
            if self.expired:
                raise SessionExpired("synthetic expiry")
            return {
                "date": day.isoformat(),
                "rooms": [],
                "checked_at": "2026-09-08T10:00:00+09:00",
            }

    source, clock = ExpiringSource(), [0.0]
    cache = ScheduleService(
        source,
        clock=lambda: clock[0],
        today=lambda: date(2026, 9, 8),
    )
    cache.get("2026-09-08")
    clock[0] = cache.TTL + 1
    source.expired = True

    with pytest.raises(SessionExpired, match="synthetic expiry"):
        cache.get("2026-09-08")

    assert cache.cache == {}
    assert cache.cool_until == 0
    assert cache.last_error == ""
