from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import numpy as np

from modelscape.core.observations import Observation, TargetError, TargetOutput, TargetRequest
from modelscape.core.tasks import Variant
from modelscape.execution.experiment import ExecutionConfig
from modelscape.targets.protocols import Target

MAX_ERROR_LENGTH = 2000
REDACTED = "[REDACTED]"
BEARER_TOKEN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)((?:api[_-]?key|access[_-]?token|secret|password|authorization)[\"']?\s*[=:]\s*[\"']?)"
    r"[^\s,;&'\"]+"
)
PREFIXED_KEY = re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{8,}")


@dataclass(frozen=True)
class ObservationJob:
    """One pending observation: a target, a variant, a repetition, and its schedule position."""

    id: str
    variant: Variant
    target: Target
    repetition: int
    seed: int
    position: int = 0

    def request(self) -> TargetRequest:
        return TargetRequest(prompt=self.variant.prompt, repetition=self.repetition, seed=self.seed)


def schedule(jobs: Sequence[ObservationJob], seed: int) -> list[ObservationJob]:
    """Order jobs in shuffled blocks, one block per repetition.

    Each block holds every target and variant once, shuffled reproducibly from ``seed``, so no
    condition or target is tied to one part of the run.
    """
    blocks: dict[int, list[ObservationJob]] = {}
    for job in jobs:
        blocks.setdefault(job.repetition, []).append(job)
    ordered: list[ObservationJob] = []
    for repetition in sorted(blocks):
        block = blocks[repetition]
        order = np.random.default_rng([seed, repetition]).permutation(len(block))
        ordered.extend(block[int(index)] for index in order)
    return [replace(job, position=position) for position, job in enumerate(ordered)]


async def execute(
    jobs: Sequence[ObservationJob], config: ExecutionConfig
) -> AsyncIterator[Observation]:
    """Start jobs in the given order with bounded concurrency; yield them as they complete."""
    semaphore = asyncio.Semaphore(config.concurrency)

    async def bounded(job: ObservationJob) -> Observation:
        async with semaphore:
            return await observe(job, config)

    tasks = [asyncio.create_task(bounded(job)) for job in jobs]
    try:
        for completed in asyncio.as_completed(tasks):
            yield await completed
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def observe(job: ObservationJob, config: ExecutionConfig) -> Observation:
    """Invoke a target with timeout and retries; failures become structured errors."""
    started_at = datetime.now(UTC)
    request = job.request()
    attempt = 0
    while True:
        attempt += 1
        began = time.perf_counter()
        try:
            async with asyncio.timeout(config.timeout_seconds):
                result = await job.target.invoke(request)
            output = result.model_copy(update={"duration_seconds": time.perf_counter() - began})
            break
        except Exception as error:
            if attempt >= config.retry.max_attempts:
                output = TargetOutput(
                    error=describe_error(error, config),
                    duration_seconds=time.perf_counter() - began,
                )
                break
            await asyncio.sleep(config.retry.delay(attempt))
    return Observation(
        id=job.id,
        variant_id=job.variant.id,
        case_id=job.variant.case_id,
        coordinate=job.variant.coordinate,
        target=job.target.identity,
        repetition=job.repetition,
        seed=job.seed,
        output=output,
        attempts=attempt,
        schedule_position=job.position,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )


def describe_error(error: Exception, config: ExecutionConfig) -> TargetError:
    if isinstance(error, TimeoutError) and not str(error):
        message = f"Timed out after {config.timeout_seconds} seconds."
    else:
        message = redact_credentials(str(error))[:MAX_ERROR_LENGTH]
    return TargetError(type=type(error).__name__, message=message)


def redact_credentials(text: str) -> str:
    """Mask common credential formats so error messages can be stored safely."""
    text = BEARER_TOKEN.sub(rf"\1{REDACTED}", text)
    text = CREDENTIAL_ASSIGNMENT.sub(rf"\1{REDACTED}", text)
    return PREFIXED_KEY.sub(REDACTED, text)
