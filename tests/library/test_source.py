from datetime import date
from importlib import import_module
from urllib.parse import parse_qs

import httpx
import pytest

LIST = """<a onclick="seminar_resv('/seminar_resv.mir','DJUL','C','C01','캐럴1실','1','1');">방</a>"""
DETAIL = '<script>var year = 2026; var month = 09; var day = 07;</script><input id="service_term" value="30"><select id="start_time"><option value="17:00">17:00</option></select>'


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
