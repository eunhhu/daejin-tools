from datetime import date
from importlib import import_module
from urllib.parse import parse_qs

import httpx
import pytest

LIST = """<a onclick="seminar_resv('/seminar_resv.mir','DJUL','C','C01','캐럴1실','1','1');">방</a>"""
DETAIL = '<script>var year = 2026; var month = 09; var day = 07;</script><input id="service_term" value="30"><select id="start_time"><option value="17:00">17:00</option></select>'


def test_source_exposes_no_operator_cookie_file_loader():
    module = import_module("apps.library.source")
    assert not hasattr(module, "session_client")


def test_source_uses_only_read_only_allowlist_and_fetches_each_room_once():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=LIST if 'list.mir' in request.url.path else DETAIL)
    module = import_module('apps.library.source')
    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = module.LibrarySource(lambda: client, pause=lambda: None)
    assert not requests  # construction does not fetch or warm anything
    result = source.fetch(date(2026, 9, 7))
    assert len(requests) == 2
    assert [r.url.path for r in requests] == ['/seminar_seminar_list.mir', '/seminar_resv.mir']
    assert all(r.url.host == 'library.daejin.ac.kr' for r in requests)
    assert parse_qs(requests[1].content.decode())['resv_datev'] == ['2026-09-07']
    assert result['rooms'][0]['starts'] == ['17:00']
    assert result['source_requests'] == 2
    assert result['rooms'][0]['state'] == 'ok'


def test_default_full_batch_has_no_artificial_sleep_and_no_duplicate_requests(monkeypatch):
    import time

    sleeps = []
    monkeypatch.setattr(time, 'sleep', sleeps.append)
    codes = [f'C{n:02d}' for n in range(1, 11)] + [f'S{n:02d}' for n in range(1, 10)] + ['Z01']
    listing = ''.join(
        f'''<a onclick="seminar_resv('/seminar_resv.mir','DJUL','{code[0]}','{code}','방 {code}','1','1');">방</a>'''
        for code in codes
    )
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, text=listing if 'list.mir' in request.url.path else DETAIL)

    module = import_module('apps.library.source')
    source = module.LibrarySource(lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    assert not seen
    result = source.fetch(date(2026, 9, 7))
    assert sleeps == []
    assert len(seen) == result['source_requests'] == len(codes) + 1
    assert [parse_qs(r.content.decode())['seminar_code'][0] for r in seen[1:]] == codes
    assert len({r['code'] for r in result['rooms']}) == len(codes)


@pytest.mark.parametrize('failure', [401, 403, 429, 'timeout'])
def test_fast_batch_stops_at_first_upstream_failure_without_later_rooms(failure):
    codes = ['C01', 'C02', 'C03']
    listing = ''.join(
        f'''<a onclick="seminar_resv('/seminar_resv.mir','DJUL','C','{code}','방 {code}','1','1');">방</a>'''
        for code in codes
    )
    seen = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(200, text=listing)
        if len(seen) == 3:
            if failure == 'timeout':
                raise httpx.ReadTimeout('synthetic timeout', request=request)
            return httpx.Response(failure)
        return httpx.Response(200, text=DETAIL)

    module = import_module('apps.library.source')
    source = module.LibrarySource(lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(module.SourceError):
        source.fetch(date(2026, 9, 7))
    assert len(seen) == 3
    assert [parse_qs(r.content.decode())['seminar_code'][0] for r in seen[1:]] == codes[:2]


@pytest.mark.parametrize('status', [302, 403, 429])
def test_login_redirect_or_throttling_stops_without_retries(status):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(status, headers={'Location': '/home_login_write.mir'})
    module = import_module('apps.library.source')
    source = module.LibrarySource(
        lambda: httpx.Client(transport=httpx.MockTransport(handler)), pause=lambda: None
    )
    with pytest.raises(module.SourceError):
        source.fetch(date(2026, 9, 7))
    assert len(seen) == 1
