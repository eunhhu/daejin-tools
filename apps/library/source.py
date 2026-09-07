"""On-demand read-only library adapter; no login, timers, retries or reservations."""

import json
import os
import stat
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from .parser import SessionExpired, SourceError, parse_rooms, parse_times

ORIGIN = "https://library.daejin.ac.kr"
READ_PATHS = frozenset({"/seminar_seminar_list.mir", "/seminar_resv.mir"})
KST = ZoneInfo("Asia/Seoul")


def session_client(path):
    """Read a narrowly scoped CDP-cookie export only when a visitor requests data."""
    try:
        path = Path(path)
        if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise SourceError("세션 파일 권한을 600으로 제한해야 해.")
        cookies = json.loads(path.read_text(encoding="utf-8"))
        jar = httpx.Cookies()
        for cookie in cookies:
            if cookie['domain'].lstrip('.') == 'library.daejin.ac.kr':
                jar.set(cookie['name'], cookie['value'], domain='library.daejin.ac.kr',
                        path=cookie.get('path', '/'))
        if not jar:
            raise SessionExpired("도서관 로그인 세션이 없어.")
        return httpx.Client(cookies=jar, timeout=httpx.Timeout(12, connect=5),
                            follow_redirects=False, trust_env=False,
                            headers={'User-Agent': 'DaejinTools/0.1 (on-demand room availability)',
                                     'Referer': ORIGIN + '/seminar_seminar_list.mir'})
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise SessionExpired("도서관 세션 파일을 읽을 수 없어. 운영자의 갱신이 필요해.") from exc


class LibrarySource:
    def __init__(self, client_factory, pause=lambda: time.sleep(0.5)):
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
                    raise SourceError("도서관 연결에 실패했어. 자동 재시도하지 않아.") from exc
                if response.is_redirect or response.status_code == 401:
                    raise SessionExpired("도서관 로그인이 만료됐어. 운영자의 세션 갱신이 필요해.")
                if response.status_code in {403, 429}:
                    raise SourceError("도서관에서 조회를 제한했어. 추가 요청을 중단했어.")
                if response.status_code != 200 or len(response.content) > 2_000_000:
                    raise SourceError("도서관 응답을 확인할 수 없어. 잠시 후 직접 다시 시도해 줘.")
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
