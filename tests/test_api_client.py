"""Tests for runtime API claim requests."""

from __future__ import annotations

import json

import httpx

from api_client import PipelineRunClaimClient


def test_claim_next_maps_claimed_run_and_workspace_header() -> None:
    """A successful API claim returns the worker-owned run and lease token."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Assert the runtime sends the documented claim request."""

        assert request.method == 'POST'
        assert request.url == 'https://api.example/api/v1/pipelines/runs/claim'
        assert request.headers['X-Workspace-ID'] == 'workspace-1'
        assert json.loads(request.content) == {'worker_id': 'worker-1'}
        return httpx.Response(
            200,
            json={
                'lease_token': 'lease-1',
                'run': {
                    'id': 'run-1',
                    'pipeline_id': 'pipeline-1',
                    'input': 'Implement.',
                    'status': 'claimed',
                    'current_activity_run': None,
                    'steps': [],
                    'created_at': '2026-08-19T10:00:00Z',
                    'created_by': 'user-1',
                    'updated_at': '2026-08-19T10:00:00Z',
                },
            },
        )

    client = PipelineRunClaimClient(
        api_base_url='https://api.example/api/v1',
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    claim = client.claim_next(workspace_id='workspace-1', worker_id='worker-1')

    assert claim is not None
    assert claim.workspace_id == 'workspace-1'
    assert claim.pipeline_id == 'pipeline-1'
    assert claim.run_id == 'run-1'
    assert claim.lease_token == 'lease-1'
    assert claim.payload['status'] == 'claimed'


def test_claim_next_returns_none_when_workspace_has_no_work() -> None:
    """The API no-work response leaves the worker free to poll again later."""

    client = PipelineRunClaimClient(
        api_base_url='https://api.example/api/v1',
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(204)),
        ),
    )

    assert client.claim_next(workspace_id='workspace-1', worker_id='worker-1') is None
