"""Shared checkpoint contract helpers for local CLI Harnesses."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Protocol

from services.checkout.changes import get_changed_files, get_git_diff
from services.checkout.repository import get_head_sha


class CliInstructions(Protocol):
    """Expose instruction data needed to construct one CLI turn prompt."""

    persona_instructions: str
    skill_names: tuple[str, ...]


def require_payload(response: Mapping[str, object]) -> Mapping[str, object]:
    """Return the API-provided pending Harness payload."""

    payload = response.get('payload')
    if not isinstance(payload, Mapping):
        raise ValueError('Activity response is missing the Harness payload.')
    return payload


def require_instruction_snapshot(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Return the immutable instruction snapshot supplied by the API."""

    snapshot = payload.get('instruction_snapshot')
    if not isinstance(snapshot, Mapping):
        raise ValueError('Activity response is missing its instruction snapshot.')
    return snapshot


def require_requested_model(payload: Mapping[str, object]) -> str:
    """Return the immutable model selected by the API for this run."""

    requested_model = payload.get('requested_model')
    if not isinstance(requested_model, str) or not requested_model.strip():
        raise ValueError('Activity response is missing its requested model.')
    return requested_model.strip()


def turn(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Return the common turn contract or the legacy direct-turn default."""

    value = payload.get('turn')
    return value if isinstance(value, Mapping) else {}


def build_prompt(
    response: Mapping[str, object],
    payload: Mapping[str, object],
    instructions: CliInstructions,
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
    current_turn = turn(payload)
    phase = str(current_turn.get('phase', 'execute'))
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
        'iteration': current_turn.get('iteration', 1),
        'workspace_access': current_turn.get('workspace_access', 'workspace_write'),
        'feedback': current_turn.get('feedback', []),
        'proposals': current_turn.get('proposals', []),
        'final_diff': current_turn.get('final_diff', ''),
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
        f'Turn responsibility:\n{phase_instruction(phase)}',
        f'Loop turn:\n{json.dumps(phase_context, sort_keys=True)}',
        f'Task:\n{input_text.strip()}',
        f'Expected output:\n{json.dumps(payload.get("output_contract", {}), sort_keys=True)}',
        f'Repository context:\n{payload.get("repo_context", "")}',
        f'Constitution:\n{payload.get("constitution", "")}',
        f'Project profile:\n{json.dumps(payload.get("project_profile", {}), sort_keys=True)}',
    ))


def phase_instruction(phase: str) -> str:
    """Describe the repository responsibility of one common loop phase."""

    return {
        'proposal': 'Analyze the task and propose a concrete solution. Do not modify files.',
        'review': 'Review the supplied diff against the task. Do not modify files.',
        'aggregate': 'Synthesize the supplied proposals and implement the best solution.',
        'execute': 'Implement the task, incorporating any supplied reviewer feedback.',
    }.get(phase, 'Implement the task.')


def checkout_state(checkout_path: Path) -> tuple[str | None, str, list[str]]:
    """Capture final Git state without hiding the primary Harness result."""

    try:
        return (
            get_head_sha(checkout_path).strip(),
            get_git_diff(checkout_path),
            get_changed_files(checkout_path),
        )
    except RuntimeError:
        return None, '', []


def process_output(value: bytes | str | None) -> str:
    """Normalize partial subprocess output captured by a timeout."""

    if isinstance(value, bytes):
        return value.decode(errors='replace')
    return value or ''


def utc_now() -> datetime:
    """Return the wall-clock timestamp used by Harness observations."""

    return datetime.now(UTC)


def monotonic_now() -> float:
    """Return the monotonic clock used for elapsed Harness duration."""

    return monotonic()


def parse_completion(
    completion: str,
    *,
    require_commit_message: bool,
    phase: str,
    harness_name: str,
) -> tuple[str, str | None, dict[str, object]]:
    """Validate one CLI's final machine-readable response and commit proposal."""

    try:
        parsed = json.loads(completion)
    except json.JSONDecodeError as error:
        raise ValueError(f'{harness_name} final response is not valid JSON.') from error
    if not isinstance(parsed, dict):
        raise ValueError(f'{harness_name} final response must be a JSON object.')
    expected_keys = {
        'proposal': {'proposal'},
        'review': {'approved', 'feedback'},
    }.get(
        phase,
        {'final_response', 'commit_message'} if require_commit_message else {'final_response'},
    )
    if set(parsed) != expected_keys:
        raise ValueError(
            f'{harness_name} final response has invalid keys; expected '
            + ', '.join(sorted(expected_keys))
            + '.'
        )
    if phase == 'proposal':
        proposal = parsed.get('proposal')
        if not isinstance(proposal, str) or not proposal.strip():
            raise ValueError(f'{harness_name} proposal must not be empty.')
        return proposal.strip(), None, {'proposal': proposal.strip()}
    if phase == 'review':
        approved = parsed.get('approved')
        feedback = parsed.get('feedback')
        if not isinstance(approved, bool) or not isinstance(feedback, str):
            raise ValueError(f'{harness_name} review must contain approved and feedback.')
        return feedback.strip() or ('Approved.' if approved else 'Rejected.'), None, {
            'approved': approved, 'feedback': feedback.strip(),
        }
    final_response = parsed.get('final_response')
    if not isinstance(final_response, str) or not final_response.strip():
        raise ValueError(f'{harness_name} final response summary must not be empty.')
    commit_message = parsed.get('commit_message')
    if require_commit_message and (
        not isinstance(commit_message, str) or not commit_message.strip()
    ):
        raise ValueError(f'{harness_name} final response commit_message must not be empty.')
    return (
        final_response.strip(),
        commit_message.strip() if isinstance(commit_message, str) else None,
        {},
    )
