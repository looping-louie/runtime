"""Copilot-specific instruction placement for one CLI turn."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from harnesses.instructions import CliInstructions
from harnesses.instructions import materialize_instruction_snapshot as materialize


CopilotInstructions = CliInstructions


@contextmanager
def materialize_instruction_snapshot(
    checkout_path: Path,
    snapshot: Mapping[str, object],
) -> Iterator[CopilotInstructions]:
    """Expose frozen Skills at Copilot's expected checkout path."""

    with materialize(
        checkout_path,
        snapshot,
        harness_name='Copilot',
        skills_root=checkout_path / '.github' / 'skills',
    ) as instructions:
        yield instructions
