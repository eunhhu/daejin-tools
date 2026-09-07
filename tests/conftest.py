"""Block network access before collection, including application imports."""

import pytest_socket


def pytest_sessionstart(session):
    pytest_socket.disable_socket()


def pytest_unconfigure(config):
    pytest_socket.enable_socket()
