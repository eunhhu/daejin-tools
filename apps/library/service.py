"""Bounded request-time cache. No background tasks or automatic refresh."""

import copy
import time
from collections import deque
from datetime import date, datetime
from threading import Lock

from .parser import SourceError
from .source import KST


class Cooldown(SourceError):
    def __init__(self, seconds, message='학교 요청을 줄이기 위해 잠시 대기 중이야.'):
        super().__init__(message)
        self.seconds = max(1, int(seconds))


class ScheduleService:
    TTL = 300
    STALE_LIMIT = 1800
    MIN_BATCH_GAP = 30
    BATCHES_PER_HOUR = 6

    def __init__(self, source, clock=time.monotonic, today=lambda: datetime.now(KST).date()):
        self.source = source
        self.clock = clock
        self.today = today
        self.lock = Lock()
        self.cache = {}
        self.batches = deque()
        self.cool_until = 0
        self.last_error = ''

    def get(self, value):
        try:
            day = date.fromisoformat(value)
        except (ValueError, TypeError) as exc:
            raise ValueError('날짜 형식은 YYYY-MM-DD여야 해.') from exc
        if day.isoformat() != value or not 0 <= (day - self.today()).days <= 6:
            raise ValueError('조회는 한국 시간 기준 오늘부터 7일 이내만 지원해.')
        # One lock for all dates: concurrent visitors cannot multiply upstream batches.
        with self.lock:
            now = self.clock()
            self.cache = {key: item for key, item in self.cache.items()
                          if now - item[0] <= self.STALE_LIMIT}
            cached = self.cache.get(value)

            def result(item, *, hit, warning=''):
                stamp, data = item
                return dict(copy.deepcopy(data), cached=hit,
                            age_seconds=max(0, int(self.clock() - stamp)),
                            stale=bool(warning), warning=warning,
                            cache_ttl_seconds=self.TTL)

            if cached and now - cached[0] < self.TTL:
                return result(cached, hit=True)
            while self.batches and now - self.batches[0] >= 3600:
                self.batches.popleft()
            wait = max(0, self.cool_until - now)
            if self.batches:
                wait = max(wait, self.MIN_BATCH_GAP - (now - self.batches[-1]))
            if len(self.batches) >= self.BATCHES_PER_HOUR:
                wait = max(wait, 3600 - (now - self.batches[0]))
            if wait > 0:
                message = self.last_error or '학교 요청 한도 보호 중이야. 잠시 후 직접 새로고침해 줘.'
                if cached:
                    return result(cached, hit=True, warning=message)
                raise Cooldown(wait, message)
            self.batches.append(now)
            try:
                data = self.source.fetch(day)
            except SourceError as exc:
                self.cool_until = self.clock() + self.TTL
                self.last_error = str(exc)
                if cached:
                    return result(cached, hit=True, warning=str(exc))
                raise
            self.last_error = ''
            self.cool_until = 0
            self.cache[value] = (self.clock(), data)
            return result(self.cache[value], hit=False)
