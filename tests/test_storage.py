from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from modelscape.core import (
    Coordinate,
    DifferenceMeasurement,
    Identity,
    MeasureValue,
    Observation,
    PointMeasurement,
    StoreError,
    TargetError,
    TargetOutput,
    Variant,
)
from modelscape.core.experiments import RunManifest
from modelscape.storage import MemoryStore, SQLiteStore, Store
from modelscape.storage.protocols import Record
from tests.helpers import level_space

VARIANT = level_space().variant("case-0", {"level": 2, "style": "formal"})
MEASURE = Identity(name="m", parameters={"k": 1})


def observation(text: str | None = "answer", error: TargetError | None = None) -> Observation:
    return Observation(
        id="obs",
        variant_id=VARIANT.id,
        case_id=VARIANT.case_id,
        coordinate=VARIANT.coordinate,
        target=Identity(name="target"),
        repetition=0,
        seed=5,
        output=TargetOutput(text=text, error=error),
        attempts=1,
        schedule_position=0,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        completed_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Store]:
    if request.param == "memory":
        yield MemoryStore()
        return
    with SQLiteStore(tmp_path / "records.db") as sqlite_store:
        yield sqlite_store


def test_every_record_kind_round_trips(store: Store) -> None:
    point = PointMeasurement.create(MEASURE, "obs", MeasureValue(value=1.0, details={"x": [1]}))
    difference = DifferenceMeasurement.create(MEASURE, "obs", "obs", MeasureValue(value=0.25))
    manifest = RunManifest(
        id="run",
        variant_ids=(VARIANT.id,),
        observation_ids=("obs",),
        point_measurement_ids=(point.id,),
        difference_measurement_ids=(difference.id,),
        completed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    records = [VARIANT, observation(), point, difference, manifest]
    store.put(records)
    for record in records:
        assert store.get(type(record), [record.id]) == {record.id: record}
    restored = store.get(Variant, [VARIANT.id])[VARIANT.id]
    assert isinstance(restored.coordinate, Coordinate)
    assert restored.coordinate == VARIANT.coordinate
    assert restored.attributes == {"level": 2, "style": "formal", "note_count": 0}
    assert restored.prompt == VARIANT.prompt


def test_put_replaces_and_get_returns_only_existing(store: Store) -> None:
    store.put([observation(error=TargetError(type="TimeoutError", message="slow"))])
    store.put([observation(text="recovered")])
    found = store.get(Observation, ["obs", "missing"])
    assert list(found) == ["obs"]
    assert found["obs"].output.text == "recovered"


def test_sqlite_store_persists_across_connections(tmp_path: Path) -> None:
    path = tmp_path / "records.db"
    with SQLiteStore(path) as first:
        first.put([VARIANT])
    with SQLiteStore(path) as second:
        assert second.get(Variant, [VARIANT.id]) == {VARIANT.id: VARIANT}


def test_sqlite_store_reads_large_id_batches(tmp_path: Path) -> None:
    observations = [observation().model_copy(update={"id": f"o{index}"}) for index in range(1200)]
    with SQLiteStore(tmp_path / "records.db") as store:
        store.put(observations)
        assert len(store.get(Observation, [item.id for item in observations])) == 1200


def test_unsupported_record_kinds_are_refused(store: Store) -> None:
    foreign = cast(type[Variant], Identity)
    with pytest.raises(StoreError, match="cannot hold records of type Identity"):
        store.get(foreign, ["obs"])
    with pytest.raises(StoreError, match="cannot hold records of type Identity"):
        store.put([cast(Record, MEASURE)])


def test_a_refused_put_stores_nothing(store: Store) -> None:
    with pytest.raises(StoreError):
        store.put([VARIANT, observation(), cast(Record, MEASURE)])
    assert store.get(Variant, [VARIANT.id]) == {}
    assert store.get(Observation, ["obs"]) == {}
