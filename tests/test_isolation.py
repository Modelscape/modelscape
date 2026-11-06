from __future__ import annotations

import asyncio
import socket

import pytest

from tests.conftest import NetworkAccessError


def test_tests_cannot_open_network_connections() -> None:
    with pytest.raises(NetworkAccessError):
        socket.create_connection(("example.com", 80))
    with socket.socket() as local, pytest.raises(NetworkAccessError):
        local.connect(("127.0.0.1", 11434))


def test_event_loops_still_get_their_internal_socket_pair() -> None:
    first, second = socket.socketpair()
    with first, second:
        first.sendall(b"ok")
        assert second.recv(2) == b"ok"
    assert asyncio.run(asyncio.sleep(0, result="ran")) == "ran"
