"""HTTP client for discovering and conditionally claiming Pipeline runs."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from runs.models import ClaimedPipelineRun


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
        """Claim one candidate run or return None when no work is available."""

        for pipeline_id in self._active_pipeline_ids(workspace_id=workspace_id):
            for candidate in self._claimable_runs(
                workspace_id=workspace_id,
                pipeline_id=pipeline_id,
            ):
                claim = self._claim_candidate(
                    workspace_id=workspace_id,
                    pipeline_id=pipeline_id,
                    candidate=candidate,
                    worker_id=worker_id,
                )
                if claim is not None:
                    return claim
        return None

    def _active_pipeline_ids(self, *, workspace_id: str) -> list[str]:
        """Return every active Pipeline ID visible in the selected workspace."""

        try:
            response = self._client.get(
                f'{self._api_base_url}/pipelines',
                params={'status': 'active'},
                headers={'X-Workspace-ID': workspace_id},
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f'Pipeline list request failed: {exc}') from exc
        if response.is_error:
            raise RuntimeError(
                f'Pipeline list request returned HTTP {response.status_code}: '
                f'{response.text}'
            )
        value: Any = response.json()
        if not isinstance(value, dict) or not isinstance(value.get('items'), list):
            raise RuntimeError('Pipeline list response must contain an items array.')
        return [_require_text(item, 'id') for item in value['items'] if isinstance(item, dict)]

    def _claimable_runs(
        self,
        *,
        workspace_id: str,
        pipeline_id: str,
    ) -> list[dict[str, object]]:
        """Return the API-approved claim candidates for one Pipeline."""

        encoded_pipeline_id = quote(pipeline_id, safe='')
        try:
            response = self._client.get(
                f'{self._api_base_url}/pipelines/{encoded_pipeline_id}/runs',
                params={'claimable': 'true'},
                headers={'X-Workspace-ID': workspace_id},
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f'Claimable-run list request failed: {exc}') from exc
        if response.is_error:
            raise RuntimeError(
                f'Claimable-run list request returned HTTP {response.status_code}: '
                f'{response.text}'
            )
        value: Any = response.json()
        if not isinstance(value, dict) or not isinstance(value.get('items'), list):
            raise RuntimeError('Claimable-run list response must contain an items array.')
        return [item for item in value['items'] if isinstance(item, dict)]

    def _claim_candidate(
        self,
        *,
        workspace_id: str,
        pipeline_id: str,
        candidate: dict[str, object],
        worker_id: str,
    ) -> ClaimedPipelineRun | None:
        """Claim one listed candidate, returning None when another worker won."""

        run = candidate.get('run')
        etag = candidate.get('etag')
        if not isinstance(run, dict):
            raise RuntimeError('Claimable-run candidate is missing its run object.')
        if not isinstance(etag, str) or not etag:
            raise RuntimeError('Claimable-run candidate is missing its ETag.')
        run_id = _require_text(run, 'id')
        try:
            response = self._client.patch(
                f'{self._api_base_url}/pipelines/{quote(pipeline_id, safe="")}/runs/'
                f'{quote(run_id, safe="")}',
                json={'worker_id': worker_id, 'status': 'claimed'},
                headers={
                    'If-Match': etag,
                    'X-Workspace-ID': workspace_id,
                },
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f'Runtime claim request failed: {exc}') from exc
        if response.status_code == httpx.codes.PRECONDITION_FAILED:
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
        lease_token: str,
    ) -> dict[str, object]:
        """Advance a terminal child and return the pipeline's scheduler state."""

        try:
            response = self._client.post(
                f'{self._api_base_url}/pipelines/{quote(pipeline_id, safe="")}/runs/'
                f'{quote(run_id, safe="")}/continue',
                json={'lease_token': lease_token},
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
    def _to_claim(value: Any, *, workspace_id: str) -> ClaimedPipelineRun | None:
        """Validate and map one successful API claim response."""

        if not isinstance(value, dict):
            raise RuntimeError('Runtime claim response must be a JSON object.')
        run = value.get('run')
        lease_token = value.get('lease_token')
        if not isinstance(run, dict):
            raise RuntimeError('Runtime claim response is missing the run object.')
        if run.get('status') == 'waiting':
            return None
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
