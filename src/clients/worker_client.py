"""HTTP client for runtime worker registration and heartbeats."""

from __future__ import annotations

from urllib.parse import quote

import httpx


class WorkerRegistrationClient:
    """Register configured runtime identities with the API control plane."""

    def __init__(
        self,
        *,
        api_base_url: str,
        client: httpx.Client | None = None,
    ) -> None:
        """Store the API endpoint and optionally inject an HTTP client for tests."""

        self._api_base_url = api_base_url.rstrip('/')
        self._client = client or httpx.Client(timeout=60.0)

    def register(self, *, workspace_id: str, worker_id: str) -> None:
        """Create or refresh one runtime worker registration."""

        self._request(
            method='PUT',
            workspace_id=workspace_id,
            worker_id=worker_id,
            suffix='',
        )

    def heartbeat(self, *, workspace_id: str, worker_id: str) -> None:
        """Record a liveness heartbeat for one registered runtime worker."""

        self._request(
            method='POST',
            workspace_id=workspace_id,
            worker_id=worker_id,
            suffix='/heartbeat',
        )

    def _request(
        self,
        *,
        method: str,
        workspace_id: str,
        worker_id: str,
        suffix: str,
    ) -> None:
        """Submit one worker lifecycle request and require a successful response."""

        try:
            response = self._client.request(
                method,
                f'{self._api_base_url}/workers/{quote(worker_id, safe="")}{suffix}',
                headers={'X-Workspace-ID': workspace_id},
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f'Worker lifecycle request failed: {exc}') from exc
        if response.is_error:
            raise RuntimeError(
                f'Worker lifecycle request returned HTTP {response.status_code}: '
                f'{response.text}'
            )