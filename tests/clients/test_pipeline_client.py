"""Tests for runtime pipeline claim requests."""

from __future__ import annotations

import json

import httpx

from clients.pipeline_client import PipelineRunClaimClient


def test_claim_next_discovers_and_conditionally_claims_a_run() -> None:
    """A runtime discovers candidates before claiming one with its ETag."""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Return the nested Pipeline claim protocol responses in order."""

        requests.append(request)
        assert request.headers['X-Project-ID'] == 'project-1'
        assert request.headers['X-User-ID'] == 'user-1'
        if request.method == 'GET' and request.url.path == '/api/v1/pipelines':
            assert request.url.params['status'] == 'active'
            return httpx.Response(200, json={'items': [{'id': 'pipeline-1'}], 'total': 1})
        if request.method == 'GET':
            assert request.url == 'https://api.example/api/v1/pipelines/pipeline-1/runs?claimable=true'
            return httpx.Response(
                200,
                json={
                    'items': [
                        {
                            'etag': '"run-1-v1"',
                            'run': {'id': 'run-1'},
                        }
                    ],
                    'total': 1,
                },
            )
        assert request.method == 'PATCH'
        assert request.url == 'https://api.example/api/v1/pipelines/pipeline-1/runs/run-1'
        assert request.headers['If-Match'] == '"run-1-v1"'
        assert json.loads(request.content) == {'worker_id': 'worker-1', 'status': 'claimed'}
        return httpx.Response(200, json=_claim_response())

    client = PipelineRunClaimClient(
        api_base_url='https://api.example/api/v1',
        user_id='user-1',
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    claim = client.claim_next(project_id='project-1', worker_id='worker-1')

    assert claim is not None
    assert claim.project_id == 'project-1'
    assert claim.pipeline_id == 'pipeline-1'
    assert claim.run_id == 'run-1'
    assert claim.lease_token == 'lease-1'
    assert claim.payload['status'] == 'claimed'
    assert len(requests) == 3


def test_claim_next_returns_none_when_no_pipeline_has_claimable_runs() -> None:
    """No nested candidates leave the worker free to poll again later."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Return one active Pipeline with no API-approved candidates."""

        if request.url.path == '/api/v1/pipelines':
            return httpx.Response(200, json={'items': [{'id': 'pipeline-1'}], 'total': 1})
        return httpx.Response(200, json={'items': [], 'total': 0})

    client = PipelineRunClaimClient(
        api_base_url='https://api.example/api/v1',
        user_id='user-1',
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
        ),
    )

    assert client.claim_next(project_id='project-1', worker_id='worker-1') is None


def test_claim_next_continues_after_another_worker_wins() -> None:
    """A failed precondition makes the runtime attempt another listed candidate."""

    patch_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Make the first candidate stale and let the second claim succeed."""

        nonlocal patch_count
        if request.url.path == '/api/v1/pipelines':
            return httpx.Response(200, json={'items': [{'id': 'pipeline-1'}], 'total': 1})
        if request.method == 'GET':
            return httpx.Response(
                200,
                json={
                    'items': [
                        {'etag': '"run-1-v1"', 'run': {'id': 'run-1'}},
                        {'etag': '"run-2-v1"', 'run': {'id': 'run-2'}},
                    ],
                    'total': 2,
                },
            )
        patch_count += 1
        if patch_count == 1:
            return httpx.Response(412, json={'error': {'code': 'pipeline_run_precondition_failed'}})
        assert request.headers['If-Match'] == '"run-2-v1"'
        return httpx.Response(200, json=_claim_response(run_id='run-2'))

    client = PipelineRunClaimClient(
        api_base_url='https://api.example/api/v1',
        user_id='user-1',
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    claim = client.claim_next(project_id='project-1', worker_id='worker-1')

    assert claim is not None and claim.run_id == 'run-2'
    assert patch_count == 2


def _claim_response(run_id: str = 'run-1') -> dict[str, object]:
    """Build one successful Pipeline claim response."""

    return {
        'lease_token': 'lease-1',
        'run': {
            'id': run_id,
            'pipeline_id': 'pipeline-1',
            'input': 'Implement.',
            'status': 'claimed',
            'current_activity_run': None,
            'steps': [],
            'created_at': '2026-08-19T10:00:00Z',
            'created_by': 'user-1',
            'updated_at': '2026-08-19T10:00:00Z',
        },
    }


def test_continue_run_uses_workspace_scoped_contract() -> None:
    """A terminal child is submitted to the pipeline scheduler for advancement."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Assert the runtime sends the documented continuation request."""

        assert request.method == 'POST'
        assert request.url == (
            'https://api.example/api/v1/pipelines/pipeline-1/runs/run-1/continue'
        )
        assert request.headers['X-Project-ID'] == 'project-1'
        assert request.headers['X-User-ID'] == 'user-1'
        assert json.loads(request.content) == {'lease_token': 'lease-1'}
        return httpx.Response(
            200,
            json={
                'id': 'run-1',
                'pipeline_id': 'pipeline-1',
                'status': 'completed',
                'current_activity_run': None,
            },
        )

    client = PipelineRunClaimClient(
        api_base_url='https://api.example/api/v1',
        user_id='user-1',
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = client.continue_run(
        project_id='project-1',
        pipeline_id='pipeline-1',
        run_id='run-1',
        lease_token='lease-1',
    )

    assert response['status'] == 'completed'


def test_renew_lease_sends_the_active_claim_token() -> None:
    """A runtime renewal uses the claimed run, project, and secret token."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Assert the renewal request follows the documented lease contract."""

        assert request.method == 'POST'
        assert request.url == (
            'https://api.example/api/v1/pipelines/pipeline-1/runs/run-1/lease'
        )
        assert request.headers['X-Project-ID'] == 'project-1'
        assert request.headers['X-User-ID'] == 'user-1'
        assert json.loads(request.content) == {'lease_token': 'lease-1'}
        return httpx.Response(200, json={'lease_expires_at': '2026-08-19T10:01:00Z'})

    client = PipelineRunClaimClient(
        api_base_url='https://api.example/api/v1',
        user_id='user-1',
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.renew_lease(
        project_id='project-1',
        pipeline_id='pipeline-1',
        run_id='run-1',
        lease_token='lease-1',
    )
