"""All booking responses below are synthetic. No school reservations are created."""

from datetime import datetime
from importlib import import_module
from threading import Lock
from types import SimpleNamespace

import httpx

DAY = "2026-09-07"
ROOM = dict(code="S01", group="S", name="테스트실", minimum=1, capacity=8)
DETAIL = """<script>var year=2026; var month=09; var day=07; initPersonNumber = 0;</script>
<input name="seminar_name" value="세미나실 → 테스트실">
<input id="service_term" value="30"><input id="resv_able_end_time" value="168">
<select id="start_time"><option>17:00</option></select><textarea id="use_purpose"></textarea>
<button onclick="seminar_resv_check('/seminar_resv_check.mir','DJUL','S','S01',initPersonNumber)">예약</button>"""
ENDS = '<select id="end_time"><option>17:30</option><option>18:00</option></select>'
EMPTY = '<div id="content"><table><tbody></tbody></table></div>'
HISTORY = """<div id="content"><table><tr><td><a onclick="seminar_use_info('/seminar_use_info.mir','DJUL','S','123')">
테스트실 2026-09-07 17:00~17:30 예약중</a></td></tr></table></div>"""


def harness(tmp_path, mutate_timeout=False, refuse=False):
    from apps.library.source import KST

    mod = import_module("apps.library.booking")
    calls, writes = [], []

    def handler(request):
        path = request.url.path
        calls.append(path)
        if path == "/seminar_resv.mir":
            text = DETAIL
        elif path == "/seminar_end_time_list.mir":
            text = ENDS
        elif path == "/seminar_use_history_list.mir":
            text = HISTORY if writes else EMPTY
        elif path == "/seminar_resv_check.mir":
            text = "당일 예약이 이미 있어요." if refuse else ""
        elif path == "/seminar_resv_prss.mir":
            writes.append(request.content)
            if mutate_timeout:
                raise httpx.ReadTimeout("synthetic ambiguous response")
            text = "<html>처리 후 이동</html>"
        else:
            raise AssertionError(path)
        return httpx.Response(200, text=text)

    def factory():
        return httpx.Client(
            transport=httpx.MockTransport(handler), cookies={"JSESSIONID": "synthetic"}
        )

    schedule = SimpleNamespace(lock=Lock(), cache={DAY: (0, {"rooms": [ROOM]})})
    b = mod.BookingService(
        factory,
        schedule,
        lambda: tmp_path / "booking-state.json",
        now=lambda: datetime(2026, 9, 7, 12, tzinfo=KST),
        pause=lambda: None,
    )
    return b, calls, writes


def test_preparing_never_books_and_only_explicit_confirm_books_once(tmp_path):
    b, calls, writes = harness(tmp_path)
    q = b.prepare(DAY, "S01", "17:00")
    assert q["ends"] == ["17:30", "18:00"]
    assert not writes
    assert calls == ["/seminar_resv.mir", "/seminar_end_time_list.mir"]
    result = b.confirm(q["ticket"], "17:30", "개인 학습", True)
    assert result["status"] == "confirmed" and result["reservation_id"] == "123"
    assert len(writes) == 1
    assert b.confirm(q["ticket"], "17:30", "개인 학습", True) == result
    assert len(writes) == 1


def test_old_journal_cannot_claim_success_after_upstream_booking_disappears(tmp_path):
    b, calls, writes = harness(tmp_path)
    q = b.prepare(DAY, "S01", "17:00")
    b.confirm(q["ticket"], "17:30", "학습", True)
    writes.clear()  # Synthetic upstream no longer reports this booking.
    assert b.confirm(q["ticket"], "17:30", "학습", True)["status"] == "unknown"
    assert not writes


def test_ambiguous_submission_is_not_retried_even_after_restart(tmp_path):
    b, calls, writes = harness(tmp_path, mutate_timeout=True)
    q = b.prepare(DAY, "S01", "17:00")
    assert b.confirm(q["ticket"], "17:30", "학습", True)["status"] == "unknown"
    assert len(writes) == 1
    restarted, calls2, writes2 = harness(tmp_path)
    q2 = restarted.prepare(DAY, "S01", "17:00")
    assert restarted.confirm(q2["ticket"], "17:30", "학습", True)["status"] == "unknown"
    assert not writes2


def test_ambiguous_booking_blocks_a_different_end_after_restart(tmp_path):
    b, calls, writes = harness(tmp_path, mutate_timeout=True)
    q = b.prepare(DAY, "S01", "17:00")
    b.confirm(q["ticket"], "17:30", "학습", True)
    restarted, calls2, writes2 = harness(tmp_path)
    q2 = restarted.prepare(DAY, "S01", "17:00")
    assert restarted.confirm(q2["ticket"], "18:00", "학습", True)["status"] == "unknown"
    assert not writes2


def test_school_rejection_stops_before_mutation(tmp_path):
    b, calls, writes = harness(tmp_path, refuse=True)
    q = b.prepare(DAY, "S01", "17:00")
    assert b.confirm(q["ticket"], "17:30", "학습", True)["status"] == "rejected"
    assert not writes


def test_unapproved_end_missing_confirmation_and_expired_ticket_never_submit(tmp_path):
    import pytest

    from apps.library.parser import SourceError

    b, calls, writes = harness(tmp_path)
    q = b.prepare(DAY, "S01", "17:00")
    for end, purpose, confirm in [
        ("19:00", "학습", True),
        ("17:30", "학습", False),
        ("17:30", "", True),
    ]:
        with pytest.raises(SourceError):
            b.confirm(q["ticket"], end, purpose, confirm)
    b.tickets[q["ticket"]]["expires"] = 0
    with pytest.raises(SourceError):
        b.confirm(q["ticket"], "17:30", "학습", True)
    assert not writes
    assert calls == ["/seminar_resv.mir", "/seminar_end_time_list.mir"]


def test_confirm_requests_are_bounded_even_for_repeated_tickets(tmp_path):
    import pytest

    from apps.library.parser import SourceError

    b, calls, writes = harness(tmp_path)
    q = b.prepare(DAY, "S01", "17:00")
    for _ in range(12):
        b.confirm(q["ticket"], "17:30", "학습", True)
    before = len(calls)
    with pytest.raises(SourceError):
        b.confirm(q["ticket"], "17:30", "학습", True)
    assert len(calls) == before
    assert len(writes) == 1


def test_cancelled_or_different_room_history_is_not_success():
    mod = import_module("apps.library.booking")
    assert (
        mod.booking_history(HISTORY.replace("예약중", "예약취소"), ROOM, DAY, "17:00", "17:30")
        is None
    )
    assert mod.booking_history(HISTORY, {**ROOM, "name": "다른실"}, DAY, "17:00", "17:30") is None
