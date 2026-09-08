"""Parse only room metadata and selectable times. Never execute upstream HTML/JS."""

import re

from bs4 import BeautifulSoup


class SourceError(Exception):
    """Upstream could not supply trustworthy availability."""


class SessionExpired(SourceError):
    """The current browser must establish a new library login."""


def document(html):
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one('input[type="password"]') or re.search(
        r"(?:location(?:\.href)?\s*=|location\.replace\()\s*['\"][^'\"]*home_login", html
    ):
        raise SessionExpired("도서관 로그인이 필요해. 다시 로그인해 줘.")
    return soup


ROOM_LINK = re.compile(
    r"^seminar_resv\(\s*'/seminar_resv\.mir'\s*,\s*'DJUL'\s*,\s*'([CSZ])'\s*,"
    r"\s*'([CSZ]\d{2})'\s*,\s*'([^'\r\n]{1,80})'\s*,\s*'(\d{1,3})'\s*,\s*'(\d{1,3})'\s*\)"
)


def parse_rooms(html):
    soup = document(html)
    rooms = {}
    for anchor in soup.select('a[onclick]'):
        match = ROOM_LINK.match(anchor['onclick'])
        if not match:
            continue
        group, code, name, minimum, capacity = match.groups()
        if not (code.startswith(group) and 1 <= int(minimum) <= int(capacity) <= 999):
            raise SourceError("호실 정보 형식이 변경됐어.")
        room = dict(code=code, group=group, name=name, minimum=int(minimum), capacity=int(capacity))
        if code in rooms and rooms[code] != room:
            raise SourceError("중복된 호실 정보가 일치하지 않아.")
        rooms[code] = room
    if not rooms or len(rooms) > 30:
        raise SourceError("예약실 목록을 확인할 수 없어. 원본 페이지를 확인해 줘.")
    return list(rooms.values())


def parse_times(html, expected_day=None):
    soup = document(html)
    if expected_day is not None:
        dates = re.findall(
            r"var\s+year\s*=\s*(\d{4})\s*;\s*var\s+month\s*=\s*(\d{1,2})\s*;"
            r"\s*var\s+day\s*=\s*(\d{1,2})\s*;", html
        )
        expected = (expected_day.year, expected_day.month, expected_day.day)
        if len(dates) != 1 or tuple(map(int, dates[0])) != expected:
            raise SourceError("요청한 날짜와 원본 화면의 날짜가 일치하지 않아.")
    select = soup.select_one('#start_time')
    step = soup.select_one('#service_term')
    if select is None or step is None or step.get('value') not in {'10', '15', '20', '30', '60'}:
        raise SourceError("선택 가능한 시간을 확인할 수 없어.")
    starts = set()
    options = select.select('option')
    if any(option.get_text(" ", strip=True) == "예약이 마감되었습니다" for option in options):
        return {'starts': [], 'step_minutes': int(step['value'])}
    if not select.has_attr('disabled'):
        for option in options:
            value = option.get('value', option.get_text()).strip()
            if not value or option.has_attr('disabled'):
                continue
            if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
                raise SourceError("시간 표시 형식이 변경됐어.")
            starts.add(value)
    return {'starts': sorted(starts), 'step_minutes': int(step['value'])}
