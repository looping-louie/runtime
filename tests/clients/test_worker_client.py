"""Tests for runtime worker heartbeat HTTP requests."""

from __future__ import annotations

import httpx

from clients.worker_client import WorkerHeartbeatClient


def test_worker_client_heartbeats_provisioned_workspace_worker() -> None:
    """Worker heartbeat selects the configured project and worker ID."""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Record one worker heartbeat request and return its API response."""

        requests.append(request)
        return httpx.Response(200, json={})

    client = WorkerHeartbeatClient(
        api_base_url='https://api.example/api/v1',
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.heartbeat(project_id='project-1', worker_id='worker-1')

    assert [(request.method, request.url.path) for request in requests] == [
        ('POST', '/api/v1/workers/worker-1/heartbeat'),
    ]
    assert all(
        request.headers['X-Project-ID'] == 'project-1'
        for request in requests
    )
