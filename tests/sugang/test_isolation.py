"""The legacy suite must never load live state or contact upstream."""

import json
import socket
import warnings
from pathlib import Path

import push_manager
import pytest
import pytest_socket
import web_observer as observer

APP_DIR = Path(__file__).resolve().parents[2] / "apps" / "sugang"


def test_legacy_imports_use_disposable_source_copies():
    for module in (observer, push_manager):
        source = Path(module.__file__)
        assert source.parent != APP_DIR
        assert source.read_bytes() == (APP_DIR / source.name).read_bytes()


def test_legacy_config_and_targets_are_empty_test_inputs():
    assert json.loads(Path(observer.CONFIG_PATH).read_text(encoding="utf-8")) == {}
    assert json.loads(Path(observer.TARGETS_PATH).read_text(encoding="utf-8")) == []
    assert Path(push_manager.VAPID_FILE).parent == Path(observer.CONFIG_PATH).parent


def test_network_sockets_are_disabled():
    # pytest-socket 0.8+ also warns before raising its blocking exception.
    # Ignore only that expected warning during this deliberate negative test.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=r"A test tried to use socket\.socket\.", category=UserWarning,
        )
        with pytest.raises(pytest_socket.SocketBlockedError):
            socket.socket()
