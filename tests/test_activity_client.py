"""Tests for runtime activity checkpoint requests."""

from __future__ import annotations

import json

import httpx

from clients.activity_client import ActivityRunClient


def test_get_and_continue_activity_run_use_workspace_scoped_contract() -> None:
    """The runtime fetches and advances the claimed Activity through API checkpoints."""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Return the activity-run response for each expected request."""

        requests.append(request)
        response = {
            'id': 'activity-run-1',
            'activity_id': 'activity-1',
            'input': 'Implement.',
            'status': 'in_progress',
            'state': 'awaiting_snapshot',
            'next_action': 'collect_snapshot',
            'iteration': 1,
            'token_revision': 0,
            'continuation_token': 'continuation-1',
            'created_at': '2026-08-19T10:00:00Z',
            'created_by': 'user-1',
            'updated_at': '2026-08-19T10:00:00Z',
            'payload': {},
        }
        return httpx.Response(200, json=response)

    client = ActivityRunClient(
        api_base_url='https://api.example/api/v1',
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    fetched = client.get_run(
        workspace_id='workspace-1', activity_id='activity-1', run_id='activity-run-1',
    )
    continued = client.continue_run(
        workspace_id='workspace-1', activity_id='activity-1', run_id='activity-run-1',
        pipeline_run_id='pipeline-run-1', lease_token='lease-1',
        continuation_token='continuation-1', idempotency_key='key-1',
        result={'action': 'collect_snapshot', 'repo_context': 'context'},
    )

    assert fetched == continued
    assert [request.method for request in requests] == ['GET', 'POST']
    assert [request.headers['X-Workspace-ID'] for request in requests] == [
        'workspace-1',
        'workspace-1',
    ]
    assert requests[0].url == 'https://api.example/api/v1/activities/activity-1/runs/activity-run-1'
    assert requests[1].url == 'https://api.example/api/v1/activities/activity-1/runs/activity-run-1/continue'
    assert json.loads(requests[1].content) == {
        'pipeline_run_id': 'pipeline-run-1',
        'lease_token': 'lease-1',
        'continuation_token': 'continuation-1',
        'idempotency_key': 'key-1',
        'result': {'action': 'collect_snapshot', 'repo_context': 'context'},
    }
