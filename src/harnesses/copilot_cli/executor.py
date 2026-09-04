"""Execute one bounded local Copilot CLI Harness turn."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from harnesses.codex_cli.executor import (
    _checkout_state,
    _monotonic,
    _parse_completion,
    _process_output,
    _prompt,
    _require_instruction_snapshot,
    _require_payload,
    _require_requested_model,
    _turn,
    _utc_now,
)
from services.checkout.repository import get_head_sha

from .instructions import materialize_instruction_snapshot
from .observations import parse_copilot_events


def execute_copilot_cli(
    response: Mapping[str, object], checkout_path: Path
) -> dict[str, object]:
    """Run Copilot in the mapped checkout and return the checkpoint result."""

    started_at = _utc_now()
    started_monotonic = _monotonic()
    requested_model: str | None = None
    source_commit_sha: str | None = None
    materialized_skills: tuple[dict[str, object], ...] = ()
    stdout = ''
    stderr = ''
    exit_code: int | None = None
    error_message: str | None = None
    commit_forbidden = False
    payload: Mapping[str, object] = {}
    try:
        payload = _require_payload(response)
        _require_copilot_harness(payload)
        requested_model = _require_requested_model(payload)
        command = os.environ.get('LOUIE_COPILOT_COMMAND', 'copilot').strip()
        if not command:
            raise ValueError('LOUIE_COPILOT_COMMAND must not be empty.')
        snapshot = _require_instruction_snapshot(payload)
        turn = _turn(payload)
        phase = str(turn.get('phase', 'execute'))
        commit_forbidden = payload.get('commit_mode') == 'forbid' or phase in (
            'proposal', 'review'
        )
        source_commit_sha = get_head_sha(checkout_path).strip()
        with materialize_instruction_snapshot(checkout_path, snapshot) as instructions:
            materialized_skills = instructions.materialized_skills
            prompt = _prompt(
                response, payload, instructions, commit_forbidden=commit_forbidden
            )
            result = subprocess.run(
                _command(command, requested_model, turn, prompt),
                capture_output=True,
                cwd=checkout_path,
                text=True,
                timeout=_timeout_seconds(),
                check=False,
            )
        stdout, stderr, exit_code = result.stdout, result.stderr, result.returncode
        if exit_code != 0:
            error_message = stderr.strip() or f'Copilot exited with status {exit_code}.'
    except subprocess.TimeoutExpired as error:
        stdout, stderr = _process_output(error.stdout), _process_output(error.stderr)
        error_message = str(error)
    except (OSError, RuntimeError, ValueError) as error:
        error_message = str(error)

    observations = parse_copilot_events(stdout)
    diagnostics = list(observations.diagnostics)
    if stderr.strip() and stderr.strip() not in diagnostics:
        diagnostics.append(stderr.strip())
    final_response = ''
    commit_message: str | None = None
    output: dict[str, object] = {}
    if observations.completion is not None:
        try:
            final_response, commit_message, output = _parse_completion(
                observations.completion,
                require_commit_message=not commit_forbidden,
                phase=str(_turn(payload).get('phase', 'execute')),
            )
        except ValueError as error:
            error_message = error_message or str(error)
            diagnostics.append(str(error))
    elif error_message is None:
        error_message = 'Copilot did not complete the turn.'
    if observations.parse_error is not None and error_message is None:
        error_message = observations.parse_error

    final_commit_sha, final_diff, changed_files = _checkout_state(checkout_path)
    harness_result: dict[str, object] = {
        'action': 'run_harness', 'schema_version': 'v1',
        'harness': {'kind': 'copilot_cli', 'version': 'v1', 'config': {}},
        'completed': error_message is None,
        'started_at': started_at.isoformat(), 'completed_at': _utc_now().isoformat(),
        'duration_ms': max(0, round((_monotonic() - started_monotonic) * 1000)),
        'final_response': final_response, 'requested_model': requested_model,
        'actual_model': observations.actual_model or requested_model,
        'reasoning_effort': observations.reasoning_effort,
        'session_reference': observations.session_reference,
        'usage': observations.usage or {},
        'exit_code': exit_code if exit_code is not None else observations.exit_code,
        'diagnostics': diagnostics, 'materialized_skills': list(materialized_skills),
        'source_commit_sha': source_commit_sha, 'final_commit_sha': final_commit_sha,
        'final_diff': final_diff, 'changed_files': changed_files,
    }
    turn = _turn(payload)
    for result_key, turn_key in (('turn_id', 'id'), ('phase', 'phase'), ('agent_id', 'agent_id'), ('role', 'role'), ('iteration', 'iteration')):
        if turn.get(turn_key) is not None:
            harness_result[result_key] = turn[turn_key]
    if output:
        harness_result['output'] = output
    if commit_message is not None:
        harness_result['commit_message'] = commit_message
    if error_message is not None:
        harness_result['error'] = error_message
    return harness_result


def _require_copilot_harness(payload: Mapping[str, object]) -> None:
    """Reject a response that is not frozen for the supported Copilot Harness."""

    harness = payload.get('harness')
    if not isinstance(harness, Mapping) or (
        harness.get('kind'), harness.get('version'), harness.get('config')
    ) != ('copilot_cli', 'v1', {}):
        raise ValueError('Activity response does not select copilot_cli v1.')


def _command(
    command: str,
    model: str,
    turn: Mapping[str, object],
    prompt: str,
) -> list[str]:
    """Build the non-interactive Copilot command for the selected turn."""

    arguments = [
        command, '--allow-all-tools', '--no-ask-user', '--output-format', 'json',
        '--stream', 'off', '--model', model, '--prompt', prompt,
    ]
    if turn.get('workspace_access') == 'read_only':
        arguments.extend(('--available-tools', 'view,grep,glob'))
    return arguments


def _timeout_seconds() -> float:
    """Return a positive bounded Copilot turn timeout from local configuration."""

    try:
        timeout = float(os.environ.get('LOUIE_COPILOT_TIMEOUT_SECONDS', '1800'))
    except ValueError as error:
        raise ValueError('LOUIE_COPILOT_TIMEOUT_SECONDS must be a number.') from error
    if timeout <= 0:
        raise ValueError('LOUIE_COPILOT_TIMEOUT_SECONDS must be positive.')
    return timeout