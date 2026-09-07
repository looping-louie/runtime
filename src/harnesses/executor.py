"""Route frozen Harness checkpoints to local execution adapters."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from harnesses.copilot_cli import execute_copilot_cli
from harnesses.codex_cli import execute_codex_cli


HARNESS_ADAPTERS = {
    ('copilot_cli', 'v1'): execute_copilot_cli,
    ('codex_cli', 'v1'): execute_codex_cli,
}


def execute_harness(
    response: Mapping[str, object],
    checkout_path: Path,
) -> dict[str, object]:
    """Execute one checkpoint through the adapter selected by its frozen Harness."""

    payload = response.get('payload')
    harness = payload.get('harness') if isinstance(payload, Mapping) else None
    identity = (
        (harness.get('kind'), harness.get('version'))
        if isinstance(harness, Mapping)
        else None
    )
    adapter = HARNESS_ADAPTERS.get(identity)
    if adapter is None:
        raise RuntimeError('Activity response selects an unsupported Harness.')
    return adapter(response, checkout_path)
