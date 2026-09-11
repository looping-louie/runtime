"""Extract durable observations from Codex CLI output and local sessions."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CodexEventObservations:
    """Partial observations retained even when a Codex turn fails."""

    session_reference: str | None = None
    completion: str | None = None
    usage: dict[str, int] | None = None
    diagnostics: tuple[str, ...] = ()
    actual_model: str | None = None
    reasoning_effort: str | None = None
    parse_error: str | None = None


def parse_codex_events(stdout: str) -> CodexEventObservations:
    """Parse every valid JSONL event without discarding earlier observations."""

    session_reference: str | None = None
    completion: str | None = None
    usage: dict[str, int] = {}
    diagnostics: list[str] = []
    actual_model: str | None = None
    reasoning_effort: str | None = None
    parse_error: str | None = None
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            parse_error = 'Codex returned invalid JSONL output.'
            diagnostics.append(parse_error)
            continue
        if not isinstance(event, dict):
            parse_error = 'Codex returned a non-object JSONL event.'
            diagnostics.append(parse_error)
            continue
        event_type = event.get('type')
        if event_type == 'thread.started':
            session_reference = _optional_text(event.get('thread_id'))
        if event_type in ('thread.started', 'turn.started'):
            actual_model = _optional_text(event.get('model')) or actual_model
            reasoning_effort = (
                _optional_text(event.get('reasoning_effort'))
                or _optional_text(event.get('effort'))
                or reasoning_effort
            )
        item = event.get('item')
        if event_type == 'item.completed' and isinstance(item, dict):
            text = item.get('text')
            if item.get('type') == 'agent_message' and isinstance(text, str):
                completion = text
        if event_type in ('turn.completed', 'turn.failed') and isinstance(
            event.get('usage'),
            dict,
        ):
            usage = {
                key: int(value)
                for key, value in event['usage'].items()
                if isinstance(key, str)
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            }
        if event_type in ('error', 'turn.failed'):
            diagnostics.append(_event_diagnostic(event))
    return CodexEventObservations(
        session_reference=session_reference,
        completion=completion,
        usage=usage,
        diagnostics=tuple(diagnostics),
        actual_model=actual_model,
        reasoning_effort=reasoning_effort,
        parse_error=parse_error,
    )


def enrich_with_session_settings(
    observations: CodexEventObservations,
) -> CodexEventObservations:
    """Read effective model settings from Codex's local persisted thread."""

    reference = observations.session_reference
    if reference is None or re.fullmatch(r'[A-Za-z0-9-]+', reference) is None:
        return observations
    session_path = _find_session_path(reference)
    if session_path is None:
        return observations
    try:
        with session_path.open(encoding='utf-8') as session_file:
            for line in session_file:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict) or event.get('type') != 'turn_context':
                    continue
                payload = event.get('payload')
                if not isinstance(payload, dict):
                    continue
                return replace(
                    observations,
                    actual_model=(
                        _optional_text(payload.get('model'))
                        or observations.actual_model
                    ),
                    reasoning_effort=(
                        _optional_text(payload.get('effort'))
                        or observations.reasoning_effort
                    ),
                )
    except OSError:
        return observations
    return observations


def _find_session_path(session_reference: str) -> Path | None:
    """Locate one Codex rollout without assuming its calendar directory."""

    codex_home = Path(
        os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))
    )
    sessions_root = codex_home / 'sessions'
    if not sessions_root.is_dir():
        return None
    try:
        return next(sessions_root.rglob(f'*-{session_reference}.jsonl'), None)
    except OSError:
        return None


def _event_diagnostic(event: dict[str, object]) -> str:
    """Return a bounded readable diagnostic from one failure event."""

    message = _optional_text(event.get('message'))
    if message is not None:
        return message
    error = event.get('error')
    if isinstance(error, dict):
        nested = _optional_text(error.get('message'))
        if nested is not None:
            return nested
    return str(event.get('type'))


def _optional_text(value: object) -> str | None:
    """Normalize an optional non-empty text observation."""

    return value.strip() if isinstance(value, str) and value.strip() else None
