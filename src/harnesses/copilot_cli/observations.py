"""Extract durable observations from Copilot CLI JSONL output."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CopilotEventObservations:
    """Partial observations retained even when a Copilot turn fails."""

    session_reference: str | None = None
    completion: str | None = None
    usage: dict[str, int] | None = None
    diagnostics: tuple[str, ...] = ()
    actual_model: str | None = None
    reasoning_effort: str | None = None
    exit_code: int | None = None
    parse_error: str | None = None


def parse_copilot_events(stdout: str) -> CopilotEventObservations:
    """Parse valid Copilot JSONL events without discarding earlier observations."""

    session_reference: str | None = None
    completion: str | None = None
    usage: dict[str, int] = {}
    diagnostics: list[str] = []
    actual_model: str | None = None
    reasoning_effort: str | None = None
    exit_code: int | None = None
    parse_error: str | None = None
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            parse_error = 'Copilot returned invalid JSONL output.'
            diagnostics.append(parse_error)
            continue
        if not isinstance(event, dict):
            parse_error = 'Copilot returned a non-object JSONL event.'
            diagnostics.append(parse_error)
            continue
        data = event.get('data')
        if event.get('type') == 'assistant.message' and isinstance(data, dict):
            content = data.get('content')
            if isinstance(content, str):
                completion = content
        if event.get('type') == 'result':
            session_reference = _text(event.get('sessionId')) or session_reference
            exit_value = event.get('exitCode')
            if isinstance(exit_value, int) and not isinstance(exit_value, bool):
                exit_code = exit_value
            usage = _numeric_values(event.get('usage'))
        if event.get('type') == 'session.warning' and isinstance(data, dict):
            message = _text(data.get('message'))
            if message is not None:
                diagnostics.append(message)
    return CopilotEventObservations(
        session_reference=session_reference,
        completion=completion,
        usage=usage,
        diagnostics=tuple(diagnostics),
        actual_model=actual_model,
        reasoning_effort=reasoning_effort,
        exit_code=exit_code,
        parse_error=parse_error,
    )


def _numeric_values(value: object) -> dict[str, int]:
    """Retain the numeric CLI usage fields without assuming a fixed schema."""

    if not isinstance(value, dict):
        return {}
    return {
        key: int(item)
        for key, item in value.items()
        if isinstance(key, str)
        and isinstance(item, (int, float))
        and not isinstance(item, bool)
    }


def _text(value: object) -> str | None:
    """Normalize an optional non-empty text observation."""

    return value.strip() if isinstance(value, str) and value.strip() else None