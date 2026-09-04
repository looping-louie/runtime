"""Reusable Harness request fixtures for runtime tests."""

from __future__ import annotations


def instruction_snapshot() -> dict[str, object]:
    """Build one immutable Persona and Skill snapshot from the API."""

    return {
        'snapshot_version': 1,
        'persona': {
            'id': 'persona-1',
            'name': 'Implementer',
            'content': 'Make the smallest coherent implementation.',
        },
        'skills': [{
            'id': 'skill-api',
            'name': 'API Compatibility',
            'description': 'Preserve existing API contracts.',
            'content': 'Keep public API contracts backwards compatible.',
            'version': 3,
        }],
    }


def codex_activity(
    instruction: str,
    *,
    requested_model: str | None = 'gpt-5-codex',
    **payload_overrides: object,
) -> dict[str, object]:
    """Build one API Activity response configured for the Codex CLI Harness."""

    payload: dict[str, object] = {
        'harness': {'kind': 'codex_cli', 'version': 'v1', 'config': {}},
        'instruction_snapshot': instruction_snapshot(),
        **payload_overrides,
    }
    if requested_model is not None:
        payload['requested_model'] = requested_model
    return {'input': instruction, 'payload': payload}
