"""Execute one bounded local Codex CLI Harness turn."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Mapping

from services.git.repository_context import get_changed_files, get_git_diff


def execute_codex_cli(response: Mapping[str, object], checkout_path: Path) -> dict[str, object]:
    """Run Codex in the mapped checkout and return the checkpoint result."""

    try:
        payload = _require_payload(response)
        _require_codex_harness(payload)
        command = os.environ.get('LOUIE_CODEX_COMMAND', 'codex').strip()
        if not command:
            raise ValueError('LOUIE_CODEX_COMMAND must not be empty.')
        result = subprocess.run(
            [command, 'exec', '--json', '--sandbox', _sandbox(), '-'],
            input=_prompt(response, payload),
            capture_output=True,
            cwd=checkout_path,
            text=True,
            timeout=_timeout_seconds(),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        return {'action': 'run_harness', 'completed': False, 'error': str(error)}
    if result.returncode != 0:
        return {
            'action': 'run_harness',
            'completed': False,
            'error': result.stderr.strip() or f'Codex exited with status {result.returncode}.',
        }
    try:
        session_reference, final_response, usage, diagnostics = _parse_events(result.stdout)
    except ValueError as error:
        return {'action': 'run_harness', 'completed': False, 'error': str(error)}
    return {
        'action': 'run_harness',
        'completed': True,
        'final_response': final_response,
        'final_diff': get_git_diff(checkout_path),
        'changed_files': get_changed_files(checkout_path),
        'usage': usage,
        'diagnostics': diagnostics,
        'session_reference': session_reference,
    }


def _require_payload(response: Mapping[str, object]) -> Mapping[str, object]:
    """Return the API-provided pending Harness payload."""

    payload = response.get('payload')
    if not isinstance(payload, Mapping):
        raise ValueError('Activity response is missing the Harness payload.')
    return payload


def _require_codex_harness(payload: Mapping[str, object]) -> None:
    """Reject a response that is not frozen for the supported Codex Harness."""

    harness = payload.get('harness')
    if not isinstance(harness, Mapping) or (
        harness.get('kind'), harness.get('version'), harness.get('config')
    ) != ('codex_cli', 'v1', {}):
        raise ValueError('Activity response does not select codex_cli v1.')


def _prompt(response: Mapping[str, object], payload: Mapping[str, object]) -> str:
    """Build one bounded task prompt from the immutable activity checkpoint."""

    input_text = response.get('input')
    if not isinstance(input_text, str) or not input_text.strip():
        raise ValueError('Activity response is missing input.')
    return '\n\n'.join((
        f'Task:\n{input_text.strip()}',
        f'Repository context:\n{payload.get("repo_context", "")}',
        f'Constitution:\n{payload.get("constitution", "")}',
        f'Project profile:\n{json.dumps(payload.get("project_profile", {}), sort_keys=True)}',
    ))


def _sandbox() -> str:
    """Return the configured local Codex sandbox policy."""

    return os.environ.get('LOUIE_CODEX_SANDBOX', 'workspace-write').strip() or 'workspace-write'


def _timeout_seconds() -> float:
    """Return a positive bounded Codex turn timeout from local configuration."""

    try:
        timeout = float(os.environ.get('LOUIE_CODEX_TIMEOUT_SECONDS', '1800'))
    except ValueError as error:
        raise ValueError('LOUIE_CODEX_TIMEOUT_SECONDS must be a number.') from error
    if timeout <= 0:
        raise ValueError('LOUIE_CODEX_TIMEOUT_SECONDS must be positive.')
    return timeout


def _parse_events(stdout: str) -> tuple[str | None, str, dict[str, int], list[str]]:
    """Extract Codex's final response and safe diagnostics from JSONL output."""

    session_reference: str | None = None
    final_response: str | None = None
    usage: dict[str, int] = {}
    diagnostics: list[str] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError('Codex returned invalid JSONL output.') from error
        if not isinstance(event, dict):
            raise ValueError('Codex returned a non-object JSONL event.')
        if event.get('type') == 'thread.started':
            thread_id = event.get('thread_id')
            session_reference = thread_id if isinstance(thread_id, str) and thread_id else None
        item = event.get('item')
        if event.get('type') == 'item.completed' and isinstance(item, dict):
            text = item.get('text')
            if item.get('type') == 'agent_message' and isinstance(text, str):
                final_response = text
        if event.get('type') == 'turn.completed' and isinstance(event.get('usage'), dict):
            usage = {
                key: int(value)
                for key, value in event['usage'].items()
                if isinstance(key, str) and isinstance(value, (int, float))
            }
        if event.get('type') in ('error', 'turn.failed'):
            diagnostics.append(str(event.get('message') or event.get('type')))
    if final_response is None:
        raise ValueError('Codex did not complete the turn.')
    return session_reference, final_response, usage, diagnostics