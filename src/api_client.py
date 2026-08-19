"""HTTP client for claiming queued pipeline runs from the API."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from worker import ClaimedPipelineRun


class PipelineRunClaimClient:
    """Claim queued Pipeline runs for configured runtime workspaces."""

    def __init__(
        self,
        *,
        api_base_url: str,
        client: httpx.Client | None = None,
    ) -> None:
        """Store the API endpoint and optionally inject an HTTP client for tests."""

        self._api_base_url = api_base_url.rstrip('/')
        self._client = client or httpx.Client(timeout=60.0)

    def claim_next(
        self,
        *,
        workspace_id: str,
        worker_id: str,
    ) -> ClaimedPipelineRun | None:
        """Claim one queued workspace run or return None when none are available."""

        try:
            response = self._client.post(
                f'{self._api_base_url}/pipelines/runs/claim',
                json={'worker_id': worker_id},
                headers={'X-Workspace-ID': workspace_id},
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f'Runtime claim request failed: {exc}') from exc
        if response.status_code == httpx.codes.NO_CONTENT:
            return None
        if response.is_error:
            raise RuntimeError(
                f'Runtime claim request returned HTTP {response.status_code}: '
                f'{response.text}'
            )
        return self._to_claim(response.json(), workspace_id=workspace_id)

    def continue_run(
        self,
        *,
        workspace_id: str,
        pipeline_id: str,
        run_id: str,
    ) -> dict[str, object]:
        """Advance a terminal child and return the pipeline's scheduler state."""

        try:
            response = self._client.post(
                f'{self._api_base_url}/pipelines/{quote(pipeline_id, safe="")}/runs/'
                f'{quote(run_id, safe="")}/continue',
                json={},
                headers={'X-Workspace-ID': workspace_id},
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f'Pipeline continuation request failed: {exc}') from exc
        if response.is_error:
            raise RuntimeError(
                f'Pipeline continuation request returned HTTP {response.status_code}: '
                f'{response.text}'
            )
        value: Any = response.json()
        if not isinstance(value, dict):
            raise RuntimeError('Pipeline continuation response must be a JSON object.')
        return value

    def renew_lease(
        self,
        *,
        workspace_id: str,
        pipeline_id: str,
        run_id: str,
        lease_token: str,
    ) -> None:
        """Extend the active claim lease before a runtime-owned mutation."""

        try:
            response = self._client.post(
                f'{self._api_base_url}/pipelines/{quote(pipeline_id, safe="")}/runs/'
                f'{quote(run_id, safe="")}/lease',
                json={'lease_token': lease_token},
                headers={'X-Workspace-ID': workspace_id},
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f'Pipeline lease renewal request failed: {exc}') from exc
        if response.is_error:
            raise RuntimeError(
                f'Pipeline lease renewal request returned HTTP {response.status_code}: '
                f'{response.text}'
            )
        value: Any = response.json()
        if not isinstance(value, dict) or not isinstance(value.get('lease_expires_at'), str):
            raise RuntimeError('Pipeline lease renewal response is missing lease_expires_at.')

    @staticmethod
    def _to_claim(value: Any, *, workspace_id: str) -> ClaimedPipelineRun:
        """Validate and map one successful API claim response."""

        if not isinstance(value, dict):
            raise RuntimeError('Runtime claim response must be a JSON object.')
        run = value.get('run')
        lease_token = value.get('lease_token')
        if not isinstance(run, dict):
            raise RuntimeError('Runtime claim response is missing the run object.')
        if not isinstance(lease_token, str) or not lease_token:
            raise RuntimeError('Runtime claim response is missing a lease token.')
        pipeline_id = _require_text(run, 'pipeline_id')
        run_id = _require_text(run, 'id')
        return ClaimedPipelineRun(
            workspace_id=workspace_id, pipeline_id=pipeline_id,
            run_id=run_id,
            lease_token=lease_token,
            payload=run,
        )


def _require_text(value: dict[str, object], field_name: str) -> str:
    """Return a required non-empty string from one API response object."""

    field_value = value.get(field_name)
    if not isinstance(field_value, str) or not field_value:
        raise RuntimeError(f'Runtime claim response is missing {field_name}.')
    return field_value
