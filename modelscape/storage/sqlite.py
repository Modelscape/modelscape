from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator, Iterable, Iterator, Sequence
from contextlib import contextmanager
from types import TracebackType

from modelscape.core.errors import StoreError
from modelscape.core.experiments import ExperimentRecord, RunManifest
from modelscape.core.measurements import DifferenceMeasurement, PointMeasurement
from modelscape.core.observations import Observation
from modelscape.core.tasks import Variant
from modelscape.storage.protocols import Record, RecordT

TABLES: dict[type[Record], str] = {
    Variant: "variants",
    Observation: "observations",
    PointMeasurement: "point_measurements",
    DifferenceMeasurement: "difference_measurements",
    ExperimentRecord: "experiments",
    RunManifest: "run_manifests",
}

COLUMNS = "id TEXT PRIMARY KEY, payload TEXT NOT NULL"
FORMAT = 1
QUERY_CHUNK = 500


class SQLiteStore:
    """Durable local store backed by a single SQLite file.

    Records are stored as validated JSON payloads, one table per record kind. Every ``put`` is
    committed atomically, so an interrupted run keeps all records written before it stopped.
    The file's ``user_version`` is its format, raised when a release changes the layout.
    """

    __slots__ = ("_connection", "_path")

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = os.fspath(path)
        self._connection = sqlite3.connect(self._path, isolation_level=None)
        found: int = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if found > FORMAT:
            self._connection.close()
            raise StoreError(
                f"{self._path} has store format {found}, but this modelscape reads up to "
                f"{FORMAT}. Upgrade modelscape to read it."
            )
        self._connection.execute("PRAGMA journal_mode = WAL")
        with _transaction(self._connection):
            for table in TABLES.values():
                self._connection.execute(f"CREATE TABLE IF NOT EXISTS {table} ({COLUMNS})")
            self._connection.execute(f"PRAGMA user_version = {FORMAT}")

    def __repr__(self) -> str:
        return f"SQLiteStore({self._path!r})"

    def __enter__(self) -> SQLiteStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def put(self, records: Iterable[Record]) -> None:
        rows: dict[str, list[tuple[str, str]]] = {}
        for record in records:
            rows.setdefault(_table(type(record)), []).append((record.id, record.model_dump_json()))
        with _transaction(self._connection):
            for table, values in rows.items():
                self._connection.executemany(
                    f"INSERT INTO {table} (id, payload) VALUES (?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
                    values,
                )

    def get(self, kind: type[RecordT], ids: Iterable[str]) -> dict[str, RecordT]:
        table = _table(kind)
        found: dict[str, RecordT] = {}
        for chunk in _chunks(list(dict.fromkeys(ids)), QUERY_CHUNK):
            placeholders = ", ".join("?" for _ in chunk)
            cursor = self._connection.execute(
                f"SELECT id, payload FROM {table} WHERE id IN ({placeholders})", chunk
            )
            rows: list[tuple[str, str]] = cursor.fetchall()
            for identifier, payload in rows:
                found[identifier] = kind.model_validate_json(payload)
        return found


def _table(kind: type[Record]) -> str:
    if kind not in TABLES:
        raise StoreError(f"SQLiteStore cannot hold records of type {kind.__name__}.")
    return TABLES[kind]


def _chunks(items: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


@contextmanager
def _transaction(connection: sqlite3.Connection) -> Generator[None, None, None]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")
