"""Tests for runtime worker registration HTTP requests."""

from __future__ import annotations

import httpx

from clients.worker_client import WorkerRegistrationClient


def test_worker_client_registers_and_heartbeats_workspace_worker() -> None:
    """Worker lifecycle calls select the configured workspace and worker ID."""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Record worker lifecycle requests and return their API response."""

        requests.append(request)
        return httpx.Response(201 if request.method == 'PUT' else 200, json={})

    client = WorkerRegistrationClient(
        api_base_url='https://api.example/api/v1',
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.register(workspace_id='workspace-1', worker_id='worker-1')
    client.heartbeat(workspace_id='workspace-1', worker_id='worker-1')

    assert [(request.method, request.url.path) for request in requests] == [
        ('PUT', '/api/v1/workers/worker-1'),
        ('POST', '/api/v1/workers/worker-1/heartbeat'),
    ]
    assert all(
        request.headers['X-Workspace-ID'] == 'workspace-1'
        for request in requests
    )