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
        user_id='user-1',
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
    assert all(request.headers['X-User-ID'] == 'user-1' for request in requests)


def test_worker_client_provisions_detected_harnesses() -> None:
    """Initial provisioning submits User, Project, and local Harness capabilities."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Validate one worker registration and return its generated ID."""

        assert request.method == 'POST'
        assert request.url.path == '/api/v1/workers'
        assert request.headers['X-Project-ID'] == 'project-1'
        assert request.headers['X-User-ID'] == 'user-1'
        assert request.read() == (
            b'{"harnesses":[{"kind":"louie","version":"v1","config":{}},'
            b'{"kind":"codex_cli","version":"v1","config":{}}]}'
        )
        return httpx.Response(201, json={'id': 'worker-1'})

    client = WorkerHeartbeatClient(
        api_base_url='https://api.example/api/v1',
        user_id='user-1',
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    worker_id = client.provision(
        project_id='project-1',
        harnesses=('louie', 'codex_cli'),
    )

    assert worker_id == 'worker-1'
