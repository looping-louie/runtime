"""Route frozen Harness checkpoints to local execution adapters."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from harnesses.codex_cli import execute_codex_cli


def execute_harness(
    response: Mapping[str, object],
    checkout_path: Path,
) -> dict[str, object]:
    """Execute one checkpoint through the adapter selected by its frozen Harness."""

    payload = response.get('payload')
    harness = payload.get('harness') if isinstance(payload, Mapping) else None
    if isinstance(harness, Mapping) and (
        harness.get('kind'), harness.get('version')
    ) == ('codex_cli', 'v1'):
        return execute_codex_cli(response, checkout_path)
    raise RuntimeError('Activity response selects an unsupported Harness.')
