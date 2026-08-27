"""HTTP client for activity-run checkpoint operations."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class ActivityRunClient:
    """Fetch and advance Activity runs allocated to a claimed Pipeline run."""

    def __init__(
        self,
        *,
        api_base_url: str,
        client: httpx.Client | None = None,
    ) -> None:
        """Store the API endpoint and optionally inject an HTTP client for tests."""

        self._api_base_url = api_base_url.rstrip('/')
        self._client = client or httpx.Client(timeout=300.0)

    def get_run(
        self,
        *,
        project_id: str,
        activity_id: str,
        run_id: str,
    ) -> dict[str, object]:
        """Return one project-scoped Activity run from the API."""

        return self._request(
            method='GET',
            project_id=project_id,
            path=self._run_path(activity_id=activity_id, run_id=run_id),
        )

    def continue_run(
        self,
        *,
        project_id: str,
        activity_id: str,
        run_id: str,
        pipeline_run_id: str,
        lease_token: str,
        continuation_token: str,
        idempotency_key: str,
        result: dict[str, object],
    ) -> dict[str, object]:
        """Submit one idempotent local checkpoint result and return the next state."""

        return self._request(
            method='POST',
            project_id=project_id,
            path=f'{self._run_path(activity_id=activity_id, run_id=run_id)}/continue',
            payload={
                'pipeline_run_id': pipeline_run_id,
                'lease_token': lease_token,
                'continuation_token': continuation_token,
                'idempotency_key': idempotency_key,
                'result': result,
            },
        )

    def _request(
        self,
        *,
        method: str,
        project_id: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Send one checkpoint request and require an Activity-run object response."""

        try:
            response = self._client.request(
                method,
                f'{self._api_base_url}{path}',
                json=payload,
                headers={'X-Project-ID': project_id},
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f'Activity checkpoint request failed: {exc}') from exc
        if response.is_error:
            raise RuntimeError(
                f'Activity checkpoint request returned HTTP {response.status_code}: '
                f'{response.text}'
            )
        value: Any = response.json()
        if not isinstance(value, dict):
            raise RuntimeError('Activity checkpoint response must be a JSON object.')
        return value

    @staticmethod
    def _run_path(*, activity_id: str, run_id: str) -> str:
        """Build the encoded API path for one Activity run."""

        return (
            f'/activities/{quote(activity_id, safe="")}/runs/'
            f'{quote(run_id, safe="")}'
        )
