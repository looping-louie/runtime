"""Tests for runtime worker heartbeat HTTP requests."""

from __future__ import annotations

import httpx

from clients.worker_client import WorkerHeartbeatClient


def test_worker_client_heartbeats_global_worker() -> None:
    """Worker heartbeat authenticates as the Worker owner."""

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

    client.heartbeat(
        worker_id='worker-1',
        harnesses=('louie',),
    )

    assert [(request.method, request.url.path) for request in requests] == [
        ('POST', '/api/v1/workers/worker-1/heartbeat'),
    ]
    assert all('X-Project-ID' not in request.headers for request in requests)
    assert all(request.headers['X-User-ID'] == 'user-1' for request in requests)
    assert requests[0].read() == (
        b'{"harnesses":[{"kind":"louie","version":"v1","config":{}}]}'
    )


def test_worker_client_registers_global_worker_with_detected_harnesses() -> None:
    """Worker registration submits its initial Project and Harnesses."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Validate one worker registration and return its generated ID."""

        assert request.method == 'POST'
        assert request.url.path == '/api/v1/workers'
        assert request.headers['X-Project-ID'] == 'project-1'
        assert request.headers['X-User-ID'] == 'user-1'
        assert request.read() == (
            b'{"project_id":"project-1","harnesses":[{"kind":"louie","version":"v1","config":{}},'
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
