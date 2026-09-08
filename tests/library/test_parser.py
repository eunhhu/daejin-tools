"""Synthetic fixtures model observed HTML shapes; no account HTML is committed."""

from importlib import import_module

import pytest


def parser():
    return import_module("apps.library.parser")


def test_room_list_reads_only_expected_read_only_navigation_and_deduplicates():
    html = """
    <a onclick="seminar_resv('/seminar_resv.mir','DJUL','C','C01','캐럴1실','1','1'); return false;">Room</a>
    <a onclick="seminar_resv('/seminar_resv.mir','DJUL','C','C01','캐럴1실','1','1'); return false;">duplicate</a>
    <a onclick="other_action('/secret')">Ignore</a>
    """
    rooms = parser().parse_rooms(html)
    assert len(rooms) == 1
    assert rooms[0] == {
        "code": "C01", "group": "C", "name": "캐럴1실", "minimum": 1, "capacity": 1
    }


def test_selectable_starts_do_not_include_disabled_options_or_invent_end_times():
    html = '''<input id="service_term" value="30">
    <select id="start_time"><option value="">선택</option>
    <option value="17:00">17:00</option><option value="17:30">17:30</option>
    <option value="18:00" disabled>18:00</option></select>'''
    result = parser().parse_times(html)
    assert result == {"starts": ["17:00", "17:30"], "step_minutes": 30}
    assert "ends" not in result


@pytest.mark.parametrize("html", ["<html>Error</html>", '<select id="start_time"><option value="99:99">bad</option></select>'])
def test_malformed_times_fail_closed(html):
    with pytest.raises(parser().SourceError):
        parser().parse_times(html)


def test_empty_disabled_select_is_known_unavailable_not_a_fetch_error():
    result = parser().parse_times('<input id="service_term" value="30"><select id="start_time" disabled></select>')
    assert result["starts"] == []


def test_option_without_value_uses_text_like_the_browser():
    result = parser().parse_times('''<input id="service_term" value="30"><select id="start_time">
    <option id="startTime_1">17:00</option><option id="startTime_2">17:30</option>
    </select>''')
    assert result['starts'] == ['17:00', '17:30']


def test_server_echoed_date_must_match_requested_date():
    html = '''<script>var year = 2026; var month = 09; var day = 07;</script>
    <input id="service_term" value="30"><select id="start_time"><option>17:00</option></select>'''
    from datetime import date
    with pytest.raises(parser().SourceError):
        parser().parse_times(html, expected_day=date(2026, 9, 8))
    assert parser().parse_times(html, expected_day=date(2026, 9, 7))['starts'] == ['17:00']


def test_observed_closed_booking_notice_is_known_unavailable():
    html = '''<input id="service_term" value="30"><select id="start_time">
    <option>예약이 마감되었습니다</option></select>'''
    assert parser().parse_times(html) == {"starts": [], "step_minutes": 30}


@pytest.mark.parametrize("attributes", ['value=""', "disabled", 'value="" disabled'])
def test_closed_booking_notice_uses_visible_text_even_with_empty_or_disabled_value(attributes):
    html = f'''<input id="service_term" value="30"><select id="start_time">
    <option {attributes}>예약이 마감되었습니다</option>
    <option value="not-a-time">stale option</option></select>'''
    assert parser().parse_times(html) == {"starts": [], "step_minutes": 30}


def test_login_html_is_not_an_empty_room_list():
    with pytest.raises(parser().SessionExpired, match="도서관 로그인이 필요해. 다시 로그인해 줘"):
        parser().parse_rooms('<input id="home_login_password_login01" type="password">')
