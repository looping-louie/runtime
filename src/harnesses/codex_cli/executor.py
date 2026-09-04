"""Execute one bounded local Codex CLI Harness turn."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Mapping

from services.checkout.changes import get_changed_files, get_git_diff
from services.checkout.repository import get_head_sha

from .instructions import CodexInstructions, materialize_instruction_snapshot
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


def _require_instruction_snapshot(
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    """Return the immutable instruction snapshot supplied by the API."""

    snapshot = payload.get('instruction_snapshot')
    if not isinstance(snapshot, Mapping):
        raise ValueError('Activity response is missing its instruction snapshot.')
    return snapshot


def _require_requested_model(payload: Mapping[str, object]) -> str:
    """Return the immutable model selected by the API for this run."""

    requested_model = payload.get('requested_model')
    if not isinstance(requested_model, str) or not requested_model.strip():
        raise ValueError('Activity response is missing its requested model.')
    return requested_model.strip()


def _turn(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Return the common turn contract or the legacy direct-turn default."""

    turn = payload.get('turn')
    return turn if isinstance(turn, Mapping) else {}


def _prompt(
    response: Mapping[str, object],
    payload: Mapping[str, object],
    instructions: CodexInstructions,
    *,
    commit_forbidden: bool,
) -> str:
    """Build one bounded task prompt from the immutable activity checkpoint."""

    input_text = response.get('input')
    if not isinstance(input_text, str) or not input_text.strip():
        raise ValueError('Activity response is missing input.')
    selected_skills = (
        'Apply these run-scoped Skills when relevant: '
        + ', '.join(f'${name}' for name in instructions.skill_names)
        if instructions.skill_names
        else 'No additional run-scoped Skills were selected.'
    )
    turn = _turn(payload)
    phase = str(turn.get('phase', 'execute'))
    completion_shape: dict[str, object]
    if phase == 'proposal':
        completion_shape = {'proposal': 'A concrete implementation proposal.'}
    elif phase == 'review':
        completion_shape = {'approved': True, 'feedback': 'Concise review feedback.'}
    else:
        completion_shape = {'final_response': 'Concise summary of the completed work.'}
    if not commit_forbidden and phase in ('execute', 'aggregate'):
        completion_shape['commit_message'] = 'feat: concise description'
    phase_context = {
        'phase': phase,
        'iteration': turn.get('iteration', 1),
        'workspace_access': turn.get('workspace_access', 'workspace_write'),
        'feedback': turn.get('feedback', []),
        'proposals': turn.get('proposals', []),
        'final_diff': turn.get('final_diff', ''),
    }
    return '\n\n'.join((
        f'Persona instructions:\n{instructions.persona_instructions}',
        f'Selected Skills:\n{selected_skills}',
        (
            'Git commit boundary:\nDo not run git commit or otherwise create a '
            'commit. Leave all changes in the working tree. The API and runtime '
            'own commit authorization and execution.'
        ),
        (
            'Completion contract:\nYour final response must be only this JSON '
            f'object shape, without Markdown fences: {json.dumps(completion_shape)}'
        ),
        f'Turn responsibility:\n{_phase_instruction(phase)}',
        f'Loop turn:\n{json.dumps(phase_context, sort_keys=True)}',
        f'Task:\n{input_text.strip()}',
        f'Expected output:\n{json.dumps(payload.get("output_contract", {}), sort_keys=True)}',
        f'Repository context:\n{payload.get("repo_context", "")}',
        f'Constitution:\n{payload.get("constitution", "")}',
        f'Project profile:\n{json.dumps(payload.get("project_profile", {}), sort_keys=True)}',
    ))


def _phase_instruction(phase: str) -> str:
    """Describe the repository responsibility of one common loop phase."""

    return {
        'proposal': 'Analyze the task and propose a concrete solution. Do not modify files.',
        'review': 'Review the supplied diff against the task. Do not modify files.',
        'aggregate': 'Synthesize the supplied proposals and implement the best solution.',
        'execute': 'Implement the task, incorporating any supplied reviewer feedback.',
    }.get(phase, 'Implement the task.')


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


def _checkout_state(checkout_path: Path) -> tuple[str | None, str, list[str]]:
    """Capture the final Git state without hiding the primary Harness result."""

    try:
        return (
            get_head_sha(checkout_path).strip(),
            get_git_diff(checkout_path),
            get_changed_files(checkout_path),
        )
    except RuntimeError:
        return None, '', []


def _process_output(value: bytes | str | None) -> str:
    """Normalize partial subprocess output captured by a timeout."""

    if isinstance(value, bytes):
        return value.decode(errors='replace')
    return value or ''


def _utc_now() -> datetime:
    """Return the wall-clock timestamp used by Harness observations."""

    return datetime.now(UTC)


def _monotonic() -> float:
    """Return the monotonic clock used for elapsed Harness duration."""

    return monotonic()


def _parse_completion(
    completion: str,
    *,
    require_commit_message: bool,
    phase: str,
) -> tuple[str, str | None, dict[str, object]]:
    """Validate Codex's final machine-readable response and commit proposal."""

    try:
        parsed = json.loads(completion)
    except json.JSONDecodeError as error:
        raise ValueError('Codex final response is not valid JSON.') from error
    if not isinstance(parsed, dict):
        raise ValueError('Codex final response must be a JSON object.')
    expected_keys = {
        'proposal': {'proposal'},
        'review': {'approved', 'feedback'},
    }.get(
        phase,
        {'final_response', 'commit_message'} if require_commit_message else {'final_response'},
    )
    if set(parsed) != expected_keys:
        raise ValueError(
            'Codex final response has invalid keys; expected '
            + ', '.join(sorted(expected_keys))
            + '.'
        )
    if phase == 'proposal':
        proposal = parsed.get('proposal')
        if not isinstance(proposal, str) or not proposal.strip():
            raise ValueError('Codex proposal must not be empty.')
        return proposal.strip(), None, {'proposal': proposal.strip()}
    if phase == 'review':
        approved = parsed.get('approved')
        feedback = parsed.get('feedback')
        if not isinstance(approved, bool) or not isinstance(feedback, str):
            raise ValueError('Codex review must contain approved and feedback.')
        return feedback.strip() or ('Approved.' if approved else 'Rejected.'), None, {
            'approved': approved, 'feedback': feedback.strip(),
        }
    final_response = parsed.get('final_response')
    if not isinstance(final_response, str) or not final_response.strip():
        raise ValueError('Codex final response summary must not be empty.')
    commit_message = parsed.get('commit_message')
    if require_commit_message and (
        not isinstance(commit_message, str) or not commit_message.strip()
    ):
        raise ValueError('Codex final response commit_message must not be empty.')
    return (
        final_response.strip(),
        commit_message.strip() if isinstance(commit_message, str) else None,
        {},
    )
