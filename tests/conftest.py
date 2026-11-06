from __future__ import annotations

import socket
from collections.abc import Callable
from typing import Any

import pytest


class NetworkAccessError(RuntimeError):
    pass


def refuse(*args: object, **kwargs: object) -> None:
    raise NetworkAccessError("Tests must not open network connections.")


@pytest.fixture(autouse=True)
def no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if "integration" in request.keywords:
        return
    connect = socket.socket.connect
    pair: Callable[..., tuple[socket.socket, socket.socket]] = socket.socketpair
    pairing = False

    def connect_within_pair(self: socket.socket, address: Any) -> None:
        if not pairing:
            refuse()
        connect(self, address)

    def socketpair(*args: Any, **kwargs: Any) -> tuple[socket.socket, socket.socket]:
        nonlocal pairing
        pairing = True
        try:
            return pair(*args, **kwargs)
        finally:
            pairing = False

    monkeypatch.setattr(socket.socket, "connect", connect_within_pair)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "socketpair", socketpair)
