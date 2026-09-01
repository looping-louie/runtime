"""HTTP client for runtime worker registration and heartbeats."""

from __future__ import annotations

from urllib.parse import quote

import httpx


class WorkerHeartbeatClient:
    """Provision runtime workers and refresh their API liveness."""

    def __init__(
        self,
        *,
        api_base_url: str,
        user_id: str,
        client: httpx.Client | None = None,
    ) -> None:
        """Store the API endpoint and optionally inject an HTTP client for tests."""

        self._api_base_url = api_base_url.rstrip('/')
        self._user_id = user_id
        self._client = client or httpx.Client(timeout=60.0)

    def provision(
        self,
        *,
        project_id: str,
        harnesses: tuple[str, ...],
    ) -> str:
        """Create one worker with detected capabilities and return its API ID."""

        response = self._request(
            method='POST',
            project_id=project_id,
            path='/workers',
            payload={'harnesses': [
                {'kind': harness, 'version': 'v1', 'config': {}}
                for harness in harnesses
            ]},
        )
        worker_id = response.get('id')
        if not isinstance(worker_id, str) or not worker_id:
            raise RuntimeError('Worker provisioning response is missing its ID.')
        return worker_id

    def heartbeat(
        self,
        *,
        project_id: str,
        worker_id: str,
        harnesses: tuple[str, ...],
    ) -> None:
        """Record a liveness heartbeat for one registered runtime worker."""

        self._request(
            method='POST',
            project_id=project_id,
            path=f'/workers/{quote(worker_id, safe="")}/heartbeat',
            payload={'harnesses': [
                {'kind': harness, 'version': 'v1', 'config': {}}
                for harness in harnesses
            ]},
        )

    def _request(
        self,
        *,
        method: str,
        project_id: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Submit one worker lifecycle request and require a successful response."""

        try:
            response = self._client.request(
                method,
                f'{self._api_base_url}{path}',
                headers={
                    'X-Project-ID': project_id,
                    'X-User-ID': self._user_id,
                },
                json=payload,
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f'Worker lifecycle request failed: {exc}') from exc
        if response.is_error:
            raise RuntimeError(
                f'Worker lifecycle request returned HTTP {response.status_code}: '
                f'{response.text}'
            )
        value = response.json()
        if not isinstance(value, dict):
            raise RuntimeError('Worker lifecycle response must be a JSON object.')
        return value
