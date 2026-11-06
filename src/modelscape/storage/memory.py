from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from modelscape.core.errors import StoreError
from modelscape.storage.protocols import RECORD_KINDS, Record, RecordT


class MemoryStore:
    """In-process store for tests and small experiments. Nothing is written to disk."""

    __slots__ = ("_tables",)

    def __init__(self) -> None:
        self._tables: dict[type[Record], dict[str, Record]] = {kind: {} for kind in RECORD_KINDS}

    def __repr__(self) -> str:
        counts = ", ".join(f"{kind.__name__}={len(table)}" for kind, table in self._tables.items())
        return f"MemoryStore({counts})"

    def put(self, records: Iterable[Record]) -> None:
        staged = [(self._table(type(record)), record) for record in records]
        for table, record in staged:
            table[record.id] = record

    def get(self, kind: type[RecordT], ids: Iterable[str]) -> dict[str, RecordT]:
        table = self._table(kind)
        return {
            identifier: cast(RecordT, table[identifier])
            for identifier in ids
            if identifier in table
        }

    def _table(self, kind: type[Record]) -> dict[str, Record]:
        if kind not in self._tables:
            raise StoreError(f"MemoryStore cannot hold records of type {kind.__name__}.")
        return self._tables[kind]
