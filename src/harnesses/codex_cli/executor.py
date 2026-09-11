"""Execute one bounded local Codex CLI Harness turn."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping

from harnesses.cli_common import build_prompt as _prompt
from harnesses.cli_common import checkout_state as _checkout_state
from harnesses.cli_common import monotonic_now as _monotonic
from harnesses.cli_common import parse_completion as _parse_completion
from harnesses.cli_common import process_output as _process_output
from harnesses.cli_common import require_instruction_snapshot as _require_instruction_snapshot
from harnesses.cli_common import require_payload as _require_payload
from harnesses.cli_common import require_requested_model as _require_requested_model
from harnesses.cli_common import turn as _turn
from harnesses.cli_common import utc_now as _utc_now
from services.checkout.repository import get_head_sha

from .instructions import materialize_instruction_snapshot
from .observations import enrich_with_session_settings, parse_codex_events


def execute_codex_cli(response: Mapping[str, object], checkout_path: Path) -> dict[str, object]:
    """Run Codex in the mapped checkout and return the checkpoint result."""

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
        _require_codex_harness(payload)
        requested_model = _require_requested_model(payload)
        command = os.environ.get('LOUIE_CODEX_COMMAND', 'codex').strip()
        if not command:
            raise ValueError('LOUIE_CODEX_COMMAND must not be empty.')
        snapshot = _require_instruction_snapshot(payload)
        turn = _turn(payload)
        phase = str(turn.get('phase', 'execute'))
        commit_forbidden = (
            payload.get('commit_mode') == 'forbid'
            or phase in ('proposal', 'review')
        )
        source_commit_sha = get_head_sha(checkout_path).strip()
        with materialize_instruction_snapshot(checkout_path, snapshot) as instructions:
            materialized_skills = instructions.materialized_skills
            result = subprocess.run(
                [
                    command,
                    'exec',
                    '--json',
                    '--model',
                    requested_model,
                    '--sandbox',
                    _sandbox(turn),
                    '-',
                ],
                input=_prompt(
                    response,
                    payload,
                    instructions,
                    commit_forbidden=commit_forbidden,
                ),
                capture_output=True,
                cwd=checkout_path,
                text=True,
                timeout=_timeout_seconds(),
                check=False,
            )
        stdout = result.stdout
        stderr = result.stderr
        exit_code = result.returncode
        if exit_code != 0:
            error_message = (
                stderr.strip() or f'Codex exited with status {exit_code}.'
            )
    except subprocess.TimeoutExpired as error:
        stdout = _process_output(error.stdout)
        stderr = _process_output(error.stderr)
        error_message = str(error)
    except (OSError, RuntimeError, ValueError) as error:
        error_message = str(error)

    observations = enrich_with_session_settings(parse_codex_events(stdout))
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
                harness_name='Codex',
            )
        except ValueError as error:
            diagnostics.append(str(error))
            if error_message is None:
                error_message = str(error)
    elif error_message is None:
        error_message = 'Codex did not complete the turn.'
    if observations.parse_error is not None and error_message is None:
        error_message = observations.parse_error

    final_commit_sha, final_diff, changed_files = _checkout_state(checkout_path)
    completed_at = _utc_now()
    harness_result: dict[str, object] = {
        'action': 'run_harness',
        'schema_version': 'v1',
        'harness': {'kind': 'codex_cli', 'version': 'v1', 'config': {}},
        'completed': error_message is None,
        'started_at': started_at.isoformat(),
        'completed_at': completed_at.isoformat(),
        'duration_ms': max(0, round((_monotonic() - started_monotonic) * 1000)),
        'final_response': final_response,
        'requested_model': requested_model,
        'actual_model': observations.actual_model or requested_model,
        'reasoning_effort': observations.reasoning_effort,
        'session_reference': observations.session_reference,
        'usage': observations.usage or {},
        'exit_code': exit_code,
        'diagnostics': diagnostics,
        'materialized_skills': list(materialized_skills),
        'source_commit_sha': source_commit_sha,
        'final_commit_sha': final_commit_sha,
        'final_diff': final_diff,
        'changed_files': changed_files,
    }
    turn = _turn(payload)
    for result_key, turn_key in (
        ('turn_id', 'id'), ('phase', 'phase'), ('agent_id', 'agent_id'),
        ('role', 'role'), ('iteration', 'iteration'),
    ):
        if turn.get(turn_key) is not None:
            harness_result[result_key] = turn[turn_key]
    if output:
        harness_result['output'] = output
    if commit_message is not None:
        harness_result['commit_message'] = commit_message
    if error_message is not None:
        harness_result['error'] = error_message
    return harness_result


def _require_codex_harness(payload: Mapping[str, object]) -> None:
    """Reject a response that is not frozen for the supported Codex Harness."""

    harness = payload.get('harness')
    if not isinstance(harness, Mapping) or (
        harness.get('kind'), harness.get('version'), harness.get('config')
    ) != ('codex_cli', 'v1', {}):
        raise ValueError('Activity response does not select codex_cli v1.')


def _sandbox(turn: Mapping[str, object]) -> str:
    """Return the configured local Codex sandbox policy."""

    if turn.get('workspace_access') == 'read_only':
        return 'read-only'
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
