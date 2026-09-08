"""Read-only library adapter for one authenticated in-memory client."""

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from .parser import SessionExpired, SourceError, parse_rooms, parse_times

ORIGIN = "https://library.daejin.ac.kr"
READ_PATHS = frozenset({"/seminar_seminar_list.mir", "/seminar_resv.mir"})
KST = ZoneInfo("Asia/Seoul")
class LibrarySource:
    def __init__(self, client_factory, pause=lambda: None):
        # One request in flight; bounded batches need no arbitrary per-room sleep.
        self.client_factory = client_factory
        self.pause = pause

    def fetch(self, day):
        requests = 0
        started = datetime.now(KST).isoformat()
        with self.client_factory() as client:
            def read(path, data):
                nonlocal requests
                if path not in READ_PATHS:
                    raise SourceError("허용되지 않은 조회 경로야.")
                if requests:
                    self.pause()
                requests += 1
                try:
                    response = client.post(ORIGIN + path, data=data)
                except httpx.HTTPError as exc:
                    raise SourceError("도서관 연결에 실패했어.") from exc
                if response.is_redirect or response.status_code == 401:
                    raise SessionExpired("도서관 로그인이 만료됐어. 다시 로그인해 줘.")
                if response.status_code in {403, 429}:
                    raise SourceError("도서관에서 조회를 잠시 제한했어.")
                if response.status_code != 200 or len(response.content) > 2_000_000:
                    raise SourceError("도서관 응답을 확인할 수 없어. 잠시 후 다시 시도해 줘.")
                return response.text

            rooms = parse_rooms(read('/seminar_seminar_list.mir', {
                'sloc_code': 'DJUL', 'resv_use_start_datev': day.isoformat(),
                'resv_use_start_timev': '', 'resv_use_end_timev': '00:00:00', 'all_search_yn': 'Y',
            }))
            for room in rooms:
                html = read('/seminar_resv.mir', {
                    'sloc_code': 'DJUL', 'group_code': room['group'],
                    'seminar_code': room['code'], 'seminar_name': room['name'],
                    'resv_datev': day.isoformat(), 'year': str(day.year),
                    'month': f'{day.month:02d}', 'day': f'{day.day:02d}',
                    'min_personnel': str(room['minimum']), 'max_personnel': str(room['capacity']),
                })
                try:
                    room.update(parse_times(html, expected_day=day), state='ok')
                except SessionExpired:
                    raise
                except SourceError:
                    room.update(starts=[], step_minutes=30, state='unknown')
        return {'date': day.isoformat(), 'rooms': rooms, 'source_requests': requests,
                'started_at': started, 'checked_at': datetime.now(KST).isoformat()}
