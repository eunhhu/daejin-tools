import time
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier, Lock

import pytest


class FakeClient:
    def __init__(self, name, fail_close=False):
        self.name = name
        self.fail_close = fail_close
        self.closed = False
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        self.closed = True
        if self.fail_close:
            raise RuntimeError("synthetic close failure")

    def __repr__(self):
        return f"FakeClient(raw={self.name})"


def test_session_resource_factory_is_injected_per_browser(tmp_path):
    sessions = import_module("apps.library.sessions")
    calls = []

    def resources(client, operation_lock, journal_path, account_label):
        schedule = object()
        bookings = object()
        calls.append((client, operation_lock, journal_path, account_label, schedule, bookings))
        return schedule, bookings

    store = sessions.SessionStore(state_dir=tmp_path, resource_factory=resources)
    first = store.create("20261234", FakeClient("first"))
    second = store.create("20261234", FakeClient("second"))

    assert len(calls) == 2
    assert first.schedule is calls[0][4]
    assert first.bookings is calls[0][5]
    assert second.schedule is calls[1][4]
    assert second.bookings is calls[1][5]
    assert calls[0][1] is not calls[1][1]
    assert calls[0][2] != calls[1][2]


def test_same_school_account_gets_fully_isolated_browser_sessions(tmp_path):
    sessions = import_module("apps.library.sessions")
    store = sessions.SessionStore(state_dir=tmp_path)

    first = store.create("20261234", FakeClient("first"))
    second = store.create("20261234", FakeClient("second"))

    assert first.token != second.token
    assert len(first.token) >= 43
    assert first.csrf_token != second.csrf_token
    assert first.account_label == second.account_label
    assert first.account_label != "20261234"
    assert first.operation_lock is not second.operation_lock
    assert first.schedule is not second.schedule
    assert first.schedule.cache is not second.schedule.cache
    assert first.bookings is not second.bookings
    assert first.bookings.tickets is not second.bookings.tickets
    assert first.journal_path != second.journal_path
    assert first.journal_path.parent == second.journal_path.parent == tmp_path


def test_session_store_expires_closes_bounds_and_removes_sessions(tmp_path):
    sessions = import_module("apps.library.sessions")
    clock = [0.0]
    store = sessions.SessionStore(
        state_dir=tmp_path,
        clock=lambda: clock[0],
        idle_ttl=10,
        max_sessions=1,
    )
    first_client = FakeClient("first")
    first = store.create("20261234", first_client)
    first.journal_path.write_text("{}", encoding="utf-8")
    rejected_client = FakeClient("rejected")

    with pytest.raises(sessions.SessionLimit):
        store.create("20265678", rejected_client)

    assert rejected_client.closed is True
    assert store.get(first.token) is first
    clock[0] = 9
    assert store.get(first.token) is first
    clock[0] = 20
    assert store.get(first.token) is None
    assert first_client.closed is True
    assert first.journal_path.exists() is False

    replacement_client = FakeClient("replacement")
    replacement = store.create("20265678", replacement_client)
    assert store.remove(replacement.token) is True
    assert replacement_client.closed is True
    assert store.remove(replacement.token) is False


def test_one_upstream_jar_serializes_while_different_sessions_run_concurrently(tmp_path):
    sessions = import_module("apps.library.sessions")
    store = sessions.SessionStore(state_dir=tmp_path)
    first = store.create("20261234", FakeClient("first"))
    second = store.create("20265678", FakeClient("second"))
    state_lock = Lock()
    active = 0
    peak = 0

    def measured(waiter=None):
        nonlocal active, peak
        with state_lock:
            active += 1
            peak = max(peak, active)
        if waiter:
            waiter.wait(timeout=1)
        else:
            time.sleep(0.03)
        with state_lock:
            active -= 1

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: first.run(measured), range(2)))
    assert peak == 1

    peak = 0
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(first.run, measured, barrier), pool.submit(second.run, measured, barrier)]
        for future in futures:
            future.result(timeout=2)
    assert peak == 2


def test_failed_session_resource_construction_closes_the_authenticated_client(tmp_path):
    sessions = import_module("apps.library.sessions")
    client = FakeClient("failed")

    def broken_resources(client, operation_lock, journal_path, account_label):
        raise RuntimeError("synthetic construction failure")

    store = sessions.SessionStore(state_dir=tmp_path, resource_factory=broken_resources)
    with pytest.raises(RuntimeError, match="synthetic construction failure"):
        store.create("20261234", client)

    assert client.closed is True
    assert store._sessions == {}


def test_browser_session_repr_hides_raw_tokens_and_client(tmp_path):
    sessions = import_module("apps.library.sessions")
    client = FakeClient("raw-client-secret")
    browser_session = sessions.SessionStore(state_dir=tmp_path).create("20261234", client)

    value = repr(browser_session)

    assert browser_session.token not in value
    assert browser_session.csrf_token not in value
    assert "raw-client-secret" not in value


def test_closed_session_reference_fails_controlled_and_close_is_idempotent(tmp_path):
    sessions = import_module("apps.library.sessions")
    client = FakeClient("held-reference")
    store = sessions.SessionStore(state_dir=tmp_path)
    browser_session = store.create("20261234", client)
    browser_session.journal_path.write_text("{}", encoding="utf-8")
    called = False

    assert store.remove(browser_session.token) is True

    def use_closed_client():
        nonlocal called
        called = True

    with pytest.raises(sessions.SessionExpired, match="로그인 세션이 종료됐어"):
        browser_session.run(use_closed_client)

    browser_session.close()
    assert called is False
    assert client.close_calls == 1
    assert browser_session.journal_path.exists() is False


def test_browser_session_close_finishes_cleanup_even_if_client_close_fails(tmp_path):
    sessions = import_module("apps.library.sessions")
    client = FakeClient("broken-close", fail_close=True)
    browser_session = sessions.SessionStore(state_dir=tmp_path).create("20261234", client)
    browser_session.journal_path.write_text("{}", encoding="utf-8")

    browser_session.close()
    browser_session.close()

    assert client.close_calls == 1
    assert browser_session.journal_path.exists() is False
    with pytest.raises(sessions.SessionExpired):
        browser_session.run(lambda: None)


def test_closed_store_rejects_new_sessions_and_closes_the_unaccepted_client(tmp_path):
    sessions = import_module("apps.library.sessions")
    store = sessions.SessionStore(state_dir=tmp_path)
    store.close()
    client = FakeClient("after-shutdown")

    with pytest.raises(RuntimeError, match="closed"):
        store.create("20261234", client)

    assert client.closed is True
    assert store._sessions == {}


@pytest.mark.parametrize("method", ["cleanup", "close"])
def test_store_closes_every_session_even_if_one_session_close_fails(tmp_path, method):
    sessions = import_module("apps.library.sessions")
    clock = [0.0]
    store = sessions.SessionStore(state_dir=tmp_path, clock=lambda: clock[0], idle_ttl=10)
    first = store.create("20261234", FakeClient("first"))
    second_client = FakeClient("second")
    store.create("20265678", second_client)

    def broken_close():
        raise RuntimeError("synthetic session close failure")

    first.close = broken_close
    if method == "cleanup":
        clock[0] = 10
        assert store.cleanup() == 2
    else:
        store.close()

    assert second_client.closed is True
    assert store._sessions == {}
